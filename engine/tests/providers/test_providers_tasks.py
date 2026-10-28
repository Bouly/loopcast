"""Tâches video.generate / image.generate : de bout en bout par la file, reprise après plantage, coûts, budget."""

import json
from datetime import datetime, timedelta

import pytest
from providers_testkit import (events, image_model, image_router, job_row, job_state, run_until_settled,
                               video_model, video_router)

from loopcast import costs, jobs
from loopcast.providers import tasks
from loopcast.providers.base import probe_video


def enqueue(conn, clock, request: dict, *, content_id="habitudo-fr-0007", shot_index=0, kind="video",
            app_id="habitudo", key=None) -> int:
    payload = {"content_id": content_id, "shot_index": shot_index, "request": request}
    return jobs.enqueue(conn, f"{kind}.generate", payload, app_id=app_id, key=key, clock=clock)


def ledger(conn):
    return conn.execute("SELECT * FROM cost_ledger ORDER BY id").fetchall()


def submissions(router) -> int:
    return sum(len(p.submitted) for p in router.providers.values())


def test_video_generate_end_to_end(conn, config, clock):
    router = video_router([video_model("std-a", usd_per_s=0.10)], clock, delay_s=45)
    services = {"video": router}
    job_id = enqueue(conn, clock, {"prompt": "A runner at dawn", "duration_s": 5, "audio": True}, shot_index=2)

    jobs.run_one(conn, config, "w", clock=clock, services=services)              # budget + soumission
    state = job_state(conn, job_id)
    assert job_row(conn, job_id)["status"] == "queued"
    assert state["handle"].startswith("std-a|fake-") and state["estimate_usd"] == pytest.approx(0.50)
    assert state["billed_duration_s"] == 5 and state["provider"] == "fake"

    assert run_until_settled(conn, config, clock, services, job_id) == "done"
    row = job_row(conn, job_id)
    result = json.loads(row["result"])
    assert row["attempts"] <= 1                                                  # les sondages ne coûtent pas d'essai
    path = config.data_dir / "media" / "habitudo-fr-0007" / "shot-02.mp4"
    assert result["path"] == str(path) and path.is_file()
    info = probe_video(path)
    assert info.duration_s == pytest.approx(5.0, abs=0.05) and info.has_audio and info.height > info.width
    assert result["duration_s"] == pytest.approx(5.0, abs=0.05) and result["requested_duration_s"] == 5
    assert result["model"] == "std-a" and result["provider"] == "fake" and result["ai_label"] is True
    assert result["cost_usd"] == pytest.approx(0.50) and result["estimated"] is False
    rows = ledger(conn)
    assert len(rows) == 1 and rows[0]["kind"] == "video" and rows[0]["app_id"] == "habitudo"
    assert rows[0]["cost_usd"] == pytest.approx(0.50) and rows[0]["estimated"] == 0 and rows[0]["job_id"] == job_id
    assert submissions(router) == 1


def test_resume_after_crash_never_submits_twice(conn, config, clock):
    """Le Mac redémarre pendant le sondage : un nouveau processus reprend la même génération."""
    models = [video_model("std-a")]
    first = video_router(models, clock, delay_s=120)
    job_id = enqueue(conn, clock, {"prompt": "Waves at sunset", "duration_s": 4})
    jobs.run_one(conn, config, "w1", clock=clock, services={"video": first})    # soumis, identifiant gardé
    clock.advance(seconds=11)
    assert jobs.claim(conn, "w1", clock=clock).id == job_id                     # pris… et le processus meurt
    clock.advance(seconds=601)
    assert jobs.requeue_expired(conn, clock=clock) == 1

    restarted = video_router(models, clock, delay_s=120)                        # rien en mémoire
    assert run_until_settled(conn, config, clock, {"video": restarted}, job_id) == "done"
    assert submissions(first) == 1 and submissions(restarted) == 0
    assert len(ledger(conn)) == 1


