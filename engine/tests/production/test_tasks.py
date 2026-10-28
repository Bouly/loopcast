"""Tâches content.* : du content.produce au contrôle qualité, avec un faux moteur de rendu (vrais fichiers)."""

import json
import sys
import textwrap
from pathlib import Path

import pytest

from loopcast import jobs
from loopcast.production import assets, renderer, store
from loopcast.production.tasks import _hashtags
from loopcast.schemas import Shot

from .conftest import FakeRenderer, make_video, needs_ffmpeg, story_shots

pytestmark = needs_ffmpeg

HOOK_DEMO = {"hook": "Arrête de compter sur ta **motivation**",
             "screens": [{"caption": "Choisis 3 habitudes", "asset_id": None},
                         {"caption": "Coche-les chaque soir", "mock": {"kind": "stat", "title": "Série",
                                                                       "value": "21", "label": "jours"}}]}


def hook_demo(pipe) -> str:
    props = json.loads(json.dumps(HOOK_DEMO))
    props["screens"][0]["asset_id"] = pipe.screenshot()
    return pipe.idea("hook-demo", props=props)


# --- Format Remotion à props --------------------------------------------------------------------------------

def test_remotion_format_end_to_end(pipe):
    idea_id = hook_demo(pipe)
    pipe.produce(idea_id)
    fake = FakeRenderer()
    pipe.run(fake)

    c = pipe.content(idea_id)
    assert c["status"] == "rendered" and store.to_review(c)
    assert pipe.idea_row(idea_id)["status"] == "produced"
    assert (c["app_id"], c["idea_id"], c["account_id"], c["format"], c["lang"], c["kind"]) == \
        ("habitudo", idea_id, "phone-1:tiktok", "hook-demo", "fr", "video")
    assert json.loads(c["hashtags"]) == ["#habitudes", "#Routine"] and c["caption"] == "Ta routine en 3 habitudes"
    assert c["ai_label"] == 0 and c["cost_usd"] == 0 and c["duration_s"] == pytest.approx(8, abs=0.2)

    files = json.loads(c["files"])
    out = store.content_dir(pipe.config, idea_id)
    assert files == [str(out / f"{idea_id}.mp4")] and Path(files[0]).is_file()
    assert (out / "poster.jpg").is_file() and not (out / ".r0").exists()

    job = fake.calls[0]
    assert job.composition == "hook-demo"
    brand = job.props["brand"]
    assert brand == {"name": "Habitudo", "accent": "#5B5BF7", "handle": "@habitudo",
                     "storeLine": "Gratuit sur l'App Store"}
    assert job.props["cta"] == "Lance ta série ce soir" and job.props["lang"] == "fr"
    src = job.props["screens"][0]["src"]
    assert src.startswith("apps/habitudo/") and (pipe.root / "render" / "public" / src).is_file()
    report = json.loads(c["qa"])
    assert report["ok"] and report["run"] == 0 and report["probe"]["width"] == 1080


def test_review_mode_auto_approves(pipe):
    pipe.config.settings = {"pipeline": {"review_mode": "auto"}}
    idea_id = hook_demo(pipe)
    pipe.produce(idea_id)
    pipe.run(FakeRenderer())
    c = pipe.content(idea_id)
    assert c["status"] == "approved" and c["approved_at"]
    assert pipe.conn.execute("SELECT COUNT(*) FROM events WHERE kind='content.approved'").fetchone()[0] == 1


def test_carousel(pipe):
    slides = [{"title": "5 habitudes\nqui changent tout"}, {"title": "Lire", "body": "10 pages"},
              {"title": "Marcher"}, {"title": "Dormir"}]
    idea_id = pipe.idea("slideshow", props={"slides": slides})
    pipe.produce(idea_id)
    fake = FakeRenderer()
    pipe.run(fake)
    c = pipe.content(idea_id)
    assert fake.calls[0].stills == 5 and c["kind"] == "carousel"
    assert c["status"] == "rendered" and len(json.loads(c["files"])) == 5
    assert [Path(f).name for f in json.loads(c["files"])] == ["01.png", "02.png", "03.png", "04.png", "05.png"]


