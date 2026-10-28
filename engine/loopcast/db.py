"""SQLite + migrations simples (une liste de scripts, appliqués dans l'ordre)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS = [
    # 1 : schéma de REPRISE §5.1
    """
    CREATE TABLE content(
      id TEXT PRIMARY KEY, brand TEXT, format TEXT, lang TEXT, props TEXT,
      caption TEXT, hashtags TEXT, status TEXT DEFAULT 'draft', files TEXT,
      ai_label INTEGER DEFAULT 0, parent_id TEXT, created_at TEXT, error TEXT);
    CREATE TABLE accounts(
      id TEXT PRIMARY KEY, device TEXT, platform TEXT, handle TEXT, created TEXT,
      channel TEXT, token_ref TEXT, token_expires_at TEXT);
    CREATE TABLE posts(
      id INTEGER PRIMARY KEY AUTOINCREMENT, content_id TEXT, account_id TEXT,
      scheduled_at TEXT, status TEXT DEFAULT 'scheduled', attempts INTEGER DEFAULT 0,
      external_id TEXT, posted_at TEXT, log TEXT, views INTEGER, likes INTEGER, metrics_at TEXT);
    CREATE TABLE account_state(
      account_id TEXT PRIMARY KEY, quota INTEGER, paused_until TEXT, note TEXT, updated_at TEXT);
    CREATE TABLE events(
      id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, account_id TEXT, kind TEXT, message TEXT);
    """,
    # 2 : la ferme d'iPhones
    """
    CREATE TABLE phones(
      udid TEXT PRIMARY KEY,
      phone_id TEXT,                 -- id de devices.yaml (phone-1…), NULL si inconnu
      name TEXT, model TEXT, ios TEXT, connection TEXT,
      status TEXT,                   -- ok | attention | offline | unknown
      problems TEXT,                 -- JSON : liste de codes (untrusted, devmode_off, battery_low…)
      battery INTEGER, charging INTEGER,
      session_id TEXT,               -- session Appium en cours
      first_seen TEXT, last_seen TEXT, updated_at TEXT);
    ALTER TABLE events ADD COLUMN phone_udid TEXT;
    CREATE INDEX events_phone ON events(phone_udid, id);
    """,
]


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {i};\nCOMMIT;")
