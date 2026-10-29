"""Supervision de la ferme : un tour = lister les iPhones, vérifier leur santé, noter les changements.

Chaque tour met à jour la table `phones` et n'écrit un événement que lorsqu'un problème
apparaît ou disparaît (pas de bruit à chaque tour). Avec `checks`, le tour vérifie aussi ce dont dépend
le pilotage hors des iPhones : Appium, tunneld et la signature de WebDriverAgent (health.py).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from loopcast.config import Config
from loopcast.farm.backend import BackendError, DeviceBackend, model_name
from loopcast.farm.health import (FARM_PROBLEMS, Checks, FarmHealth, family, farm_tz, problem_message,
                                  resolved_message)

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]

# Un service doit manquer deux tours d'affilée avant l'alerte : un redémarrage d'Appium ne réveille personne.
SERVICE_DOWN_TICKS = 2

# Code → message affiché dans le dashboard et les notifications
PROBLEMS = {
    "untrusted": "Déverrouiller l'iPhone et appuyer sur « Faire confiance »",
    "devmode_off": "Activer le mode développeur (Réglages › Confidentialité et sécurité)",
    "battery_low": "Batterie faible et pas en charge",
    "unknown_phone": "Nouvel iPhone : l'ajouter à la ferme depuis la page Ferme",
    "offline": "iPhone débranché ou injoignable",
    "probe_error": "Lecture de l'état impossible",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TickResult:
    seen: int
    events: list[tuple[str | None, str, str]]   # (udid, ou None pour la ferme ; kind ; message)
    farm_changed: bool = False                  # Appium, tunneld ou la signature ont changé : la page se met à jour


def add_event(conn: sqlite3.Connection, at: datetime, udid: str | None, kind: str, message: str) -> None:
    conn.execute(
        "INSERT INTO events(at, phone_udid, kind, message) VALUES (?,?,?,?)", (iso(at), udid, kind, message)
    )


def _status(problems: list[str]) -> str:
    if "offline" in problems:
        return "offline"
    if "unknown_phone" in problems:
        return "unknown"
    return "attention" if problems else "ok"


def active_farm_problems(conn: sqlite3.Connection) -> set[str]:
    """Les problèmes de la ferme signalés et pas encore résolus, d'après le journal : après un redémarrage, ils
    ne déclenchent pas une nouvelle alerte. Dans chaque famille, le dernier événement fait foi."""
    active: set[str] = set()
    for fam in sorted({family(c) for c in FARM_PROBLEMS}):
        kinds = [f"{p}_{c}" for c in FARM_PROBLEMS if family(c) == fam for p in ("problem", "resolved")]
        row = conn.execute(
            f"SELECT kind FROM events WHERE phone_udid IS NULL AND kind IN ({','.join('?' * len(kinds))}) "
            "ORDER BY id DESC LIMIT 1", kinds).fetchone()
        if row and row["kind"].startswith("problem_"):
            active.add(row["kind"].removeprefix("problem_"))
    return active


class Supervisor:
    def __init__(self, config: Config, conn: sqlite3.Connection, backend: DeviceBackend, clock: Clock = utcnow,
                 checks: Checks | None = None):
        self.config = config
        self.conn = conn
        self.backend = backend
        self.clock = clock
        self.checks = checks                    # santé de la ferme (health.py) ; None : les iPhones seulement
        self.health: FarmHealth | None = None   # dernière vérification d'Appium, de tunneld et de la signature
        self.farm_problems: set[str] = set()    # problèmes de la ferme en cours (codes de FARM_PROBLEMS)
        self._farm_loaded = False
        self._failures: dict[str, int] = {}     # tours d'affilée sans réponse, par service
        self._lock = threading.Lock()

    def tick(self) -> TickResult:
        with self._lock:
            return self._tick()

    def _tick(self) -> TickResult:
        now = self.clock()
        farm = self.config.farm
        events: list[tuple[str | None, str, str]] = []

        def emit(udid: str | None, kind: str, message: str) -> None:
            add_event(self.conn, now, udid, kind, message)
            events.append((udid, kind, message))

        farm_changed = self._farm_tick(now, emit) if self.checks is not None else False

        try:
            devices = self.backend.list_devices()
        except BackendError as e:
            log.error("liste des iPhones impossible : %s", e)
            add_event(self.conn, now, None, "farm_error", f"Liste des iPhones impossible : {e}")
            return TickResult(0, [*events, (None, "farm_error", str(e))], farm_changed)

        known = {r["udid"]: r for r in self.conn.execute("SELECT * FROM phones")}
        seen: set[str] = set()

        for dev in devices:
            seen.add(dev.udid)
            phone = self.config.phone_by_udid(dev.udid)
            problems: list[str] = []
            if phone is None:
                problems.append("unknown_phone")
            try:
                h = self.backend.health(dev.udid)
            except BackendError as e:
                log.warning("%s : santé illisible : %s", dev.udid, e)
                h = None
                problems.append("probe_error")
            if h is not None:
                if not h.trusted:
                    problems.append("untrusted")
                elif h.developer_mode is False:
                    problems.append("devmode_off")
                if h.battery is not None and h.battery < farm.battery_low and not h.charging:
                    problems.append("battery_low")

            prev = known.get(dev.udid)
            prev_problems = set(json.loads(prev["problems"] or "[]")) if prev else set()
            label = phone.id if phone else dev.name or dev.udid

            if prev is None:
                emit(dev.udid, "phone_new", f"Nouvel iPhone branché : {label} ({model_name(dev.model)}, iOS {dev.ios})")
            elif "offline" in prev_problems:
                emit(dev.udid, "phone_back", f"{label} est de nouveau connecté")
            for code in sorted(set(problems) - prev_problems):
                emit(dev.udid, f"problem_{code}", f"{label} : {PROBLEMS[code]}")
            for code in sorted(prev_problems - set(problems) - {"offline", "unknown_phone"}):
                emit(dev.udid, f"resolved_{code}", f"{label} : résolu ({PROBLEMS[code]})")

            self.conn.execute(
                """
                INSERT INTO phones(udid, phone_id, name, model, ios, connection, status, problems,
                                   battery, charging, first_seen, last_seen, updated_at)
                VALUES (:udid,:phone_id,:name,:model,:ios,:connection,:status,:problems,
                        :battery,:charging,:now,:now,:now)
                ON CONFLICT(udid) DO UPDATE SET
                  phone_id=excluded.phone_id, name=excluded.name, model=excluded.model, ios=excluded.ios,
                  connection=excluded.connection, status=excluded.status, problems=excluded.problems,
                  battery=excluded.battery, charging=excluded.charging,
                  last_seen=excluded.last_seen, updated_at=excluded.updated_at
                """,
                {
                    "udid": dev.udid,
                    "phone_id": phone.id if phone else None,
                    "name": dev.name,
                    "model": dev.model,
                    "ios": dev.ios,
                    "connection": dev.connection,
                    "status": _status(problems),
                    "problems": json.dumps(problems),
                    "battery": h.battery if h else None,
                    "charging": None if h is None or h.charging is None else int(h.charging),
                    "now": iso(now),
                },
            )

        # Les iPhones qui ont disparu : hors ligne tout de suite, alerte après `offline_alert_minutes`.
        grace = timedelta(minutes=farm.offline_alert_minutes)
        for udid, prev in known.items():
            if udid in seen:
                continue
            prev_problems = json.loads(prev["problems"] or "[]")
            label = prev["phone_id"] or prev["name"] or udid
            if "offline" not in prev_problems:
                self.conn.execute(
                    "UPDATE phones SET status='offline', problems=?, session_id=NULL, updated_at=? WHERE udid=?",
                    (json.dumps(["offline"]), iso(now), udid),
                )
                emit(udid, "phone_gone", f"{label} a été débranché")
            elif (prev["status"] == "offline" and self.config.phone_by_udid(udid) is not None
                  and now - datetime.fromisoformat(prev["last_seen"]) >= grace):
                if not self.conn.execute(
                    "SELECT 1 FROM events WHERE phone_udid=? AND kind='problem_offline' AND at>=?",
                    (udid, prev["last_seen"]),
                ).fetchone():
                    emit(udid, "problem_offline", f"{label} : {PROBLEMS['offline']} depuis plus de "
                                                  f"{farm.offline_alert_minutes} min")

        # Les iPhones de devices.yaml jamais vus : rien à signaler tant qu'ils ne sont pas branchés.
        return TickResult(len(seen), events, farm_changed)

    def _farm_tick(self, now: datetime, emit: Callable[[str | None, str, str], None]) -> bool:
        """Appium, tunneld, signature : un événement quand un problème apparaît, s'aggrave ou disparaît.
        Renvoie True si ce que la page Ferme affiche a changé."""
        try:
            health = self.checks.check(now)
        except Exception:  # une vérification ratée n'arrête pas la supervision des iPhones
            log.exception("santé de la ferme illisible")
            return False
        if not self._farm_loaded:
            self.farm_problems = active_farm_problems(self.conn)
            self._farm_loaded = True
        previous, self.health = self.health, health

        wanted: set[str] = set()
        for code, service in (("appium_down", health.appium), ("tunneld_down", health.tunneld)):
            self._failures[code] = 0 if service.ok else self._failures.get(code, 0) + 1
            if not service.ok and (code in self.farm_problems or self._failures[code] >= SERVICE_DOWN_TICKS):
                wanted.add(code)
        if health.signing.state in ("expiring", "expired"):
            wanted.add(f"signing_{health.signing.state}")
        elif health.signing.state != "ok":     # aucun profil lisible : on garde ce qui était signalé
            wanted |= {c for c in self.farm_problems if family(c) == "signing"}

        tz = farm_tz(self.config)
        emitted = False
        for fam in sorted({family(c) for c in FARM_PROBLEMS}):
            old = {c for c in self.farm_problems if family(c) == fam}
            new = {c for c in wanted if family(c) == fam}
            if old == new:
                continue
            emitted = True
            if new:     # apparition, ou aggravation (« expire bientôt » → « expirée »)
                code = new.pop()
                emit(None, f"problem_{code}", problem_message(code, health, tz))
            else:
                code = old.pop()
                emit(None, f"resolved_{code}", resolved_message(code, health, tz))
        self.farm_problems = wanted

        def shown(h: FarmHealth | None):
            return h and (h.appium, h.tunneld, h.signing.state, h.signing.expires_at)

        return emitted or shown(previous) != shown(health)

    def run_forever(self, stop: threading.Event, on_events: Callable[[list], None] | None = None) -> None:
        log.info("supervision de la ferme : un tour toutes les %s s", self.config.farm.poll_seconds)
        while not stop.is_set():
            try:
                result = self.tick()
                if on_events and result.events:
                    on_events(result.events)
            except Exception:  # la boucle ne doit jamais mourir
                log.exception("tour de supervision en échec")
            stop.wait(self.config.farm.poll_seconds)


def list_phones(conn: sqlite3.Connection, config: Config) -> list[dict]:
    """Tous les iPhones : ceux vus au moins une fois + ceux de devices.yaml jamais branchés."""
    rows = []
    for r in map(dict, conn.execute("SELECT * FROM phones")):
        phone = config.phone_by_udid(r["udid"])
        if phone is None and r["status"] == "offline":
            continue    # sorti de la ferme (remplacé, retiré de devices.yaml) et débranché : plus rien à en dire
        # Le nom vient de devices.yaml, pas du dernier passage de l'iPhone : un iPhone remplacé ne garde pas sa place.
        r["phone_id"] = phone.id if phone else None
        r["problems"] = [{"code": c, "message": PROBLEMS.get(c, c)} for c in json.loads(r["problems"] or "[]")]
        r["model_name"] = model_name(r["model"] or "")
        r["owner"] = phone.owner if phone else ""
        r["slot"] = phone.slot if phone else None
        rows.append(r)
    seen_udids = {r["udid"] for r in rows}
    for p in config.phones:
        if p.udid and p.udid in seen_udids:
            continue
        rows.append({
            "udid": p.udid, "phone_id": p.id, "name": "", "model": "", "model_name": "", "ios": "", "connection": None,
            "status": "never_seen", "owner": p.owner, "slot": p.slot, "battery": None, "charging": None,
            "session_id": None, "last_seen": None,
            "problems": [{"code": "never_seen", "message": "Jamais branché" if p.udid else "Place libre"}],
        })
    rows.sort(key=lambda r: (r["phone_id"] is None, r["phone_id"] or "", r["name"] or ""))
    return rows
