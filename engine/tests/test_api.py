import httpx
import pytest
from conftest import UDID1
from fastapi.testclient import TestClient
from test_control import FakeAppium

from loopcast.api.app import create_app
from loopcast.farm.control import PhoneController


@pytest.fixture
def api(config, conn, backend, tmp_path):
    appium = FakeAppium()
    ctl = PhoneController(config, conn, httpx.Client(transport=httpx.MockTransport(appium), base_url="http://appium"))
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Loopcast</title>")
    with TestClient(create_app(config, conn, backend, ctl, web_dist=dist)) as client:
        client.post("/api/farm/refresh")
        yield client


def test_phones_and_events(api):
    phones = {p["phone_id"]: p for p in api.get("/api/phones").json()}
    assert phones["phone-1"]["status"] == "ok"
    assert phones["phone-2"]["status"] == "never_seen"
    assert api.get("/api/events").json()[0]["kind"] == "phone_new"


def test_screenshot_is_cached_with_etag(api):
    r = api.get(f"/api/phones/{UDID1}/screenshot")
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    assert api.get(f"/api/phones/{UDID1}/screenshot", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    assert api.get("/api/phones").json()[0]["screen_etag"] == r.headers["etag"]


def test_control_flow(api):
    r = api.post(f"/api/phones/{UDID1}/session")
    assert r.json() == {"session_id": "s1", "size": {"width": 393, "height": 852}}
    assert api.post(f"/api/phones/{UDID1}/tap", json={"x": 10, "y": 20}).json() == {"ok": True}
    assert api.post(f"/api/phones/{UDID1}/launch", json={"app": "tiktok"}).status_code == 200
    assert api.post(f"/api/phones/{UDID1}/button", json={"name": "power"}).status_code == 409
    assert api.delete(f"/api/phones/{UDID1}/session").status_code == 200
    assert api.post(f"/api/phones/{UDID1}/tap", json={"x": 10, "y": 20}).status_code == 409


def test_unknown_phone_404(api):
    assert api.get("/api/phones/nope/screenshot").status_code == 404


def test_spa_fallback(api):
    assert "Loopcast" in api.get("/ferme/phone-1").text
    assert api.get("/api/nope").status_code == 404


def test_a_page_from_another_site_cannot_change_anything(config, conn, backend, clock):
    """CSRF : une page d'un autre site ouverte sur le Mac ne peut rien modifier (403 avant toute action).
    Passent : même origine, localhost sur le port du serveur, front de dev, api.allowed_origins, et les
    requêtes sans Origin (CLI, curl). Les lectures ne sont pas concernées."""
    from loopcast import jobs

    config.settings["api"] = {"allowed_origins": ["https://mac.tail1234.ts.net"]}
    job = jobs.enqueue(conn, "diffusion.tick", {}, clock=clock)
    conn.execute("UPDATE jobs SET status='dead' WHERE id=?", (job,))
    evil = {"Origin": "https://evil.example"}
    with TestClient(create_app(config, conn, backend, db_path=":memory:")) as client:
        for path in ("/api/content/c1/approve", "/api/content/c1/retry", f"/api/jobs/{job}/retry",
                     "/api/diffusion/accounts/phone-1:tiktok/resume", "/api/farm/refresh"):
            r = client.post(path, headers=evil)
            assert r.status_code == 403 and "evil.example" in r.json()["detail"], path
        assert conn.execute("SELECT status FROM jobs WHERE id=?", (job,)).fetchone()[0] == "dead"   # rien n'a bougé
        assert client.post("/api/farm/refresh", headers={"Origin": "null"}).status_code == 403
        assert client.delete(f"/api/phones/{UDID1}/session",
                             headers={"Origin": "http://localhost:9999"}).status_code == 403    # autre port local
        for origin in (None, "http://testserver", "http://localhost", "http://127.0.0.1:5173",
                       "https://mac.tail1234.ts.net"):
            assert client.post("/api/farm/refresh", headers={"Origin": origin} if origin else {}).status_code == 200
        assert client.get("/api/phones", headers=evil).status_code == 200
        assert client.post(f"/api/jobs/{job}/retry").status_code == 200                        # la CLI, curl…


def test_background_jobs_are_pushed_live(config, conn, backend, clock):
    """Une tâche de fond qui se termine prévient le front (écran Production + section concernée)."""
    from loopcast import jobs
    from loopcast.api.app import publish_job

    sent = []

    class Bus:
        def publish(self, kind, data):
            sent.append((kind, data["status"]))

    job = jobs.Job(id=7, kind="content.render", key=None, payload={}, attempts=1, max_attempts=3,
                   app_id="habitudo", parent_id=None)
    publish_job(Bus(), job, "done")
    assert sent == [("jobs", "done"), ("content", "done")]
    with TestClient(create_app(config, conn, backend, db_path=":memory:")):
        assert len(jobs.LISTENERS) == 1                    # branché pendant que le serveur tourne…
    assert jobs.LISTENERS == []                            # …et retiré à l'arrêt


def test_farm_status_and_farm_events_in_the_log(api, conn):
    """La page Ferme lit Appium, tunneld et la signature ; son journal montre aussi les alertes de la ferme."""
    status = api.get("/api/farm/status").json()
    assert status["appium"] == {"ok": True, "detail": "prêt (démo)"} and status["tunneld"]["ok"]
    assert status["signing"]["state"] == "ok" and status["problems"] == []
    for kind, message in (("problem_appium_down", "Appium ne répond pas"), ("ideas.generated", "pas pour la ferme")):
        conn.execute("INSERT INTO events(at, kind, message) VALUES (?,?,?)",
                     ("2026-10-29T17:00:00+00:00", kind, message))
    kinds = [e["kind"] for e in api.get("/api/events").json()]
    assert "problem_appium_down" in kinds and "ideas.generated" not in kinds
