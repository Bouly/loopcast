import base64
import json

import httpx
import pytest
from conftest import UDID1

from loopcast.farm.control import ControlError, PhoneController, capabilities, wda_failure_hint
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
    with pytest.raises(ControlError, match="pas encore ajouté à la ferme"):
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


def _fake_xcrun(tmp_path, report: str):
    """Un faux `xcrun` qui imprime `report` comme le ferait `xcresulttool get test-results summary`."""
    script = tmp_path / "xcrun"
    script.write_text(f"#!/bin/sh\ncat <<'EOF'\n{report}\nEOF\n")
    script.chmod(0o755)
    return str(script)


def test_a_wda_launch_failure_is_explained_from_xcodes_report(tmp_path):
    derived = tmp_path / "wda"
    (derived / "Logs" / "Test" / "Test-WebDriverAgentRunner.xcresult").mkdir(parents=True)
    report = ('{"devicesAndConfigurations": [], "testFailures": [{"failureText": "Failed to install or launch the '
              'test runner. (Underlying Error: The application could not be launched because the Developer App '
              'Certificate is not trusted.)"}]}')
    hint = wda_failure_hint(derived, since=0, xcrun=_fake_xcrun(tmp_path, report))
    assert hint.startswith("iOS ne fait pas encore confiance au certificat") and "VPN et gestion" in hint
    assert wda_failure_hint(derived, since=0, xcrun=_fake_xcrun(tmp_path, "{}")) is None     # cause inconnue
    assert wda_failure_hint(tmp_path / "rien", since=0) is None                                # aucun rapport


def test_start_says_why_wda_did_not_start(ctl, appium, config, monkeypatch):
    def refuse(request):
        if request.url.path == "/session":
            return httpx.Response(500, json={"value": {"error": "unknown error", "message":
                                  "Unable to launch WebDriverAgent. Original error: xcodebuild failed with code 65"}})
        return appium(request)

    ctl.http = httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://appium")
    monkeypatch.setattr("loopcast.farm.control.wda_failure_hint", lambda derived, since: "L'iPhone est verrouillé.")
    with pytest.raises(ControlError, match="L'iPhone est verrouillé"):
        ctl.start(UDID1)
