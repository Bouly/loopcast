"""File de validation /api/content : liste, détail, décisions, médias avec Range."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from loopcast.api.app import create_app
from loopcast.farm.backend import FakeBackend
from loopcast.jobs import iso
from loopcast.production import review, store

from .conftest import FakeRenderer, make_png, make_video, needs_ffmpeg, story_shots

pytestmark = needs_ffmpeg


@pytest.fixture
def api(pipe):
    app = create_app(pipe.config, pipe.conn, FakeBackend(), services={}, db_path=pipe.config.db_path)
    app.state.clock = pipe.clock
    with TestClient(app) as client:
        yield client


def produced(pipe, fmt="hook-demo") -> str:
    """Un contenu passé par tout le pipeline (faux rendu, vrai contrôle qualité) : à valider."""
    props = {"hook": "Arrête de compter sur ta **motivation**",
             "screens": [{"caption": "Choisis 3 habitudes", "asset_id": pipe.screenshot()},
                         {"caption": "Coche-les", "mock": {"kind": "stat", "title": "Série", "value": "21", "label": "j"}}]}
    idea_id = pipe.idea(fmt, props=props)
    pipe.produce(idea_id)
    pipe.run(FakeRenderer())
    assert store.to_review(pipe.content(idea_id))
    return idea_id


def add_content(pipe, content_id: str, status: str, *, qa_ok: bool | None = None, account="phone-1:tiktok",
                minutes: int = 0) -> str:
    idea_id = pipe.idea("notes-app", props={"title": "t", "items": ["a", "b", "c"]}, idea_id=content_id)
    at = iso(pipe.clock() + timedelta(minutes=minutes))
    pipe.conn.execute(
        """INSERT INTO content(id, app_id, idea_id, account_id, format, lang, kind, status, qa, caption, hashtags,
                               files, run, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (content_id, "habitudo", idea_id, account, "notes-app", "fr", "video", status,
         json.dumps({"ok": qa_ok}) if qa_ok is not None else None, "légende", "[]", "[]", 0, at, at))
    return content_id


def test_list_puts_review_first_and_filters(api, pipe):
    add_content(pipe, "c-approved", "approved", qa_ok=True, minutes=1)
    add_content(pipe, "c-failed", "failed", minutes=2)
    add_content(pipe, "c-review-late", "rendered", qa_ok=True, minutes=5)
    add_content(pipe, "c-review-early", "rendered", qa_ok=True, minutes=3)
    add_content(pipe, "c-checking", "rendered", minutes=4)              # contrôle qualité pas encore passé
    add_content(pipe, "c-other", "rendered", qa_ok=True, account="phone-2:tiktok", minutes=6)
    ids = [c["id"] for c in api.get("/api/content").json()]
    assert ids[:3] == ["c-review-early", "c-review-late", "c-other"]
    assert ids.index("c-checking") > 2 and ids[-1] == "c-approved"
    review_ids = [c["id"] for c in api.get("/api/content?status=review").json()]
    assert review_ids == ["c-review-early", "c-review-late", "c-other"]
    assert [c["id"] for c in api.get("/api/content?status=review&account_id=phone-2:tiktok").json()] == ["c-other"]
    assert [c["id"] for c in api.get("/api/content?status=failed").json()] == ["c-failed"]
    assert api.get("/api/content?app_id=autre").json() == []
    first = api.get("/api/content?limit=1").json()[0]
    assert first["to_review"] and first["qa_ok"] and "props" not in first
    stats = api.get("/api/content/stats").json()
    assert stats["review"] == 3 and stats["by_status"]["rendered"] == 4


def test_detail(api, pipe):
    content_id = produced(pipe)
    d = api.get(f"/api/content/{content_id}").json()
    assert d["status"] == "rendered" and d["qa"]["ok"] and d["composition"] == "hook-demo"
    assert d["idea"]["hook"] == "Arrête de compter sur ta motivation" and d["idea"]["status"] == "produced"
    assert d["media"] == [f"/api/content/{content_id}/media/0"] and d["poster"] == f"/api/content/{content_id}/poster"
    assert {j["kind"] for j in d["jobs"]} == {"content.produce", "content.render", "content.qa"}
    assert any(e["kind"] == "content.ready" for e in d["events"])
    assert api.get("/api/content/inconnu").status_code == 404


