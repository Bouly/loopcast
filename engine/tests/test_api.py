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
