"""Lecture et écriture des lignes `content` et `ideas` pour le module production (tâches, API, CLI).

Statuts d'un contenu (docs/architecture-pipeline.md) :
    draft → rendering → rendered → approved            (ou qa_failed, rejected, failed)
« À valider » = `rendered` avec un contrôle qualité réussi : rien d'autre n'atteint la validation.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from loopcast.jobs import iso

ACTIVE = ("draft", "rendering")                 # production en cours
FAILED = ("failed", "qa_failed")
FINAL = ("approved", "rejected")                # décidé par un humain (ou par review_mode: auto)

# L'accroche de l'idée : le titre d'une vidéo dans tous les écrans (validation, calendrier, idées).
# Sous-requête plutôt que jointure : les colonnes de `content` restent sans préfixe dans les filtres.
WITH_HOOK = "SELECT *, (SELECT i.hook FROM ideas i WHERE i.id = content.idea_id) AS hook FROM content"


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Plusieurs écritures d'un coup (la connexion est en autocommit)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def get_content(conn: sqlite3.Connection, content_id: str) -> sqlite3.Row | None:
    return conn.execute(f"{WITH_HOOK} WHERE id=?", (content_id,)).fetchone()


def get_idea(conn: sqlite3.Connection, idea_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()


def qa_ok(row: sqlite3.Row | dict) -> bool:
    report = loads(row["qa"], {}) or {}
    return bool(report.get("ok"))


def to_review(row: sqlite3.Row | dict) -> bool:
    return row["status"] == "rendered" and qa_ok(row)


def set_content(conn: sqlite3.Connection, content_id: str, now: datetime, **fields: Any) -> None:
    """UPDATE content SET … (les listes et dicts sont écrits en JSON)."""
    fields["updated_at"] = iso(now)
    cols = ", ".join(f"{k}=?" for k in fields)
    values = [dumps(v) if isinstance(v, (list, dict)) else v for v in fields.values()]
    conn.execute(f"UPDATE content SET {cols} WHERE id=?", (*values, content_id))


def set_idea(conn: sqlite3.Connection, idea_id: str | None, now: datetime, status: str,
             error: str | None = None) -> None:
    if idea_id:
        conn.execute("UPDATE ideas SET status=?, error=?, updated_at=? WHERE id=?",
                     (status, error, iso(now), idea_id))


def event(conn: sqlite3.Connection, now: datetime, kind: str, message: str, account_id: str | None = None) -> None:
    """Journal du pipeline (`events`), kind préfixé par le module : « content.failed »…"""
    conn.execute("INSERT INTO events(at, account_id, kind, message) VALUES (?,?,?,?)",
                 (iso(now), account_id, kind, message[:1000]))


def fail_content(conn: sqlite3.Connection, row: sqlite3.Row, now: datetime, error: str,
                 status: str = "failed") -> None:
    """Le contenu (et son idée) passent en échec avec une raison lisible."""
    with tx(conn):
        set_content(conn, row["id"], now, status=status, error=error)
        set_idea(conn, row["idea_id"], now, "failed", error)
        event(conn, now, f"content.{status}", f"{row['id']} : {error}", row["account_id"])


def content_jobs(conn: sqlite3.Connection, content_id: str, idea_id: str | None = None,
                 statuses: tuple[str, ...] | None = None) -> list[sqlite3.Row]:
    """Les tâches content.* et video.* de ce contenu (repérées par leur payload)."""
    sql = ("SELECT * FROM jobs WHERE (kind LIKE 'content.%' OR kind LIKE 'video.%') "
           "AND (json_extract(payload, '$.content_id') = ? OR json_extract(payload, '$.idea_id') = ?)")
    args: list = [content_id, idea_id or content_id]
    if statuses:
        sql += f" AND status IN ({','.join('?' * len(statuses))})"
        args += list(statuses)
    return conn.execute(sql + " ORDER BY id", args).fetchall()


def in_flight(conn: sqlite3.Connection, content_id: str, idea_id: str | None = None) -> bool:
    """Une tâche content.* de ce contenu attend ou tourne-t-elle encore ?"""
    return any(r["kind"].startswith("content.")
               for r in content_jobs(conn, content_id, idea_id, ("queued", "running")))


def out_dir(config: Any) -> Path:
    """Les rendus : out/<content_id>/ (ignoré par git) ; en démo, data/demo/out/ (config.out_dir)."""
    return Path(getattr(config, "out_dir", None) or Path(config.root) / "out")


def content_dir(config: Any, content_id: str) -> Path:
    return out_dir(config) / content_id


def summary(row: sqlite3.Row) -> dict:
    """Une ligne de la file de validation (sans le détail des plans). `hook` : l'accroche de l'idée (lue avec
    WITH_HOOK), None pour un contenu sans idée."""
    d = dict(row)
    d["hook"] = d.get("hook") or None
    d["hashtags"] = loads(d.get("hashtags"), [])
    files = loads(d.get("files"), []) or []
    d["files"] = files
    report = loads(d.get("qa"), None)
    d["qa"] = report
    d["qa_ok"] = bool(report and report.get("ok"))
    d["to_review"] = d["status"] == "rendered" and d["qa_ok"]
    d["media"] = [f"/api/content/{row['id']}/media/{i}" for i in range(len(files))]
    d["poster"] = f"/api/content/{row['id']}/poster" if files else None
    d.pop("props", None)
    return d
