"""Santé de la ferme au-delà des iPhones : Appium, tunneld et la signature de WebDriverAgent.

Un iPhone peut être prêt et le pilotage impossible quand même :
- Appium arrêté : aucune prise en main ;
- tunneld arrêté : ni captures ni mode développeur sur iOS 17 et plus ;
- profil de signature de WebDriverAgent expiré : iOS refuse de lancer WebDriverAgent. Avec un compte Apple
  gratuit, Xcode crée un profil de 7 jours ; avec Apple Developer, d'un an.

La supervision appelle check() à chaque tour (supervisor.py), le diagnostic (`farm doctor`) aussi.
"""

from __future__ import annotations

import fnmatch
import logging
import plistlib
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Protocol
from zoneinfo import ZoneInfo

import httpx

from loopcast.config import Config

DEFAULT_WDA_BUNDLE = "com.facebook.WebDriverAgentRunner"      # celui d'Appium sans farm.wda_bundle_id
MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")

# Code → (gravité, ce qui ne va pas, comment le régler). Une famille (« appium », « tunneld », « signing ») n'a
# qu'un problème à la fois : une signature qui passe de « expire bientôt » à « expirée » s'aggrave.
FARM_PROBLEMS = {
    "appium_down": ("bad", "Appium ne répond pas : aucune prise en main possible",
                    "Relancer Appium : la commande appium dans un terminal, ou le service com.loopcast.appium."),
    "tunneld_down": ("bad", "tunneld ne répond pas : ni captures ni mode développeur sur iOS 17 et plus",
                     "Relancer tunneld : sudo pymobiledevice3 remote tunneld, ou le service com.loopcast.tunneld."),
    "signing_expiring": ("warn", "La signature de WebDriverAgent expire {when}",
                         "La refaire avant cette date : docs/ferme-iphone.md, « Refaire la signature »."),
    "signing_expired": ("bad", "La signature de WebDriverAgent a expiré {when} : le pilotage ne démarre plus",
                        "La refaire : docs/ferme-iphone.md, « Refaire la signature »."),
}
# Ce que /api/events montre de la ferme en plus des événements des iPhones.
FARM_EVENT_KINDS = tuple(f"{p}_{c}" for c in FARM_PROBLEMS for p in ("problem", "resolved"))


def family(code: str) -> str:
    return code.split("_", 1)[0]


@dataclass
class Service:
    ok: bool
    detail: str                         # « prêt (3.9.0) », « ne répond pas »


@dataclass
class Signing:
    state: str                          # ok | expiring | expired | missing | unconfigured
    expires_at: datetime | None = None
    app_id: str | None = None           # l'identifiant signé, sans le Team ID (….wda.xctrunner)


@dataclass
class FarmHealth:
    checked_at: datetime
    appium: Service
    tunneld: Service
    signing: Signing


class Checks(Protocol):
    def check(self, now: datetime) -> FarmHealth: ...


# --- Services ----------------------------------------------------------------------------------------------