def test_produce_is_idempotent(pipe):
    idea_id = hook_demo(pipe)
    pipe.produce(idea_id)
    jobs.enqueue(pipe.conn, "content.produce", {"idea_id": idea_id}, key="autre-cle", clock=pipe.clock)
    pipe.run(FakeRenderer())                         # la 2e passe refait la préparation, sans rien dupliquer
    assert pipe.conn.execute("SELECT COUNT(*) FROM content").fetchone()[0] == 1
    assert len(pipe.jobs("content.render")) == 1 and len(pipe.jobs("content.qa")) == 1
    late = jobs.enqueue(pipe.conn, "content.produce", {"idea_id": idea_id}, key="encore", clock=pipe.clock)
    pipe.run(FakeRenderer())
    result = pipe.conn.execute("SELECT result FROM jobs WHERE id=?", (late,)).fetchone()["result"]
    assert json.loads(result) == {"skipped": "contenu déjà rendered"}
    assert pipe.content(idea_id)["status"] == "rendered" and len(pipe.jobs("content.render")) == 1


def test_winner_variation_keeps_its_parent(pipe):
    """ideas.parent_id = l'id du CONTENU gagnant (contrat strategy) : reporté dans content.parent_id."""
    idea_id = hook_demo(pipe)
    pipe.conn.execute("UPDATE ideas SET parent_id='habitudo-fr-gagnant-0001' WHERE id=?", (idea_id,))
    pipe.produce(idea_id)
    pipe.run(FakeRenderer())
    assert pipe.content(idea_id)["parent_id"] == "habitudo-fr-gagnant-0001"


def test_invalid_trims_fail_before_any_generation(pipe):
    rec = pipe.recording(12)
    shots = [Shot(kind="text_card", duration_s=2, visual="", prompt="", asset_id=None, on_screen_text="Ma routine",
                  voiceover=""),
             Shot(kind="app_recording", duration_s=6, visual="", prompt="", asset_id=rec, on_screen_text="",
                  voiceover="")]
    idea_id = pipe.idea("demo-recording", shots=shots, props_json=json.dumps({"trims": {"0": 4}}))
    pipe.produce(idea_id)
    pipe.run(FakeRenderer())
    assert "trims[0] : le plan 0 n'est pas un passage de vidéo de démo" in pipe.content(idea_id)["error"]


def test_invalid_idea_fails_clearly(pipe):
    idea_id = pipe.idea("notes-app", props={"title": "x" * 80, "items": ["a"]})
    job_id = pipe.produce(idea_id)
    pipe.run(FakeRenderer())
    job = pipe.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert job["status"] == "dead" and "idée invalide pour notes-app" in job["last_error"]
    c = pipe.content(idea_id)
    assert c["status"] == "failed" and "60 au plus" in c["error"] and "entre 3 et 7" in c["error"]
    assert pipe.idea_row(idea_id)["status"] == "failed"
    assert pipe.conn.execute("SELECT COUNT(*) FROM events WHERE kind='content.failed'").fetchone()[0] == 1


def test_unknown_idea_and_unusable_capture(pipe):
    job_id = jobs.enqueue(pipe.conn, "content.produce", {"idea_id": "nope"}, clock=pipe.clock)
    pipe.run(FakeRenderer())
    assert "idée introuvable : nope" in pipe.conn.execute("SELECT last_error FROM jobs WHERE id=?", (job_id,)).fetchone()[0]

    props = json.loads(json.dumps(HOOK_DEMO))
    props["screens"][0]["asset_id"] = pipe.screenshot("prive.png", analysis={"usable_in_video": False,
                                                                             "caution": "adresse e-mail visible"})
    idea_id = pipe.idea("hook-demo", props=props)
    pipe.produce(idea_id)
    pipe.run(FakeRenderer())
    assert "ne doit pas être montré en vidéo (adresse e-mail visible)" in pipe.content(idea_id)["error"]