def test_cost_is_recorded_once_when_a_finished_step_is_replayed(conn, config, clock):
    """Plantage entre l'inscription du coût et la fin de la tâche : rejouer n'inscrit rien de plus."""
    router = video_router([video_model("std-a")], clock)
    services = {"video": router}
    payload = {"content_id": "c1", "shot_index": 0, "request": {"prompt": "A dog runs", "duration_s": 2}}
    job_id = jobs.enqueue(conn, "video.generate", payload, clock=clock)
    jobs.run_one(conn, config, "w", clock=clock, services=services)
    state = job_state(conn, job_id)
    job = jobs.Job(job_id, "video.generate", None, payload, 1, 5, None, None)
    ctx = jobs.JobContext(conn=conn, config=config, job=job, clock=clock, services=services)
    first = tasks.advance(ctx, "video", payload, state)
    again = tasks.advance(ctx, "video", payload, state)
    assert first["path"] == again["path"] and first["cost_usd"] == again["cost_usd"] == pytest.approx(0.20)
    assert len(ledger(conn)) == 1 and submissions(router) == 1


def test_budget_downgrade_then_wait_until_tomorrow(conn, config, clock):
    config.settings["budget"] = {"daily_usd": 3.0, "daily_usd_per_app": 3.0, "monthly_usd": 100}
    router = video_router([video_model("pre-a", "premium", 0.50), video_model("std-a", "standard", 0.10)], clock)
    services = {"video": router}
    costs.record(conn, at=clock(), provider="fal", kind="video", cost_usd=1.0, app_id="habitudo")

    # 1 $ déjà dépensé : pre-a (2,50 $) ne passe pas sous 3 $, std-a (0,50 $) si → un niveau en dessous.
    job_id = enqueue(conn, clock, {"prompt": "UGC selfie, a woman talks", "duration_s": 5, "quality": "premium"})
    assert run_until_settled(conn, config, clock, services, job_id) == "done"
    result = json.loads(job_row(conn, job_id)["result"])
    assert result["model"] == "std-a" and result["tier"] == "standard" and result["downgraded"]
    assert any(kind == "providers.downgrade" and "premium → standard" in msg for kind, msg in events(conn))

    # 2,70 $ dépensés : plus rien ne passe (pre-a 2,50 $, std-a 0,50 $) → attente jusqu'à demain.
    costs.record(conn, at=clock(), provider="fal", kind="video", cost_usd=1.2, app_id="habitudo")
    waiting = enqueue(conn, clock, {"prompt": "Another shot", "duration_s": 5, "quality": "premium"}, shot_index=1)
    jobs.run_one(conn, config, "w", clock=clock, services=services)
    row = job_row(conn, waiting)
    tomorrow = costs.day_start(clock()) + timedelta(days=1)
    assert row["status"] == "queued" and row["attempts"] == 0                      # attendre ne coûte pas d'essai
    assert tomorrow < datetime.fromisoformat(row["run_after"]) < tomorrow + timedelta(minutes=10)
    assert job_state(conn, waiting)["budget_wait_until"] == jobs.iso(tomorrow)
    budget_events = [msg for kind, msg in events(conn) if kind == "providers.budget"]
    assert len(budget_events) == 1 and "plafond du jour" in budget_events[0]

    assert run_until_settled(conn, config, clock, services, waiting) == "done"     # le lendemain, ça repart
    assert json.loads(job_row(conn, waiting)["result"])["model"] == "pre-a"        # budget du jour neuf
    assert submissions(router) == 2


