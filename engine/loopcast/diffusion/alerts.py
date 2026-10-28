"""Journal (table events, kind « diffusion.… ») et alertes humaines (notifications macOS + ntfy).

Ce qui dérange quelqu'un : un post à finir, un échec répété, un compte en pause, plus aucun contenu
validé. Le reste ne va que dans le journal.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Callable

from loopcast.diffusion.store import iso

log = logging.getLogger(__name__)

Notifier = Callable[[str, str, dict | None], None]

TITLE = "Loopcast · diffusion"


def event(conn: sqlite3.Connection, now: datetime, kind: str, message: str, account_id: str | None = None) -> None:
    conn.execute("INSERT INTO events(at, account_id, kind, message) VALUES (?,?,?,?)",
                 (iso(now), account_id, kind, message))


def alert(conn: sqlite3.Connection, now: datetime, kind: str, message: str, *, account_id: str | None = None,
          notify_settings: dict | None = None, notifier: Notifier | None = None) -> None:
    """Inscrit l'événement et prévient l'équipe. Une notification qui échoue ne casse rien."""
    event(conn, now, kind, message, account_id)
    send = notifier or _default_notifier
    try:
        send(TITLE, message, notify_settings or {})
    except Exception as e:  # noqa: BLE001
        log.warning("notification impossible : %s", e)


def _default_notifier(title: str, message: str, settings: dict | None) -> None:
    from loopcast import notify

    notify.notify(title, message, settings)


def already_today(conn: sqlite3.Connection, kind: str, account_id: str | None, since: datetime) -> bool:
    """Cet événement a-t-il déjà été inscrit depuis `since` (pour ne pas répéter une alerte) ?"""
    row = conn.execute(
        "SELECT 1 FROM events WHERE kind=? AND COALESCE(account_id, '')=COALESCE(?, '') AND at >= ? LIMIT 1",
        (kind, account_id, iso(since)),
    ).fetchone()
    return row is not None