def test_render_failure_retries_then_fails(pipe):
    idea_id = hook_demo(pipe)
    pipe.produce(idea_id)
    pipe.run(FakeRenderer(fail="Chrome a planté"), max_steps=2)       # produce, puis 1er essai du rendu
    c = pipe.content(idea_id)
    assert c["status"] == "rendering" and "essai 1/2 raté" in c["error"] and "Chrome a planté" in c["error"]
    pipe.run(FakeRenderer(fail="Chrome a planté"))
    c = pipe.content(idea_id)
    assert c["status"] == "failed" and "abandon après 2 essais" in c["error"]
    assert pipe.jobs("content.render")[0]["status"] == "dead"
    assert pipe.idea_row(idea_id)["status"] == "failed"


def test_one_render_at_a_time(pipe):
    idea_id = hook_demo(pipe)
    pipe.produce(idea_id)
    with renderer.exclusive(pipe.config.data_dir / "render.lock"):      # un autre rendu occupe la machine
        pipe.run(FakeRenderer(), max_steps=2)
        render = pipe.jobs("content.render")[0]
        assert render["status"] == "queued" and render["attempts"] == 0
        assert pipe.content(idea_id)["status"] == "draft"
    pipe.run(FakeRenderer())
    assert pipe.content(idea_id)["status"] == "rendered"


def test_qa_failure_is_reported_in_french(pipe):
    idea_id = hook_demo(pipe)
    pipe.produce(idea_id)
    pipe.run(FakeRenderer(seconds=3))
    c = pipe.content(idea_id)
    assert c["status"] == "qa_failed" and c["error"] == "Trop courte : 3,0 s, 6 s au minimum."
    assert pipe.idea_row(idea_id)["status"] == "failed"
    assert c["run"] == 0 and len(pipe.jobs("content.produce")) == 1          # défaut déterministe : pas de reprise


# --- Formats à plans --------------------------------------------------------------------------------------------

def shot_idea(pipe, fmt="ai-hook-demo", shots=None, **kw) -> str:
    today, stats = pipe.screenshot("today.png"), pipe.screenshot("stats.png")
    return pipe.idea(fmt, shots=shots or story_shots(today, stats), **kw)