def test_list_and_detail_name_the_video_by_its_hook_and_say_where_it_goes(api, pipe):
    """Un seul titre partout (l'accroche de l'idée), et de la vidéo on remonte à son post du calendrier."""
    add_content(pipe, "c-review", "rendered", qa_ok=True)
    pipe.conn.execute("UPDATE ideas SET hook='Ta routine du soir en 3 minutes' WHERE id='c-review'")
    pipe.conn.execute("INSERT INTO content(id, app_id, format, lang, status) VALUES ('sans-idee', 'habitudo', "
                      "'notes-app', 'fr', 'approved')")
    by_id = {c["id"]: c for c in api.get("/api/content").json()}
    assert by_id["c-review"]["hook"] == "Ta routine du soir en 3 minutes" and by_id["sans-idee"]["hook"] is None
    assert api.get("/api/content?status=review").json()[0]["hook"] == "Ta routine du soir en 3 minutes"

    add_content(pipe, "c-kept", "approved", qa_ok=True)
    pipe.conn.execute("""INSERT INTO posts(content_id, account_id, platform, status, scheduled_at)
                         VALUES ('c-kept', 'phone-1:tiktok', 'tiktok', 'scheduled', '2026-10-30T11:00:00+00:00')""")
    d = api.get("/api/content/c-kept").json()
    assert d["hook"] == "Arrête de compter sur ta motivation"
    assert [(p["account_id"], p["status"]) for p in d["posts"]] == [("phone-1:tiktok", "scheduled")]
    assert api.post("/api/content/c-review/approve").json()["hook"] == "Ta routine du soir en 3 minutes"


def test_detail_shows_generations(api, pipe):
    idea_id = pipe.idea("ai-hook-demo", shots=story_shots(pipe.screenshot("a.png"), pipe.screenshot("b.png")))
    pipe.produce(idea_id)
    pipe.run(FakeRenderer(), max_steps=1)
    d = api.get(f"/api/content/{idea_id}").json()
    assert [s["kind"] for s in d["shots"]] == ["ai_video", "app_screenshot", "app_screenshot"]
    assert d["shots"][0]["generation"]["status"] == "queued" and d["shots"][1]["generation"] is None
    assert d["ai_label"] == 1


