"""ideas.ensure_stock : calcul du manque par téléphone, lots bornés, idempotence par tranche horaire."""

import itertools
import json

import pytest

from loopcast import jobs, llm
from loopcast.strategy import store

from .helpers import APP, approve_strategy, events, job_row, make_config, make_idea, make_strategy, run_jobs

SETTINGS = {"pipeline": {"stock_target": 6, "ideas_per_batch": 4}}
_keys = itertools.count()


@pytest.fixture
def services():
    return {"llm": llm.FakeLLM({})}


def _ensure(conn, config, clock, services):
    jid = jobs.enqueue(conn, "ideas.ensure_stock", {"app_id": APP}, key=f"stock-{next(_keys)}", app_id=APP,
                       clock=clock)
    run_jobs(conn, config, clock, services, kinds=("ideas.ensure_stock",))
    return job_row(conn, jid)


def _generate_jobs(conn):
    return {json.loads(r["payload"])["phone_id"]: (json.loads(r["payload"])["count"], r["key"])
            for r in conn.execute("SELECT * FROM jobs WHERE kind='ideas.generate' ORDER BY id")}


def _idea(conn, now, idea_id, status, phone="phone-1"):
    conn.execute("""INSERT INTO ideas(id, app_id, phone_id, account_id, lang, format, hook, idea, status, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                 (idea_id, APP, phone, f"{phone}:tiktok", "fr", "hook-demo", idea_id, make_idea().model_dump_json(),
                  status, jobs.iso(now)))


def _content(conn, content_id, status, *, idea=None, account="phone-1:tiktok", app=APP):
    conn.execute("INSERT INTO content(id, app_id, idea_id, account_id, format, lang, status) VALUES (?,?,?,?,?,?,?)",
                 (content_id, app, idea, account, "hook-demo", "fr", status))


def _post(conn, content_id, status, platform="tiktok"):
    conn.execute("INSERT INTO posts(content_id, account_id, platform, status) VALUES (?,?,?,?)",
                 (content_id, f"phone-1:{platform}", platform, status))


def test_stock_counts_what_waits_to_be_published(sconn, tmp_path, seeded, clock, services):
    approve_strategy(sconn, clock())
    now = clock()
    for idea_id, status in (("i1", "approved"), ("i2", "approved"), ("i3", "producing"), ("i4", "rejected"),
                            ("i5", "produced"), ("i6", "produced"), ("i7", "proposed")):
        _idea(sconn, now, idea_id, status)
    _content(sconn, "ready", "approved", idea="i5")               # compte : idée produite, contenu prêt
    _content(sconn, "posted", "approved", idea="i6")              # publié : ne compte plus
    _post(sconn, "posted", "posted")
    _content(sconn, "rendering", "rendering", idea="i3")          # déjà compté avec son idée
    _content(sconn, "planned", "rendered", account="phone-1:instagram")   # planifié, pas encore publié
    _post(sconn, "planned", "scheduled", platform="instagram")
    _content(sconn, "draft-sent", "approved")                      # brouillon TikTok envoyé : consommé
    _post(sconn, "draft-sent", "needs_human")
    _content(sconn, "trash", "rejected")
    _content(sconn, "other-app", "approved", app="autre")

    # « planned » est rendu mais pas encore contrôlé : il est encore en production, pas « à valider ».
    assert store.phone_stock(sconn, APP, "phone-1") == {
        "ideas": 4, "content": 2, "pending": 0, "total": 6,
        "proposed": 1, "producing": 4, "to_review": 0, "ready": 1}
    _idea(sconn, now, "i8", "approved", phone="phone-2")
    assert store.phone_stock(sconn, APP, "phone-2")["total"] == 1


def test_stock_tells_videos_to_review_from_videos_ready_to_publish(sconn, seeded, clock):
    """« 6 vidéos prêtes » mélangeait ce qui attend la validation et ce qui est validé : le détail les sépare."""
    approve_strategy(sconn, clock())
    now = clock()
    for idea_id in ("r1", "r2", "a1"):
        _idea(sconn, now, idea_id, "produced")
    _content(sconn, "r1", "rendered", idea="r1")
    _content(sconn, "r2", "rendered", idea="r2")
    _content(sconn, "a1", "approved", idea="a1")
    sconn.execute("""UPDATE content SET qa=? WHERE id IN ('r1', 'a1')""", (json.dumps({"ok": True}),))
    sconn.execute("""UPDATE content SET qa=? WHERE id='r2'""", (json.dumps({"ok": False}),))

    stock = store.phone_stock(sconn, APP, "phone-1")
    assert (stock["to_review"], stock["ready"], stock["producing"], stock["proposed"]) == (1, 1, 1, 0)
    assert stock["content"] == 3 and stock["total"] == 3


def test_missing_ideas_are_ordered_per_phone_in_bounded_batches(sconn, tmp_path, seeded, clock, services):
    config = make_config(tmp_path, SETTINGS)
    approve_strategy(sconn, clock())
    for n in range(5):
        _idea(sconn, clock(), f"i{n}", "approved")

    row = _ensure(sconn, config, clock, services)
    assert row["status"] == "done"
    bucket = "20261102T09"
    assert _generate_jobs(sconn) == {
        "phone-1": (1, f"ideas.generate:{APP}:phone-1:{bucket}"),
        "phone-2": (4, f"ideas.generate:{APP}:phone-2:{bucket}"),
        "phone-3": (4, f"ideas.generate:{APP}:phone-3:{bucket}"),
    }
    report = json.loads(row["result"])["phones"]
    assert report["phone-1"]["missing"] == 1 and report["phone-2"]["missing"] == 6 and "phone-4" not in report
    child = sconn.execute("SELECT * FROM jobs WHERE kind='ideas.generate'").fetchone()
    assert child["app_id"] == APP and child["parent_id"] == row["id"]


def test_ensure_stock_is_idempotent_and_counts_ordered_ideas(sconn, tmp_path, seeded, clock, services):
    config = make_config(tmp_path, SETTINGS)
    approve_strategy(sconn, clock())
    _ensure(sconn, config, clock, services)
    clock.advance(minutes=20)
    again = _ensure(sconn, config, clock, services)                # même heure : rien de plus
    assert sconn.execute("SELECT COUNT(*) FROM jobs WHERE kind='ideas.generate'").fetchone()[0] == 3
    assert json.loads(again["result"])["phones"]["phone-2"]["pending"] == 4

    clock.advance(hours=1)                                          # les lots commandés comptent
    _ensure(sconn, config, clock, services)
    counts = [json.loads(r["payload"])["count"] for r in
              sconn.execute("SELECT payload FROM jobs WHERE kind='ideas.generate' ORDER BY id")]
    assert counts == [4, 4, 4, 2, 2, 2]                            # 6 visées : 4 déjà commandées, 2 de plus
    clock.advance(hours=1)
    _ensure(sconn, config, clock, services)
    assert sconn.execute("SELECT COUNT(*) FROM jobs WHERE kind='ideas.generate'").fetchone()[0] == 6


def test_inactive_app_or_missing_claude_orders_nothing(sconn, tmp_path, seeded, clock, services):
    config = make_config(tmp_path, SETTINGS)
    assert "statut « brief_ready »" in json.loads(_ensure(sconn, config, clock, services)["result"])["skipped"]
    approve_strategy(sconn, clock())
    for _ in range(2):
        row = _ensure(sconn, config, clock, {"llm": llm.UnavailableLLM()})
    assert json.loads(row["result"]) == {"skipped": "aucune clé Claude"}
    assert len(events(sconn, "strategy.no_llm")) == 1                # alerte une fois, pas à chaque tour
    sconn.execute("UPDATE apps SET status='paused'")
    assert "paused" in json.loads(_ensure(sconn, config, clock, services)["result"])["skipped"]
    assert _generate_jobs(sconn) == {}


def test_phones_without_voice_or_accounts_are_skipped(sconn, tmp_path, seeded, clock, services):
    config = make_config(tmp_path, SETTINGS)
    config.phones[1].accounts = {}                                  # phone-2 : comptes pas encore créés
    approve_strategy(sconn, clock(), make_strategy(phones=(("phone-1", "fr"), ("phone-2", "en"))))
    for _ in range(2):
        row = _ensure(sconn, config, clock, services)
    report = json.loads(row["result"])["phones"]
    assert report["phone-2"] == {"skipped": "aucun compte configuré"}
    assert report["phone-3"]["skipped"] == "pas de voix dans la stratégie"
    assert list(_generate_jobs(sconn)) == ["phone-1"]
    assert len(events(sconn, "strategy.voice_missing")) == 1


def test_settings_defaults_and_legacy_key():
    assert store.pipeline_settings({}) == {"auto_approve_strategy": False, "idea_review": "auto", "stock_target": 6,
                                           "ideas_per_batch": 6, "posts_per_day_per_account": 3}
    assert store.pipeline_settings({"stock_target": 9})["stock_target"] == 9
    custom = store.pipeline_settings({"stock_target": 9, "pipeline": {"stock_target": 4, "ideas_per_batch": 40,
                                                                      "idea_review": "Manual"}})
    assert (custom["stock_target"], custom["ideas_per_batch"], custom["idea_review"]) == (4, store.MAX_BATCH, "manual")
    assert store.new_idea_status({"pipeline": {"idea_review": "manual"}}) == "proposed"
    assert store.new_idea_status({}) == "approved"


def test_reapproved_idea_after_rejected_video_is_really_produced_again(sconn, seeded, clock):
    """Vidéo rejetée dans la file de validation, puis idée approuvée à nouveau : la production repart pour de
    bon. Avant : la tâche content.produce:<idée>, déjà terminée, était renvoyée telle quelle ; rien ne
    repartait, l'idée restait « approved » pour toujours et comptait dans le stock."""
    from loopcast.production import review

    approve_strategy(sconn, clock())
    _idea(sconn, clock(), "i1", "produced")
    first = store.enqueue_production(sconn, "i1", APP, clock())
    sconn.execute("UPDATE jobs SET status='done' WHERE id=?", (first,))              # la production a eu lieu
    sconn.execute("""INSERT INTO content(id, app_id, idea_id, account_id, format, lang, status, qa, run)
                     VALUES ('i1', ?, 'i1', 'phone-1:tiktok', 'hook-demo', 'fr', 'rendered', '{"ok": true}', 0)""",
                  (APP,))
    review.reject(sconn, "i1", clock(), "accroche trop faible")
    assert store.get_idea(sconn, "i1")["status"] == "rejected"

    out = store.approve_idea(sconn, "i1", clock())
    assert out["status"] == "producing" and out["job_id"] != first
    job = job_row(sconn, out["job_id"])
    assert (job["key"], job["status"], json.loads(job["payload"])["run"]) == ("content.produce:i1:r1", "queued", 1)
    assert store.get_idea(sconn, "i1")["status"] == "producing"
    content = sconn.execute("SELECT status, run FROM content WHERE id='i1'").fetchone()
    assert (content["status"], content["run"]) == ("draft", 1)
    with pytest.raises(store.Conflict, match="producing"):                            # pas deux relances
        store.approve_idea(sconn, "i1", clock())