def test_shot_format_waits_for_generations_then_composes(pipe, tmp_path):
    idea_id = shot_idea(pipe)
    produce_id = pipe.produce(idea_id)
    pipe.run(FakeRenderer(), max_steps=1)

    gens = pipe.jobs("video.generate")
    assert [g["key"] for g in gens] == [f"video.generate:{idea_id}:0"]
    payload = json.loads(gens[0]["payload"])
    request = payload["request"]
    assert payload["content_id"] == idea_id and payload["shot_index"] == 0
    assert request["aspect"] == "9:16" and request["duration_s"] == 3.0 and request["audio"] is False
    assert request["quality"] == "standard" and request["image_path"] is None
    assert request["prompt"].startswith("A young woman on her bed") and "No on-screen text" in request["prompt"]
    assert gens[0]["parent_id"] == produce_id and gens[0]["app_id"] == "habitudo"

    produce = pipe.conn.execute("SELECT * FROM jobs WHERE id=?", (produce_id,)).fetchone()
    assert produce["status"] == "queued" and produce["attempts"] == 0           # RetryLater : pas d'essai consommé
    assert json.loads(produce["result"])["run"] == 0
    c = pipe.content(idea_id)
    assert c["status"] == "draft" and c["ai_label"] == 1 and pipe.idea_row(idea_id)["status"] == "producing"

    pipe.run(FakeRenderer(), max_steps=3)                                       # toujours en attente
    assert pipe.content(idea_id)["status"] == "draft" and not pipe.jobs("content.compose")

    pipe.finish_generation(gens[0]["id"], make_video(tmp_path / "clip.mp4", 4), cost=0.35)
    fake = FakeRenderer()
    pipe.run(fake)
    c = pipe.content(idea_id)
    assert c["status"] == "rendered" and store.to_review(c), c["error"]
    assert c["cost_usd"] == pytest.approx(0.35)
    job = fake.calls[0]
    assert job.composition == "story"
    kinds = [s["kind"] for s in job.props["shots"]]
    assert kinds == ["clip", "screen", "screen", "end"]
    clip, _, second, end = job.props["shots"]
    assert clip["src"] == f"content/{idea_id}/clip-0.mp4" and clip["text"].startswith("POV")
    assert clip["duration"] == 3.0 and not clip.get("audio")
    assert second["subtitle"] == "Un geste le soir, c'est tout."
    assert end == {"kind": "end", "duration": 2.5, "text": "Lance ta série ce soir"}
    assert not (pipe.root / "render" / "public" / "content" / idea_id).exists()          # clips retirés après
    envelope = json.loads(c["props"])
    assert [t["kind"] for t in envelope["timeline"]] == ["ai_video", "app_screenshot", "app_screenshot", "end_card"]
    assert envelope["timeline"][1] == {"index": 1, "kind": "app_screenshot", "ai": False, "start": 3.0, "end": 6.0}


def test_dead_generation_fails_the_content(pipe):
    idea_id = shot_idea(pipe)
    pipe.produce(idea_id)
    pipe.run(FakeRenderer(), max_steps=1)
    gen = pipe.jobs("video.generate")[0]
    pipe.kill_generation(gen["id"], "Traceback…\nProviderError: contenu refusé par le modèle")
    pipe.run(FakeRenderer())
    c = pipe.content(idea_id)
    assert c["status"] == "failed"
    assert c["error"] == "génération du plan 1 abandonnée : ProviderError: contenu refusé par le modèle"
    assert pipe.idea_row(idea_id)["status"] == "failed" and not pipe.jobs("content.compose")


def test_generation_never_done_times_out(pipe):
    idea_id = shot_idea(pipe)
    pipe.produce(idea_id)
    pipe.run(FakeRenderer(), max_steps=1)
    pipe.advance(hours=25)
    pipe.run(FakeRenderer(), max_steps=1)
    c = pipe.content(idea_id)
    assert c["status"] == "failed" and "toujours pas terminées après 24 h" in c["error"]
    assert pipe.jobs("video.generate")[0]["status"] == "cancelled"


def test_ugc_clip_is_cut_to_the_speech(pipe, tmp_path):
    today = pipe.screenshot()
    shots = [Shot(kind="ugc_avatar", duration_s=5, visual="", asset_id=None, on_screen_text="",
                  prompt="Selfie video of a young woman in her kitchen, morning light, talking to the camera",
                  voiceover="J'ai enfin tenu mes habitudes trois semaines."),
             Shot(kind="app_screenshot", duration_s=3, visual="", prompt="", asset_id=today,
                  on_screen_text="3 habitudes", voiceover="")]
    idea_id = pipe.idea("ugc-ai", shots=shots, lang="fr", hook="J'ai enfin tenu mes habitudes")
    pipe.produce(idea_id)
    pipe.run(FakeRenderer(), max_steps=1)
    gen = pipe.jobs("video.generate")[0]
    request = json.loads(gen["payload"])["request"]
    assert request["audio"] is True and request["quality"] == "premium"
    assert 'says exactly: "J\'ai enfin tenu mes habitudes trois semaines."' in request["prompt"]
    pipe.finish_generation(gen["id"], make_video(tmp_path / "ugc.mp4", 6, audio="speech"), cost=1.2)
    fake = FakeRenderer(audio="tone")
    pipe.run(fake)
    clip = fake.calls[0].props["shots"][0]
    assert clip["audio"] is True and clip["trimBefore"] == pytest.approx(0.55, abs=0.15)
    assert clip["duration"] == pytest.approx(4.4, abs=0.2)
    assert "text" not in clip                         # la voix dit déjà l'accroche : pas de titre en double
    c = pipe.content(idea_id)
    assert c["status"] == "rendered", c["error"]
    assert json.loads(c["props"])["expect_audio"] is True and c["ai_label"] == 1


