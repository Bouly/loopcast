"""Pilotage d'un iPhone via Appium (driver XCUITest, WebDriverAgent sur le téléphone).

On parle directement le protocole W3C WebDriver en HTTP (httpx) : pas de dépendance au client
Appium, et les tests passent par un faux serveur. Un seul serveur Appium sur le Mac suffit pour
tous les iPhones ; chaque téléphone a ses propres ports WDA et MJPEG (attribués par `slot`).

Prérequis sur le Mac (voir docs/ferme-iphone.md) : Xcode, Appium 3 + `appium driver install xcuitest`,
un compte Apple Developer pour signer WebDriverAgent, iPhones en mode développeur.
"""

from __future__ import annotations

import base64
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import httpx

from loopcast.config import Config, PhoneConfig


class ControlError(RuntimeError):
    pass


@dataclass
class Ports:
    wda: int
    mjpeg: int


def ports_for(config: Config, phone: PhoneConfig) -> Ports:
    return Ports(wda=config.farm.wda_base_port + phone.slot, mjpeg=config.farm.mjpeg_base_port + phone.slot)


def capabilities(config: Config, phone: PhoneConfig) -> dict:
    ports = ports_for(config, phone)
    caps = {
        "platformName": "iOS",
        "appium:automationName": "XCUITest",
        "appium:udid": phone.udid,
        "appium:wdaLocalPort": ports.wda,
        "appium:mjpegServerPort": ports.mjpeg,
        # Un dossier de build WDA par iPhone, sinon les sessions parallèles se marchent dessus
        "appium:derivedDataPath": str(config.data_dir / "wda" / phone.udid),
        "appium:noReset": True,
        "appium:newCommandTimeout": 900,
        "appium:wdaLaunchTimeout": 120000,
    }
    if config.farm.xcode_org_id:
        caps["appium:xcodeOrgId"] = config.farm.xcode_org_id
        caps["appium:xcodeSigningId"] = "Apple Development"
        # Laisse Xcode créer le profil de provisionnement et enregistrer l'iPhone sur le compte
        # (sinon : « No profiles for '….xctrunner' were found », xcodebuild code 65).
        caps["appium:allowProvisioningDeviceRegistration"] = True
    if config.farm.wda_bundle_id:
        caps["appium:updatedWDABundleId"] = config.farm.wda_bundle_id
    return caps


