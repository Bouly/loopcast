import base64
import json

import httpx
import pytest
from conftest import UDID1

from loopcast.farm.control import ControlError, PhoneController, capabilities
from loopcast.farm.supervisor import Supervisor


class FakeAppium:
    """Faux serveur Appium : enregistre les requêtes, répond comme le protocole W3C."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.sessions: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))
        if request.method == "POST" and path == "/session":
            self.sessions.add("s1")
            return httpx.Response(200, json={"value": {"sessionId": "s1", "capabilities": {}}})
        parts = path.split("/")
        if len(parts) > 2 and parts[2] not in self.sessions:
            return httpx.Response(404, json={"value": {"error": "invalid session id", "message": "Session does not exist"}})
        if path.endswith("/window/rect"):
            return httpx.Response(200, json={"value": {"x": 0, "y": 0, "width": 393, "height": 852}})
        if path.endswith("/screenshot"):
            return httpx.Response(200, json={"value": base64.b64encode(b"PNG").decode()})
        if path.endswith("/element/active"):
            return httpx.Response(200, json={"value": {"element-6066-11e4-a52e-4f735466cecf": "el1"}})
        if request.method == "DELETE" and len(parts) == 3:
            self.sessions.discard(parts[2])
        return httpx.Response(200, json={"value": None})


@pytest.fixture
def appium():
    return FakeAppium()


@pytest.fixture
def ctl(config, conn, backend, clock, appium):
    Supervisor(config, conn, backend, clock).tick()
    client = httpx.Client(transport=httpx.MockTransport(appium), base_url="http://appium")
    return PhoneController(config, conn, client)


def test_capabilities_are_unique_per_phone(config):
    c1, c2 = (capabilities(config, p) for p in config.phones[:2])
    for key in ("appium:udid", "appium:wdaLocalPort", "appium:mjpegServerPort", "appium:derivedDataPath"):
        assert c1[key] != c2[key]
    assert c1["appium:xcodeOrgId"] == "TEAM123" and c1["appium:allowProvisioningDeviceRegistration"] is True


def test_start_reuses_live_session(ctl, appium):
    assert ctl.start(UDID1) == "s1"
    assert ctl.start(UDID1) == "s1"
    assert sum(1 for m, p, _ in appium.calls if (m, p) == ("POST", "/session")) == 1


def test_start_disables_idle_waiting(ctl, appium):
    ctl.start(UDID1)
    settings = next(b for m, p, b in appium.calls if p.endswith("/appium/settings"))["settings"]
    assert settings["waitForIdleTimeout"] == 0 and settings["animationCoolOffTimeout"] == 0


def test_start_recreates_dead_session(ctl, appium):
    ctl.start(UDID1)
    appium.sessions.clear()                 # Appium redémarré : la session n'existe plus
    ctl.start(UDID1)
    assert sum(1 for m, p, _ in appium.calls if (m, p) == ("POST", "/session")) == 2


def test_gestures(ctl, appium):
    ctl.start(UDID1)
    ctl.tap(UDID1, 100.4, 200.6)
    move = next(b for m, p, b in appium.calls if p.endswith("/actions") and m == "POST")
    assert move["actions"][0]["actions"][0] == {"type": "pointerMove", "duration": 0, "x": 100, "y": 201}
    ctl.type_text(UDID1, "bonjour")
    assert ("POST", "/session/s1/element/el1/value", {"text": "bonjour"}) in appium.calls
    ctl.launch_app(UDID1, "com.zhiliaoapp.musically")
    assert appium.calls[-1][2] == {"script": "mobile: launchApp", "args": [{"bundleId": "com.zhiliaoapp.musically"}]}
    assert ctl.screenshot(UDID1) == b"PNG"


def test_errors(ctl, config):
    with pytest.raises(ControlError, match="pas de session"):
        ctl.tap(UDID1, 1, 1)
    with pytest.raises(ControlError, match="inconnu"):
        ctl.start("00008110-STRANGER")
    ctl.start(UDID1)
    with pytest.raises(ControlError, match="bouton inconnu"):
        ctl.press_button(UDID1, "power")


def test_stop_clears_session(ctl, conn):
    ctl.start(UDID1)
    ctl.stop(UDID1)
    assert ctl.session_id(UDID1) is None


def test_appium_down(config, conn, backend, clock):
    Supervisor(config, conn, backend, clock).tick()

    def refuse(_request):
        raise httpx.ConnectError("refusé")

    ctl = PhoneController(config, conn, httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://appium"))
    with pytest.raises(ControlError, match="Appium injoignable"):
        ctl.start(UDID1)


def test_dead_session_is_forgotten(ctl, appium):
    ctl.start(UDID1)
    appium.sessions.clear()                 # WebDriverAgent relancé sur l'iPhone
    with pytest.raises(ControlError, match="session perdue"):
        ctl.tap(UDID1, 1, 1)
    assert ctl.session_id(UDID1) is None    # l'UI repropose « Prendre la main »