def test_transient_qa_failure_regenerates_the_ai_shot_once(pipe, tmp_path):
    idea_id = shot_idea(pipe)
    pipe.produce(idea_id)
    pipe.run(FakeRenderer(), max_steps=1)
    pipe.finish_generation(pipe.jobs("video.generate")[0]["id"], make_video(tmp_path / "c.mp4", 4))
    pipe.run(FakeRenderer(black=(0.5, 2.5)))           # le plan IA (0 à 3 s) sort noir

    c = pipe.content(idea_id)
    assert c["run"] == 1 and c["auto_retries"] == 1 and c["status"] == "draft"
    keys = [g["key"] for g in pipe.jobs("video.generate")]
    assert keys == [f"video.generate:{idea_id}:0", f"video.generate:{idea_id}:0:r1"]
    assert pipe.conn.execute("SELECT COUNT(*) FROM events WHERE kind='content.retry'").fetchone()[0] == 1
    assert pipe.idea_row(idea_id)["status"] == "producing"

    pipe.finish_generation(pipe.jobs("video.generate")[1]["id"], make_video(tmp_path / "c2.mp4", 4))
    pipe.run(FakeRenderer(black=(0.5, 2.5)))           # encore raté : plus de nouvelle tentative
    c = pipe.content(idea_id)
    assert c["status"] == "qa_failed" and c["run"] == 1 and "(plan IA 1)" in c["error"]
    assert pipe.idea_row(idea_id)["status"] == "failed"
    assert len(pipe.jobs("video.generate")) == 2


def test_stale_jobs_stop_after_a_relaunch(pipe):
    idea_id = hook_demo(pipe)
    pipe.produce(idea_id)
    pipe.run(FakeRenderer(), max_steps=1)                                     # produce seulement
    store.set_content(pipe.conn, idea_id, pipe.clock(), run=1)               # une relance est passée par là
    pipe.run(FakeRenderer())
    assert json.loads(pipe.jobs("content.render")[0]["result"]) == {"skipped": "production remplacée ou déjà rendue"}


def test_demo_recording_cuts_in_order(pipe):
    rec = pipe.recording(12)
    shots = [Shot(kind="text_card", duration_s=2, visual="", prompt="", asset_id=None,
                  on_screen_text="Ma routine en 10 s", voiceover=""),
             Shot(kind="app_recording", duration_s=4, visual="", prompt="", asset_id=rec, on_screen_text="J'ouvre",
                  voiceover=""),
             Shot(kind="app_recording", duration_s=4, visual="", prompt="", asset_id=rec, on_screen_text="Je coche",
                  voiceover=""),
             Shot(kind="app_recording", duration_s=3, visual="", prompt="", asset_id=rec, on_screen_text="Fini",
                  voiceover="")]
    idea_id = pipe.idea("demo-recording", shots=shots, props_json=json.dumps({"trims": {"3": 10.5}}))
    pipe.produce(idea_id)
    fake = FakeRenderer()
    pipe.run(fake)
    shots_out = fake.calls[0].props["shots"]
    assert [s["kind"] for s in shots_out] == ["card", "recording", "recording", "recording", "end"]
    assert "trimBefore" not in shots_out[1] and shots_out[2]["trimBefore"] == 4.0
    # 10,5 + 3 > 12 : passage avancé, en gardant 0,3 s de marge pour le fondu vers la carte de fin
    assert shots_out[3]["trimBefore"] == pytest.approx(8.7) and shots_out[3]["duration"] == 3
    assert any("passage avancé" in n for n in json.loads(pipe.content(idea_id)["props"])["notes"])
    assert pipe.content(idea_id)["status"] == "rendered"