class PhoneController:
    """Une session Appium par iPhone, mémorisée dans phones.session_id."""

    def __init__(self, config: Config, conn: sqlite3.Connection, client: httpx.Client | None = None):
        self.config = config
        self.conn = conn
        self.http = client or httpx.Client(base_url=config.farm.appium_url, timeout=180)

    # --- sessions ---------------------------------------------------------------------------

    def _phone(self, udid: str) -> PhoneConfig:
        phone = self.config.phone_by_udid(udid)
        if phone is None:
            raise ControlError("iPhone inconnu : l'ajouter dans config/devices.yaml avant de le piloter")
        return phone

    def session_id(self, udid: str) -> str | None:
        row = self.conn.execute("SELECT session_id FROM phones WHERE udid=?", (udid,)).fetchone()
        return row["session_id"] if row else None

    def _set_session(self, udid: str, session_id: str | None) -> None:
        self.conn.execute("UPDATE phones SET session_id=? WHERE udid=?", (session_id, udid))

    def start(self, udid: str) -> str:
        """Ouvre (ou réutilise) la session : le premier lancement compile et installe WDA (1-3 min)."""
        existing = self.session_id(udid)
        if existing and self._alive(existing):
            return existing
        phone = self._phone(udid)
        Path(self.config.data_dir / "wda" / udid).mkdir(parents=True, exist_ok=True)
        body = {"capabilities": {"alwaysMatch": capabilities(self.config, phone), "firstMatch": [{}]}}
        value = self._call("POST", "/session", body)
        session_id = value.get("sessionId")
        if not session_id:
            raise ControlError(f"réponse Appium inattendue : {value}")
        self._set_session(udid, session_id)
        # Flux d'écran léger pour le dashboard : 10 i/s, demi-résolution
        self._call("POST", f"/session/{session_id}/appium/settings",
                   {"settings": {"mjpegServerFramerate": 10, "mjpegScalingFactor": 50}})
        return session_id

    def stop(self, udid: str) -> None:
        sid = self.session_id(udid)
        if sid:
            try:
                self._call("DELETE", f"/session/{sid}")
            except ControlError:
                pass
        self._set_session(udid, None)

    def _alive(self, sid: str) -> bool:
        try:
            self._call("GET", f"/session/{sid}/window/rect")
            return True
        except ControlError:
            return False

    def _sid(self, udid: str) -> str:
        sid = self.session_id(udid)
        if not sid:
            raise ControlError("pas de session ouverte : lancer « Prendre la main » d'abord")
        return sid

    # --- HTTP -------------------------------------------------------------------------------

    def _call(self, method: str, path: str, body: dict | None = None):
        try:
            resp = self.http.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise ControlError(f"Appium injoignable ({self.config.farm.appium_url}) : {e}") from e
        try:
            data = resp.json()
        except ValueError:
            raise ControlError(f"Appium {resp.status_code} : {resp.text[:300]}")
        value = data.get("value") if isinstance(data, dict) else None
        if resp.status_code >= 400:
            message = value.get("message") if isinstance(value, dict) else resp.text
            if isinstance(value, dict) and value.get("error") == "invalid session id" and path.startswith("/session/"):
                # Session morte (Appium ou WebDriverAgent relancé) : on l'oublie pour que l'UI repropose la prise en main
                self.conn.execute("UPDATE phones SET session_id=NULL WHERE session_id=?", (path.split("/")[2],))
                raise ControlError("session perdue : reprendre la main")
            raise ControlError(f"Appium {resp.status_code} : {str(message)[:300]}")
        return value

    def _execute(self, udid: str, script: str, args: dict | None = None):
        return self._call("POST", f"/session/{self._sid(udid)}/execute/sync",
                          {"script": script, "args": [args or {}]})

    # --- gestes (coordonnées en points iOS, comme window/rect) -------------------------------

    def window_size(self, udid: str) -> dict:
        rect = self._call("GET", f"/session/{self._sid(udid)}/window/rect")
        return {"width": rect["width"], "height": rect["height"]}

    def _pointer(self, udid: str, steps: list[dict]) -> None:
        sid = self._sid(udid)
        actions = [{"type": "pointer", "id": "finger1", "parameters": {"pointerType": "touch"}, "actions": steps}]
        self._call("POST", f"/session/{sid}/actions", {"actions": actions})
        self._call("DELETE", f"/session/{sid}/actions")

    def tap(self, udid: str, x: float, y: float) -> None:
        self._pointer(udid, [
            {"type": "pointerMove", "duration": 0, "x": round(x), "y": round(y)},
            {"type": "pointerDown", "button": 0},
            {"type": "pause", "duration": 80},
            {"type": "pointerUp", "button": 0},
        ])

    def swipe(self, udid: str, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None:
        self._pointer(udid, [
            {"type": "pointerMove", "duration": 0, "x": round(x1), "y": round(y1)},
            {"type": "pointerDown", "button": 0},
            {"type": "pointerMove", "duration": duration_ms, "x": round(x2), "y": round(y2)},
            {"type": "pointerUp", "button": 0},
        ])

    def type_text(self, udid: str, text: str) -> None:
        """Tape dans le champ qui a le focus (le clavier doit être ouvert)."""
        sid = self._sid(udid)
        el = self._call("GET", f"/session/{sid}/element/active")
        el_id = next(iter(el.values())) if isinstance(el, dict) and el else None
        if not el_id:
            raise ControlError("aucun champ actif : taper d'abord sur le champ de texte")
        self._call("POST", f"/session/{sid}/element/{el_id}/value", {"text": text})

    def press_button(self, udid: str, name: str) -> None:
        if name not in {"home", "volumeup", "volumedown"}:
            raise ControlError(f"bouton inconnu : {name}")
        self._execute(udid, "mobile: pressButton", {"name": name})

    def launch_app(self, udid: str, bundle_id: str) -> None:
        self._execute(udid, "mobile: launchApp", {"bundleId": bundle_id})

    def terminate_app(self, udid: str, bundle_id: str) -> None:
        self._execute(udid, "mobile: terminateApp", {"bundleId": bundle_id})

    # --- lecture ----------------------------------------------------------------------------

    def screenshot(self, udid: str) -> bytes:
        return base64.b64decode(self._call("GET", f"/session/{self._sid(udid)}/screenshot"))

    def source(self, udid: str) -> str:
        """Arbre XML de l'écran : base des scénarios (trouver un bouton par son libellé)."""
        return self._call("GET", f"/session/{self._sid(udid)}/source")

    def stream_url(self, udid: str) -> str:
        """Flux MJPEG de WebDriverAgent, redirigé par Appium sur le Mac (port propre à chaque iPhone)."""
        host = httpx.URL(self.config.farm.appium_url).host
        return f"http://{host}:{ports_for(self.config, self._phone(udid)).mjpeg}"


# Apps utiles au pilotage depuis le dashboard
BUNDLES = {
    "tiktok": "com.zhiliaoapp.musically",
    "instagram": "com.burbn.instagram",
    "photos": "com.apple.mobileslideshow",
    "settings": "com.apple.Preferences",
}
