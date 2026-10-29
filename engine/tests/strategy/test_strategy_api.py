"""Routes /api/strategy : stratégie (versions, édition, approbation, relance), stock, idées."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from loopcast import db, modules
from loopcast.strategy import store
from loopcast.strategy.api import router

from .helpers import APP, make_idea, make_strategy, seed_app


class Bus:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))


@pytest.fixture
def env(tmp_path, sconfig, clock):
    path = tmp_path / "api.db"
    conn = db.connect(path)
    seed_app(conn, clock())
    app = FastAPI()
    app.state.config = sconfig
    app.state.conn = conn
    app.state.db_path = str(path)
    app.state.services = {}
    app.state.clock = clock
    app.state.bus = Bus()
    app.include_router(router)
    with TestClient(app) as client:
        yield client, conn, app.state.bus


def _draft(conn, clock, **over):
    with store.transaction(conn):
        return store.insert_strategy(conn, app_id=APP, brief_id=1, strategy=make_strategy(**over), model="m",
                                     now=clock())


def _jobs(conn, kind):
    return [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE kind=? ORDER BY id", (kind,))]


def test_router_is_plugged_into_the_api():
    assert any(getattr(r, "prefix", "") == "/api/strategy" for r in modules.routers())


def test_formats_catalog(env):
    client, _conn, _bus = env
    ids = [f["id"] for f in client.get("/api/strategy/formats").json()]
    assert {"hook-demo", "notes-app", "chat-story", "slideshow"} <= set(ids)


def test_current_strategy_draft_and_versions(env, clock):
    client, conn, _bus = env
    assert client.get("/api/strategy/apps/nope").status_code == 404
    empty = client.get(f"/api/strategy/apps/{APP}").json()
    assert empty["current"] is None and empty["draft"] is None and empty["versions"] == []

    _draft(conn, clock)
    body = client.get(f"/api/strategy/apps/{APP}").json()
    assert body["app"]["status"] == "brief_ready" and body["draft"]["version"] == 1
    assert body["draft"]["strategy"]["voices"][0]["phone_id"] == "phone-1"
    assert [v["version"] for v in client.get(f"/api/strategy/apps/{APP}/versions").json()] == [1]
    assert client.get(f"/api/strategy/apps/{APP}/versions/1").json()["status"] == "draft"
    assert client.get(f"/api/strategy/apps/{APP}/versions/7").status_code == 404


def test_edit_is_validated(env, clock):
    client, conn, bus = env
    _draft(conn, clock)
    edited = make_strategy(positioning="Repositionné à la main").model_dump()
    r = client.put(f"/api/strategy/apps/{APP}/versions/1", json=edited)
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["note"] == "édition manuelle"
    assert store.strategy_by_version(conn, APP, 1).strategy.positioning == "Repositionné à la main"
    assert ("strategy", {"app_id": APP, "version": 1, "action": "edited"}) in bus.events

    missing = make_strategy(phones=(("phone-1", "fr"),)).model_dump()
    r = client.put(f"/api/strategy/apps/{APP}/versions/1", json=missing)
    assert r.status_code == 422 and any("phone-2" in e for e in r.json()["detail"]["errors"])
    broken = dict(edited)
    del broken["voices"]
    assert client.put(f"/api/strategy/apps/{APP}/versions/1", json=broken).status_code == 422


def test_approve_then_edit_makes_a_new_draft(env, clock):
    client, conn, bus = env
    _draft(conn, clock)
    r = client.post(f"/api/strategy/apps/{APP}/versions/1/approve")
    assert r.status_code == 200 and r.json()["version"] == 1
    assert store.get_app(conn, APP)["status"] == "active"
    assert _jobs(conn, "ideas.ensure_stock")[0]["priority"] == 1
    assert ("strategy", {"app_id": APP, "version": 1, "action": "approved"}) in bus.events

    r = client.put(f"/api/strategy/apps/{APP}/versions/1", json=make_strategy(positioning="v2").model_dump())
    assert r.json()["version"] == 2 and r.json()["status"] == "draft"
    body = client.get(f"/api/strategy/apps/{APP}").json()
    assert body["current"]["version"] == 1 and body["draft"]["version"] == 2

    client.post(f"/api/strategy/apps/{APP}/versions/2/approve")
    assert client.post(f"/api/strategy/apps/{APP}/versions/1/approve").status_code == 409   # archivée


def test_module_events(env, clock):
    client, conn, _bus = env
    store.add_event(conn, clock(), "ideas.abandoned", f"{APP} · phone-1 : idée abandonnée « x » : hook vide")
    store.add_event(conn, clock(), "strategy.approved", "autre-app : stratégie v1 approuvée")
    store.add_event(conn, clock(), "phone_new", "iPhone branché")
    assert [e["kind"] for e in client.get("/api/strategy/events").json()] == ["strategy.approved", "ideas.abandoned"]
    assert [e["kind"] for e in client.get("/api/strategy/events", params={"app_id": APP}).json()] == ["ideas.abandoned"]


def test_regenerate_enqueues_a_new_version(env, clock):
    client, conn, _bus = env
    r = client.post(f"/api/strategy/apps/{APP}/regenerate", json={"note": "Plus d'humour"})
    job = _jobs(conn, "strategy.generate")[0]
    assert r.json() == {"job_id": job["id"]}
    assert json.loads(job["payload"]) == {"app_id": APP, "brief_id": 1, "note": "Plus d'humour"}
    assert client.get(f"/api/strategy/apps/{APP}").json()["pending_jobs"][0]["id"] == job["id"]
    assert client.post(f"/api/strategy/apps/{APP}/regenerate").json() == {"job_id": job["id"]}   # double clic
    conn.execute("UPDATE app_briefs SET approved_at=NULL")
    clock.advance(minutes=5)
    assert client.post(f"/api/strategy/apps/{APP}/regenerate").status_code == 409


def test_stock_and_generation_for_a_phone(env, clock):
    client, conn, _bus = env
    stock = client.get(f"/api/strategy/apps/{APP}/stock").json()
    assert stock["target"] == 6 and [p["phone_id"] for p in stock["phones"]] == ["phone-1", "phone-2", "phone-3"]
    assert stock["phones"][0]["accounts"] == ["phone-1:tiktok", "phone-1:instagram"]
    assert client.post(f"/api/strategy/apps/{APP}/stock").json()["job_id"] == _jobs(conn, "ideas.ensure_stock")[0]["id"]

    assert client.post(f"/api/strategy/apps/{APP}/phones/phone-1/generate").status_code == 409   # pas de stratégie
    store.approve_strategy(conn, _draft(conn, clock).id, clock())
    assert client.post(f"/api/strategy/apps/{APP}/phones/phone-4/generate").status_code == 404
    r = client.post(f"/api/strategy/apps/{APP}/phones/phone-2/generate", json={"count": 3})
    job = _jobs(conn, "ideas.generate")[0]
    assert r.json() == {"job_id": job["id"], "count": 3}
    assert json.loads(job["payload"]) == {"app_id": APP, "phone_id": "phone-2", "count": 3}
    assert client.post(f"/api/strategy/apps/{APP}/phones/phone-2/generate", json={"count": 40}).status_code == 422


def test_ideas_list_detail_approve_reject(env, clock):
    client, conn, bus = env
    rec = _draft(conn, clock)
    phone1, phone2 = (type("P", (), {"id": p, "accounts": {"tiktok": {}}})() for p in ("phone-1", "phone-2"))
    with store.transaction(conn):
        a, b = store.insert_ideas(conn, app_id=APP, strategy_id=rec.id, phone=phone1, status="proposed", now=clock(),
                                  job_id=None, ideas=[make_idea(), make_idea("Ta to-do déborde ?", fmt="notes-app")])
        (c,) = store.insert_ideas(conn, app_id=APP, strategy_id=rec.id, phone=phone2, status="producing",
                                  now=clock(), job_id=None,
                                  ideas=[make_idea("Stop relying on motivation", lang="en", phone="phone-2")])

    listed = client.get("/api/strategy/ideas", params={"app_id": APP, "phone_id": "phone-1",
                                                       "status": "proposed"}).json()
    assert {i["id"] for i in listed} == {a, b} and listed[0]["idea"]["lang"] == "fr"
    assert [i["id"] for i in client.get("/api/strategy/ideas", params={"status": "producing,approved"}).json()] == [c]
    detail = client.get(f"/api/strategy/ideas/{a}").json()
    assert detail["hook"] == "Arrête de compter sur ta motivation" and detail["content"] == []
    assert client.get("/api/strategy/ideas/nope").status_code == 404

    assert client.post(f"/api/strategy/ideas/{a}/approve").json()["status"] == "approved"
    produce = _jobs(conn, "content.produce")[0]
    assert produce["key"] == f"content.produce:{a}" and ("strategy", {"idea_id": a, "status": "approved"}) in bus.events

    r = client.post(f"/api/strategy/ideas/{a}/reject", json={"note": "Trop proche d'une pub"})
    assert r.json()["status"] == "rejected"
    assert store.get_idea(conn, a)["review_note"] == "Trop proche d'une pub"
    assert _jobs(conn, "content.produce")[0]["status"] == "cancelled"        # la production n'avait pas commencé
    assert client.post(f"/api/strategy/ideas/{a}/approve").json()["job_id"] == produce["id"]   # on se ravise
    assert _jobs(conn, "content.produce")[0]["status"] == "queued"
    assert client.post(f"/api/strategy/ideas/{b}/reject").json()["status"] == "rejected"
    assert client.post(f"/api/strategy/ideas/{c}/reject").status_code == 409       # déjà en production
    assert client.post(f"/api/strategy/ideas/{c}/approve").status_code == 409
    assert client.post("/api/strategy/ideas/nope/approve").status_code == 404


def test_ideas_list_leads_to_the_video_and_its_posts(env, clock):
    """Une idée produite mène à sa vidéo (à valider ou décidée) puis à son post du calendrier."""
    client, conn, _bus = env
    rec = _draft(conn, clock)
    phone1 = type("P", (), {"id": "phone-1", "accounts": {"tiktok": {}}})()
    with store.transaction(conn):
        review, kept, waiting = store.insert_ideas(
            conn, app_id=APP, strategy_id=rec.id, phone=phone1, status="produced", now=clock(), job_id=None,
            ideas=[make_idea(), make_idea("Ta to-do déborde ?", fmt="notes-app"), make_idea("Trois habitudes")])
    for content_id, status in ((review, "rendered"), (kept, "approved")):
        conn.execute("INSERT INTO content(id, app_id, idea_id, format, lang, status, qa, created_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (content_id, APP, content_id, "hook-demo", "fr", status,
                                                  json.dumps({"ok": True}), "2026-10-29T08:00:00+00:00"))
    conn.execute("""INSERT INTO posts(content_id, account_id, platform, status, scheduled_at) VALUES
                    (?, 'phone-1:tiktok', 'tiktok', 'scheduled', '2026-10-30T11:00:00+00:00'),
                    (?, 'phone-1:instagram', 'instagram', 'skipped', '2026-10-30T12:00:00+00:00')""", (kept, kept))

    videos = {i["id"]: i["video"] for i in client.get("/api/strategy/ideas", params={"app_id": APP}).json()}
    assert videos[review]["to_review"] is True and videos[review]["posts"] == []
    assert videos[kept]["status"] == "approved" and videos[kept]["to_review"] is False
    assert [(p["account_id"], p["status"]) for p in videos[kept]["posts"]] == [("phone-1:tiktok", "scheduled")]
    assert videos[waiting] is None
