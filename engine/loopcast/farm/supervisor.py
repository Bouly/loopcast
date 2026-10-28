"""Supervision de la ferme : un tour = lister les iPhones, vérifier leur santé, noter les changements.

Chaque tour met à jour la table `phones` et n'écrit un événement que lorsqu'un problème
apparaît ou disparaît (pas de bruit à chaque tour).
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

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]

# Code → message affiché dans le dashboard et les notifications
PROBLEMS = {
    "untrusted": "Déverrouiller l'iPhone et appuyer sur « Faire confiance »",
    "devmode_off": "Activer le mode développeur (Réglages › Confidentialité et sécurité)",
    "battery_low": "Batterie faible et pas en charge",
    "unknown_phone": "iPhone inconnu : l'ajouter dans config/devices.yaml",
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
    events: list[tuple[str, str, str]]   # (udid, kind, message)


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


class Supervisor:
    def __init__(self, config: Config, conn: sqlite3.Connection, backend: DeviceBackend, clock: Clock = utcnow):
        self.config = config
        self.conn = conn
        self.backend = backend
        self.clock = clock
        self._lock = threading.Lock()

    def tick(self) -> TickResult:
        with self._lock:
            return self._tick()

    def _tick(self) -> TickResult:
        now = self.clock()
        farm = self.config.farm
        events: list[tuple[str, str, str]] = []

        def emit(udid: str, kind: str, message: str) -> None:
            add_event(self.conn, now, udid, kind, message)
            events.append((udid, kind, message))

        try:
            devices = self.backend.list_devices()
        except BackendError as e:
            log.error("liste des iPhones impossible : %s", e)
            add_event(self.conn, now, None, "farm_error", f"Liste des iPhones impossible : {e}")
            return TickResult(0, [(None, "farm_error", str(e))])

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
            for code in sorted(prev_problems - set(problems) - {"offline"}):
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
            elif prev["status"] == "offline" and now - datetime.fromisoformat(prev["last_seen"]) >= grace:
                if not self.conn.execute(
                    "SELECT 1 FROM events WHERE phone_udid=? AND kind='problem_offline' AND at>=?",
                    (udid, prev["last_seen"]),
                ).fetchone():
                    emit(udid, "problem_offline", f"{label} : {PROBLEMS['offline']} depuis plus de "
                                                  f"{farm.offline_alert_minutes} min")

        # Les iPhones de devices.yaml jamais vus : rien à signaler tant qu'ils ne sont pas branchés.
        return TickResult(len(seen), events)

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
    rows = [dict(r) for r in conn.execute("SELECT * FROM phones")]
    for r in rows:
        r["problems"] = [{"code": c, "message": PROBLEMS.get(c, c)} for c in json.loads(r["problems"] or "[]")]
        r["model_name"] = model_name(r["model"] or "")
        phone = config.phone_by_udid(r["udid"])
        r["owner"] = phone.owner if phone else ""
        r["slot"] = phone.slot if phone else None
    seen_udids = {r["udid"] for r in rows}
    for p in config.phones:
        if p.udid and p.udid in seen_udids:
            continue
        rows.append({
            "udid": p.udid, "phone_id": p.id, "name": "", "model": "", "model_name": "", "ios": "", "connection": None,
            "status": "never_seen", "owner": p.owner, "slot": p.slot, "battery": None, "charging": None,
            "session_id": None, "last_seen": None,
            "problems": [{"code": "never_seen", "message": "Jamais branché" if p.udid else "UDID à renseigner"}],
        })
    rows.sort(key=lambda r: (r["phone_id"] is None, r["phone_id"] or "", r["name"] or ""))
    return rows