def test_inflight_generations_count_against_the_budget(conn, config, clock):
    """Deux générations simultanées : la seconde voit ce que la première va coûter."""
    config.settings["budget"] = {"daily_usd": 1.0, "daily_usd_per_app": 1.0, "monthly_usd": 100}
    router = video_router([video_model("std-a", usd_per_s=0.12)], clock, delay_s=300)
    services = {"video": router}
    a = enqueue(conn, clock, {"prompt": "Shot A", "duration_s": 5}, shot_index=0)
    b = enqueue(conn, clock, {"prompt": "Shot B", "duration_s": 5}, shot_index=1)
    jobs.run_one(conn, config, "w", clock=clock, services=services)               # A soumis (0,60 $ en cours)
    assert tasks.inflight_usd(conn) == pytest.approx(0.60)
    jobs.run_one(conn, config, "w", clock=clock, services=services)               # B : 0,60 + 0,60 > 1 $
    assert job_state(conn, a).get("handle") and not job_state(conn, b).get("handle")
    assert job_state(conn, b)["budget_wait_until"]


def test_provider_failure_switches_to_another_model_of_the_same_tier(conn, config, clock):
    models = [video_model("std-a"), video_model("std-b", usd_per_s=0.12), video_model("eco-a", "eco", 0.02)]
    router = video_router(models, clock, per_model={"std-a": {"fail_first": 5}})
    job_id = enqueue(conn, clock, {"prompt": "City at night", "duration_s": 3})
    assert run_until_settled(conn, config, clock, {"video": router}, job_id) == "done"
    result = json.loads(job_row(conn, job_id)["result"])
    assert result["model"] == "std-b" and result["retries"] == 1                 # pas descendu en éco
    retry = [msg for kind, msg in events(conn) if kind == "providers.retry"]
    assert len(retry) == 1 and "std-a" in retry[0] and "std-b" in retry[0]
    assert [r["model"] for r in ledger(conn)] == ["std-b"]                       # l'échec n'est pas facturé


def test_repeated_failures_end_dead_then_manual_retry_starts_fresh(conn, config, clock):
    router = video_router([video_model("std-a")], clock, fail_first=3)
    job_id = enqueue(conn, clock, {"prompt": "Mountains", "duration_s": 2})
    assert run_until_settled(conn, config, clock, {"video": router}, job_id) == "dead"
    row = job_row(conn, job_id)
    assert "abandonné après 3 échecs" in row["last_error"] and "échec simulé" in row["last_error"]
    assert submissions(router) == 3
    assert any(kind == "job_dead" for kind, _ in events(conn, prefix="job_"))
    assert jobs.retry(conn, job_id, clock=clock)                                   # relance depuis le dashboard
    assert run_until_settled(conn, config, clock, {"video": router}, job_id) == "done"
    assert submissions(router) == 4


def test_too_long_generation_is_cancelled_and_retried(conn, config, clock):
    config.settings["providers"] = {"video": {"max_wait_s": 120, "poll_initial_s": 30}}
    router = video_router([video_model("std-a"), video_model("std-b")], clock,
                          per_model={"std-a": {"delay_s": 10_000}})
    job_id = enqueue(conn, clock, {"prompt": "Forest", "duration_s": 2})
    assert run_until_settled(conn, config, clock, {"video": router}, job_id) == "done"
    assert json.loads(job_row(conn, job_id)["result"])["model"] == "std-b"
    assert any("délai maximal dépassé (2 min" in msg for _, msg in events(conn))


def test_invalid_requests_die_with_a_clear_reason(conn, config, clock):
    router = video_router([video_model("std-a", max_s=8)], clock)
    services = {"video": router}
    bad = enqueue(conn, clock, {"prompt": "", "duration_s": 5}, key="bad")
    too_long = enqueue(conn, clock, {"prompt": "x", "duration_s": 12}, key="too-long")
    no_model = enqueue(conn, clock, {"prompt": "x", "duration_s": 9}, key="no-model")
    no_image = enqueue(conn, clock, {"prompt": "x", "duration_s": 2, "image_path": "absent.png"}, key="no-image")
    bad_id = jobs.enqueue(conn, "video.generate", {"content_id": "../etc", "request": {"prompt": "x", "duration_s": 2}},
                          clock=clock)
    for job_id in (bad, too_long, no_model, no_image, bad_id):
        assert run_until_settled(conn, config, clock, services, job_id) == "dead"
    assert "requête video invalide" in job_row(conn, bad)["last_error"]
    assert "duration_s" in job_row(conn, too_long)["last_error"]                  # 10 s au plus (contrat)
    assert "aucun modèle video" in job_row(conn, no_model)["last_error"]
    assert "image de départ introuvable" in job_row(conn, no_image)["last_error"]
    assert "content_id" in job_row(conn, bad_id)["last_error"]
    assert submissions(router) == 0 and not ledger(conn)


