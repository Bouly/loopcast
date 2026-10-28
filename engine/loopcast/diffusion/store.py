"""Accès à la base pour le module diffusion : posts, état des comptes, contenus, journal.

Statuts d'un post : scheduled → running → posted | needs_human | failed, ou skipped (jamais tenté :
créneau manqué, compte en pause, quota réduit, contenu retiré). Un post « skipped » libère son contenu :
il peut être replanifié (on réutilise alors la même ligne, l'index unique posts(content_id, platform)
interdisant d'en créer une seconde).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from loopcast.accounts import Account
from loopcast.diffusion.publishers.base import ContentItem

ACTIVE_STATUSES = ("scheduled", "running", "needs_human", "posted", "failed")   # comptent dans la journée
PENDING_STATUSES = ("running", "needs_human", "posted")                      # sont (peut-être) en ligne


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@contextmanager
def tx(conn: sqlite3.Connection):
    """Transaction d'écriture (BEGIN IMMEDIATE : une seule à la fois) ; rejoint celle qui est ouverte."""
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


# --- Comptes ---------------------------------------------------------------------------------------------

def get_account(conn: sqlite3.Connection, account_id: str) -> Account | None:
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return Account.from_row(row) if row else None


@dataclass
class AccountState:
    account_id: str
    quota: int = 0
    state: str = "active"
    day: str | None = None
    target: int | None = None
    base: int | None = None
    ratio: float | None = None
    note: str = ""
    paused_until: datetime | None = None
    paused_by: str | None = None
    paused_reason: str | None = None
    regulated_at: datetime | None = None
    updated_at: datetime | None = None

    def paused(self, now: datetime) -> bool:
        return self.paused_until is not None and self.paused_until > now

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "AccountState":
        return cls(r["account_id"], int(r["quota"] or 0), r["state"] or "active", r["day"], r["target"], r["base"],
                   r["ratio"], r["note"] or "", parse_dt(r["paused_until"]), r["paused_by"], r["paused_reason"],
                   parse_dt(r["regulated_at"]), parse_dt(r["updated_at"]))


def get_state(conn: sqlite3.Connection, account_id: str) -> AccountState | None:
    row = conn.execute("SELECT * FROM account_state WHERE account_id=?", (account_id,)).fetchone()
    return AccountState.from_row(row) if row else None


def save_state(conn: sqlite3.Connection, st: AccountState, now: datetime) -> None:
    conn.execute(
        """INSERT INTO account_state(account_id, quota, state, day, target, base, ratio, note, paused_until, paused_by,
                                     paused_reason, regulated_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(account_id) DO UPDATE SET quota=excluded.quota, state=excluded.state, day=excluded.day,
             target=excluded.target, base=excluded.base, ratio=excluded.ratio, note=excluded.note,
             paused_until=excluded.paused_until, paused_by=excluded.paused_by, paused_reason=excluded.paused_reason,
             regulated_at=excluded.regulated_at, updated_at=excluded.updated_at""",
        (st.account_id, st.quota, st.state, st.day, st.target, st.base, st.ratio, st.note,
         iso(st.paused_until) if st.paused_until else None, st.paused_by, st.paused_reason,
         iso(st.regulated_at) if st.regulated_at else None, iso(now)),
    )


# --- Posts ---------------------------------------------------------------------------------------------

@dataclass
class Post:
    id: int
    content_id: str
    account_id: str
    platform: str | None
    app_id: str | None
    status: str
    scheduled_at: datetime | None
    planned_at: datetime | None
    attempts: int
    external_id: str | None
    posted_at: datetime | None
    views: int | None
    likes: int | None
    metrics_at: datetime | None
    winner_at: datetime | None
    channel: str | None
    url: str | None
    log: list[dict] = field(default_factory=list)
    format: str | None = None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Post":
        keys = r.keys()
        return cls(r["id"], r["content_id"], r["account_id"], r["platform"], r["app_id"], r["status"],
                   parse_dt(r["scheduled_at"]), parse_dt(r["planned_at"]), int(r["attempts"] or 0), r["external_id"],
                   parse_dt(r["posted_at"]), r["views"], r["likes"], parse_dt(r["metrics_at"]),
                   parse_dt(r["winner_at"]), r["channel"], r["url"], read_log(r["log"]),
                   r["format"] if "format" in keys else None)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "content_id": self.content_id, "account_id": self.account_id, "platform": self.platform,
            "app_id": self.app_id, "status": self.status, "format": self.format,
            "scheduled_at": iso(self.scheduled_at) if self.scheduled_at else None,
            "planned_at": iso(self.planned_at) if self.planned_at else None,
            "attempts": self.attempts, "external_id": self.external_id, "url": self.url, "channel": self.channel,
            "posted_at": iso(self.posted_at) if self.posted_at else None,
            "views": self.views, "likes": self.likes, "metrics_at": iso(self.metrics_at) if self.metrics_at else None,
            "winner": self.winner_at is not None, "log": self.log,
        }


POST_SELECT = "SELECT p.*, c.format AS format FROM posts p LEFT JOIN content c ON c.id = p.content_id"


def read_log(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        return [{"at": None, "msg": str(raw)}]
    return value if isinstance(value, list) else [{"at": None, "msg": str(value)}]


def get_post(conn: sqlite3.Connection, post_id: int) -> Post | None:
    row = conn.execute(POST_SELECT + " WHERE p.id=?", (post_id,)).fetchone()
    return Post.from_row(row) if row else None


def posts_between(conn: sqlite3.Connection, account_id: str, start: datetime, end: datetime,
                  statuses: tuple[str, ...] = ACTIVE_STATUSES) -> list[Post]:
    marks = ",".join("?" * len(statuses))
    rows = conn.execute(
        POST_SELECT + f" WHERE p.account_id=? AND p.scheduled_at >= ? AND p.scheduled_at < ? AND p.status IN ({marks})"
                      " ORDER BY p.scheduled_at, p.id",
        (account_id, iso(start), iso(end), *statuses),
    ).fetchall()
    return [Post.from_row(r) for r in rows]


def log_post(conn: sqlite3.Connection, post_id: int, now: datetime, message: str) -> None:
    conn.execute(
        """UPDATE posts SET log = json_insert(CASE WHEN json_valid(log) THEN log ELSE '[]' END, '$[#]',
                                              json_object('at', ?, 'msg', ?)),
                  updated_at = ?
           WHERE id = ?""",
        (iso(now), message, iso(now), post_id),
    )


def update_post(conn: sqlite3.Connection, post_id: int, now: datetime, message: str | None = None, **fields) -> None:
    """Met à jour les champs donnés (+ une ligne de journal)."""
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        values = [iso(v) if isinstance(v, datetime) else v for v in fields.values()]
        conn.execute(f"UPDATE posts SET {sets}, updated_at=? WHERE id=?", (*values, iso(now), post_id))
    if message:
        log_post(conn, post_id, now, message)


# --- Contenus -----------------------------------------------------------------------------------------------

def get_content(conn: sqlite3.Connection, content_id: str) -> ContentItem | None:
    row = conn.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone()
    return ContentItem.from_row(row) if row else None