def test_hashtags_are_normalized():
    assert _hashtags(["#Habitudes", "habitudes", "  #Mes Routines ", "", "#"]) == ["#Habitudes", "#MesRoutines"]


# --- Le vrai moteur (contrat de render.mjs) avec un script de substitution --------------------------------------

FAKE_SCRIPT = textwrap.dedent("""
    import json, sys, time
    manifest = json.load(open(sys.argv[-1]))
    print("[render] bundle…", file=sys.stderr)
    for job in manifest["jobs"]:
        if job["composition"] == "lent":
            time.sleep(30)
        if job["composition"] == "casse":
            print(json.dumps({"id": job["id"], "ok": False, "error": "composition introuvable"}))
            continue
        open(job["out"], "wb").write(b"video")
        print("ligne parasite")
        print(json.dumps({"id": job["id"], "ok": True, "files": [job["out"]]}), flush=True)
""")


def test_node_renderer_contract(tmp_path):
    script = tmp_path / "fake_render.py"
    script.write_text(FAKE_SCRIPT)
    engine = renderer.NodeRenderer([sys.executable, str(script)], tmp_path, timeout_s=10)
    results = engine.render([renderer.RenderJob("a", "story", {}, out=tmp_path / "a.mp4"),
                             renderer.RenderJob("b", "casse", {}, out=tmp_path / "b.mp4")])
    assert results["a"].ok and results["a"].files == [str(tmp_path / "a.mp4")]
    assert not results["b"].ok and results["b"].error == "composition introuvable"
    manifest_job = renderer.RenderJob("c", "slideshow", {}, out_dir=tmp_path / "c", stills=3).manifest()
    assert manifest_job == {"id": "c", "composition": "slideshow", "props": {}, "outDir": str(tmp_path / "c"),
                            "stills": 3}


def test_node_renderer_timeout_and_missing_result(tmp_path):
    script = tmp_path / "fake_render.py"
    script.write_text(FAKE_SCRIPT)
    slow = renderer.NodeRenderer([sys.executable, str(script)], tmp_path, timeout_s=1)
    result = slow.render([renderer.RenderJob("a", "lent", {}, out=tmp_path / "a.mp4")])["a"]
    assert not result.ok and "rendu interrompu après 1 s" in result.error
    crash = renderer.NodeRenderer([sys.executable, "-c", "import sys; print('boum', file=sys.stderr); sys.exit(3)"],
                                  tmp_path, timeout_s=10)
    result = crash.render([renderer.RenderJob("a", "story", {}, out=tmp_path / "a.mp4")])["a"]
    assert not result.ok and "aucun résultat du moteur (code 3) : boum" in result.error


def test_missing_node_is_a_clear_permanent_error(pipe, monkeypatch):
    monkeypatch.setattr("loopcast.production.options.node_bin", lambda settings: None)
    idea_id = hook_demo(pipe)
    pipe.produce(idea_id)
    pipe.run()                                       # pas de faux moteur : le vrai est demandé
    c = pipe.content(idea_id)
    assert c["status"] == "failed" and c["error"].startswith("Node introuvable")
    assert pipe.jobs("content.render")[0]["status"] == "dead"


def test_brand_falls_back_and_warns(pipe):
    pipe.conn.execute("UPDATE apps SET brand=? WHERE id='habitudo'", (json.dumps({"accent": "violet"}),))
    brand, notes = assets.brand(pipe.conn, pipe.config, "habitudo", "fr")
    assert brand == {"name": "Habitudo", "accent": assets.DEFAULT_ACCENT}
    assert notes == ["couleur de marque absente ou invalide : couleur par défaut"]