def _json(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def check_appium(url: str, http: httpx.Client) -> Service:
    """GET /status : {"value": {"ready": true, "build": {"version": "3.9.0"}}} quand Appium est prêt."""
    try:
        r = http.get(f"{url.rstrip('/')}/status", timeout=3)
    except httpx.HTTPError:
        return Service(False, "ne répond pas")
    if r.status_code != 200:
        return Service(False, f"répond HTTP {r.status_code}")
    value = _json(r).get("value")
    value = value if isinstance(value, dict) else {}
    if value.get("ready") is False:
        return Service(False, "démarré mais pas prêt")
    build = value.get("build")
    version = build.get("version") if isinstance(build, dict) else None
    return Service(True, f"prêt ({version})" if version else "prêt")


def check_tunneld(url: str, http: httpx.Client) -> Service:
    """GET / : {UDID: [tunnels]}, une entrée par iPhone en tunnel (iOS 17 et plus)."""
    try:
        r = http.get(f"{url.rstrip('/')}/", timeout=3)
    except httpx.HTTPError:
        return Service(False, "ne répond pas")
    if r.status_code != 200:
        return Service(False, f"répond HTTP {r.status_code}")
    n = len(_json(r))
    return Service(True, f"actif, {n} iPhone{'s' if n > 1 else ''} en tunnel" if n else "actif, aucun iPhone en tunnel")


# --- Signature de WebDriverAgent ---------------------------------------------------------------------------

def profile_dirs() -> tuple[Path, ...]:
    """Xcode 16 et plus range les profils dans UserData ; les versions d'avant, dans MobileDevice."""
    home = Path.home()
    return (home / "Library" / "Developer" / "Xcode" / "UserData" / "Provisioning Profiles",
            home / "Library" / "MobileDevice" / "Provisioning Profiles")


def read_profile(path: Path) -> dict | None:
    """Le plist d'un .mobileprovision : il est en clair dans l'enveloppe CMS signée, sans passer par `security`."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    start = raw.find(b"<?xml")
    end = raw.find(b"</plist>", start)
    if start < 0 or end < 0:
        return None
    try:
        data = plistlib.loads(raw[start:end + len(b"</plist>")])
    except Exception:  # noqa: BLE001 : un profil abîmé est ignoré, les autres comptent
        return None
    return data if isinstance(data, dict) else None


_profiles_cache: dict[Path, tuple[int, dict | None]] = {}      # relu seulement quand le fichier change


def _profiles(dirs: Iterable[Path]) -> list[dict]:
    out = []
    for d in dirs:
        for f in sorted(d.glob("*.mobileprovision")):
            try:
                mtime = f.stat().st_mtime_ns
            except OSError:
                continue
            cached = _profiles_cache.get(f)
            if cached is None or cached[0] != mtime:
                cached = _profiles_cache[f] = (mtime, read_profile(f))
            if cached[1]:
                out.append(cached[1])
    return out


def wda_app_id(config: Config) -> str | None:
    """« TEAMID.<bundle>.xctrunner » : le lanceur de tests que Xcode signe pour Appium."""
    team = config.farm.xcode_org_id
    return f"{team}.{config.farm.wda_bundle_id or DEFAULT_WDA_BUNDLE}.xctrunner" if team else None


def signing_state(expires_at: datetime, now: datetime, warn_days: int) -> str:
    if expires_at <= now:
        return "expired"
    return "expiring" if expires_at - now <= timedelta(days=warn_days) else "ok"


def signing_status(config: Config, now: datetime, dirs: Iterable[Path] | None = None) -> Signing:
    """Le profil de WebDriverAgent qui expire le plus tard : Xcode garde aussi les anciens, déjà expirés."""
    target = wda_app_id(config)
    if target is None:
        return Signing("unconfigured")
    best: tuple[datetime, str] | None = None
    for p in _profiles(dirs if dirs is not None else profile_dirs()):
        entitlements = p.get("Entitlements")
        app_id = entitlements.get("application-identifier") if isinstance(entitlements, dict) else None
        expires = p.get("ExpirationDate")
        if not isinstance(app_id, str) or not isinstance(expires, datetime):
            continue
        if not fnmatch.fnmatchcase(target, app_id):         # identifiant exact ou joker (« TEAMID.* »)
            continue
        expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
        if best is None or expires > best[0]:
            best = (expires, app_id)
    if best is None:
        return Signing("missing")
    expires, app_id = best
    return Signing(signing_state(expires, now, config.farm.signing_warn_days), expires, app_id.split(".", 1)[-1])


# --- Vérifications ------------------------------------------------------------------------------------------

class _QuietChecks(logging.Filter):
    """Les vérifications passent toutes les 15 s : sans ce filtre, httpx écrit deux lignes à chaque tour dans le
    journal du serveur (plus de 11 000 par jour). Les autres requêtes restent journalisées."""

    def __init__(self, urls: tuple[str, ...]):
        super().__init__()
        self.urls = urls

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(url in message for url in self.urls)


class FarmChecks:
    """Les vraies vérifications, sur le Mac de la ferme."""

    def __init__(self, config: Config, http: httpx.Client | None = None, dirs: Iterable[Path] | None = None):
        self.config = config
        self.http = http or httpx.Client(timeout=3)
        self.dirs = dirs
        farm = config.farm
        logging.getLogger("httpx").addFilter(
            _QuietChecks((f"{farm.appium_url.rstrip('/')}/status ", f"{farm.tunneld_url.rstrip('/')}/ ")))

    def check(self, now: datetime) -> FarmHealth:
        farm = self.config.farm
        return FarmHealth(now, check_appium(farm.appium_url, self.http), check_tunneld(farm.tunneld_url, self.http),
                          signing_status(self.config, now, self.dirs))


class FakeFarmChecks:
    """Démo et tests : tout répond, la signature vaut encore 6 jours."""

    def __init__(self, config: Config):
        self.config = config

    def check(self, now: datetime) -> FarmHealth:
        expires = now + timedelta(days=6)
        signing = Signing(signing_state(expires, now, self.config.farm.signing_warn_days), expires,
                          "loopcast.demo.xctrunner")
        return FarmHealth(now, Service(True, "prêt (démo)"), Service(True, "actif (démo)"), signing)


def make_checks(config: Config) -> Checks:
    return FakeFarmChecks(config) if config.farm.backend == "fake" else FarmChecks(config)


# --- Textes -------------------------------------------------------------------------------------------------

def farm_tz(config: Config) -> str:
    """Le fuseau des comptes (devices.yaml) : celui de l'équipe qui lit les alertes."""
    return str((config.defaults or {}).get("timezone") or "Europe/Paris")


def date_text(dt: datetime, tz: str) -> str:
    """« 4 nov. à 22 h 11, heure de Paris » : le fuseau est toujours dit, l'équipe et le Mac n'ont pas forcément
    le même (une notification ntfy se lit n'importe où)."""
    d = dt.astimezone(ZoneInfo(tz))
    city = tz.rsplit("/", 1)[-1].replace("_", " ")
    return f"{d.day} {MONTHS[d.month - 1]} à {d.hour} h {d.minute:02d}, heure de {city}"


def remaining_text(dt: datetime, now: datetime) -> str:
    """« dans 2 jours », « dans 20 h »."""
    hours = (dt - now).total_seconds() / 3600
    if hours < 36:
        return f"dans {max(1, round(hours))} h"
    return f"dans {round(hours / 24)} jours"


def problem_message(code: str, health: FarmHealth, tz: str) -> str:
    message = FARM_PROBLEMS[code][1]
    expires = health.signing.expires_at
    if "{when}" in message:
        when = f"le {date_text(expires, tz)}" if expires else "bientôt"
        if expires and code == "signing_expiring":
            when += f" ({remaining_text(expires, health.checked_at)})"
        message = message.format(when=when)
    return message


def resolved_message(code: str, health: FarmHealth, tz: str) -> str:
    if family(code) == "signing":
        expires = health.signing.expires_at
        return ("Signature de WebDriverAgent renouvelée" +
                (f" : valable jusqu'au {date_text(expires, tz)}" if expires else ""))
    return {"appium": "Appium répond de nouveau", "tunneld": "tunneld répond de nouveau"}[family(code)]


def status_dict(health: FarmHealth | None, problems: Iterable[str], config: Config) -> dict:
    """Ce que la page Ferme affiche : les trois services et les problèmes en cours, avec la marche à suivre."""
    tz = farm_tz(config)
    signing = None
    if health is not None:
        expires = health.signing.expires_at
        signing = {**asdict(health.signing),
                   "expires_at": expires.astimezone(timezone.utc).isoformat(timespec="seconds") if expires else None}
    return {
        "checked_at": health.checked_at.astimezone(timezone.utc).isoformat(timespec="seconds") if health else None,
        "appium": asdict(health.appium) if health else None,
        "tunneld": asdict(health.tunneld) if health else None,
        "signing": signing,
        "problems": [
            {"code": c, "level": FARM_PROBLEMS[c][0], "message": problem_message(c, health, tz),
             "fix": FARM_PROBLEMS[c][2]}
            for c in sorted(problems) if health is not None and c in FARM_PROBLEMS
        ],
    }