def test_start_image_must_have_the_shot_format(conn, config, clock, tmp_path):
    """Une capture d'iPhone (9:19,5) est refusée avant de payer ; une image 9:16 part en image→vidéo."""
    from PIL import Image

    screenshot, framed = tmp_path / "screenshot.png", tmp_path / "framed.png"
    Image.new("RGB", (1290, 2796), (240, 240, 245)).save(screenshot)
    Image.new("RGB", (1080, 1920), (240, 240, 245)).save(framed)
    router = video_router([video_model("std-a", endpoint_i2v=None), video_model("std-i2v")], clock)
    services = {"video": router}
    refused = enqueue(conn, clock, {"prompt": "App demo", "duration_s": 3, "image_path": str(screenshot)}, key="r")
    assert run_until_settled(conn, config, clock, services, refused) == "dead"
    assert "image de départ 1290×2796 : le plan est en 9:16" in job_row(conn, refused)["last_error"]
    ok = enqueue(conn, clock, {"prompt": "App demo", "duration_s": 3, "image_path": str(framed)}, key="ok")
    assert run_until_settled(conn, config, clock, services, ok) == "done"
    assert json.loads(job_row(conn, ok)["result"])["model"] == "std-i2v"
    assert submissions(router) == 1


def test_image_generate_end_to_end(conn, config, clock):
    router = image_router([image_model("img-a", usd_per_image=0.04)], clock, delay_s=5)
    job_id = enqueue(conn, clock, {"prompt": "Pastel background, phone mockup"}, kind="image", shot_index=3)
    assert run_until_settled(conn, config, clock, {"image": router}, job_id) == "done"
    result = json.loads(job_row(conn, job_id)["result"])
    assert result["path"].endswith("habitudo-fr-0007/image-03.png") and result["height"] > result["width"]
    assert result["cost_usd"] == pytest.approx(0.04) and "duration_s" not in result
    rows = ledger(conn)
    assert len(rows) == 1 and rows[0]["kind"] == "image" and rows[0]["unit"] == "images"


def test_free_fake_provider_records_nothing(conn, config, clock):
    """Mode démo : le faux fournisseur gratuit ne remplit pas le registre des coûts."""
    from loopcast.providers.fake import FakeVideoProvider
    from loopcast.providers.router import Router

    model = video_model("demo")
    router = Router("video", [model], {"demo": FakeVideoProvider(model, scale=0.25)}, mode="fake", why="démo")
    job_id = enqueue(conn, clock, {"prompt": "Demo", "duration_s": 1})
    assert run_until_settled(conn, config, clock, {"video": router}, job_id) == "done"
    assert json.loads(job_row(conn, job_id)["result"])["cost_usd"] == 0 and not ledger(conn)


def test_run_inline_for_the_cli(conn, config, clock):
    router = video_router([video_model("std-a")], clock, delay_s=20)
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        clock.advance(seconds=seconds)

    result = tasks.run_inline(conn, config, {"video": router}, "video",
                              {"content_id": "essai", "shot_index": 0, "request": {"prompt": "x", "duration_s": 1}},
                              clock=clock, sleep=sleep)
    assert result["model"] == "std-a" and waits[0] == 10 and waits[1] == 15
    assert ledger(conn)[0]["job_id"] is None