def test_approve_needs_a_passed_qa(api, pipe):
    add_content(pipe, "c-checking", "rendered")
    r = api.post("/api/content/c-checking/approve")
    assert r.status_code == 409 and "contrôle qualité pas encore réussi" in r.json()["detail"]
    add_content(pipe, "c-failed", "qa_failed", qa_ok=False)
    assert api.post("/api/content/c-failed/approve").status_code == 409
    content_id = produced(pipe)
    r = api.post(f"/api/content/{content_id}/approve", json={"note": "parfait"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    c = pipe.content(content_id)
    assert c["approved_at"] and c["review_note"] == "parfait"
    assert api.post(f"/api/content/{content_id}/approve").status_code == 200          # idempotent
    assert api.post("/api/content/absent/approve").status_code == 404


def test_reject_marks_the_idea_and_keeps_the_note(api, pipe):
    content_id = produced(pipe)
    r = api.post(f"/api/content/{content_id}/reject", json={"note": "accroche trop molle"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert pipe.idea_row(content_id)["status"] == "rejected"
    notes = review.rejection_notes(pipe.conn, "habitudo")
    assert notes[0]["note"] == "accroche trop molle" and notes[0]["hook"] == "Arrête de compter sur ta motivation"
    add_content(pipe, "c-draft", "draft")
    assert api.post("/api/content/c-draft/reject", json={"note": ""}).status_code == 409
    add_content(pipe, "c-posted", "approved", qa_ok=True)
    pipe.conn.execute("INSERT INTO posts(content_id, account_id, platform, status) VALUES (?,?,?,?)",
                      ("c-posted", "phone-1:tiktok", "tiktok", "scheduled"))
    r = api.post("/api/content/c-posted/reject", json={"note": "non"})
    assert r.status_code == 409 and "déjà planifié ou publié" in r.json()["detail"]


def test_edit_caption_and_hashtags(api, pipe):
    content_id = produced(pipe)
    r = api.patch(f"/api/content/{content_id}", json={"caption": " Nouvelle légende ", "hashtags": ["Routine", "#routine", "#Soir"]})
    assert r.status_code == 200
    assert r.json()["caption"] == "Nouvelle légende" and r.json()["hashtags"] == ["#Routine", "#Soir"]
    r = api.patch(f"/api/content/{content_id}", json={"hashtags": ["deux mots"]})
    assert r.status_code == 422 and "hashtag invalide" in r.json()["detail"]
    assert api.patch(f"/api/content/{content_id}", json={"caption": "x" * 2201}).status_code == 422
    assert pipe.content(content_id)["caption"] == "Nouvelle légende"


def test_retry_relaunches_a_failed_production(api, pipe):
    idea_id = pipe.idea("ai-hook-demo", shots=story_shots(pipe.screenshot("a.png"), pipe.screenshot("b.png")))
    pipe.produce(idea_id)
    pipe.run(FakeRenderer(), max_steps=1)
    r = api.post(f"/api/content/{idea_id}/retry")
    assert r.status_code == 409 and "production en cours" in r.json()["detail"]
    gen = pipe.jobs("video.generate")[0]
    pipe.kill_generation(gen["id"], "quota du fournisseur")
    pipe.run(FakeRenderer())
    assert pipe.content(idea_id)["status"] == "failed"

    r = api.post(f"/api/content/{idea_id}/retry")
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["run"] == 1
    job = pipe.conn.execute("SELECT * FROM jobs WHERE id=?", (r.json()["job_id"],)).fetchone()
    assert job["key"] == f"content.produce:{idea_id}:r1" and json.loads(job["payload"])["run"] == 1
    assert pipe.conn.execute("SELECT status FROM jobs WHERE id=?", (gen["id"],)).fetchone()[0] == "queued"
    assert pipe.idea_row(idea_id)["status"] == "producing"

    r = api.post(f"/api/content/{idea_id}/retry")                       # déjà relancée : en cours
    assert r.status_code == 409
    add_content(pipe, "c-approved", "approved", qa_ok=True)
    assert "déjà validé" in api.post("/api/content/c-approved/retry").json()["detail"]


def test_retry_with_regeneration_uses_new_keys(api, pipe, tmp_path):
    idea_id = pipe.idea("ai-hook-demo", shots=story_shots(pipe.screenshot("a.png"), pipe.screenshot("b.png")))
    pipe.produce(idea_id)
    pipe.run(FakeRenderer(), max_steps=1)
    pipe.finish_generation(pipe.jobs("video.generate")[0]["id"], make_video(tmp_path / "c.mp4", 4))
    pipe.run(FakeRenderer())
    api.post(f"/api/content/{idea_id}/reject", json={"note": "plan IA raté"})
    r = api.post(f"/api/content/{idea_id}/retry", json={"regenerate": True})
    assert r.status_code == 200
    pipe.run(FakeRenderer(), max_steps=1)
    assert [g["key"] for g in pipe.jobs("video.generate")] == [f"video.generate:{idea_id}:0",
                                                                f"video.generate:{idea_id}:0:r1"]


def test_media_supports_range_requests(api, pipe):
    content_id = produced(pipe)
    path = Path(json.loads(pipe.content(content_id)["files"])[0])
    data = path.read_bytes()
    full = api.get(f"/api/content/{content_id}/media/0")
    assert full.status_code == 200 and full.content == data
    assert full.headers["accept-ranges"] == "bytes" and full.headers["content-type"] == "video/mp4"
    part = api.get(f"/api/content/{content_id}/media/0", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == data[:100]
    assert part.headers["content-range"] == f"bytes 0-99/{len(data)}"
    tail = api.get(f"/api/content/{content_id}/media/0", headers={"Range": "bytes=-10"})
    assert tail.status_code == 206 and tail.content == data[-10:]
    assert api.get(f"/api/content/{content_id}/media/0", headers={"Range": f"bytes={len(data) + 5}-"}).status_code == 416
    assert api.get(f"/api/content/{content_id}/media/3").status_code == 404


def test_media_is_only_served_from_out(api, pipe, tmp_path):
    secret = make_png(tmp_path / "ailleurs.png")
    add_content(pipe, "c-evil", "rendered", qa_ok=True)
    store.set_content(pipe.conn, "c-evil", pipe.clock(), files=[str(secret)])
    assert api.get("/api/content/c-evil/media/0").status_code == 404
    store.set_content(pipe.conn, "c-evil", pipe.clock(), files=[str(pipe.root / "out" / ".." / "data" / "loopcast.db")])
    assert api.get("/api/content/c-evil/media/0").status_code == 404


def test_poster(api, pipe):
    content_id = produced(pipe)
    poster = store.content_dir(pipe.config, content_id) / "poster.jpg"
    poster.unlink()                                      # recréé à la demande
    r = api.get(f"/api/content/{content_id}/poster")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and poster.exists()
    add_content(pipe, "c-nothing", "draft")
    assert api.get("/api/content/c-nothing/poster").status_code == 404
