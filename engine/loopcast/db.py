"""SQLite + migrations en fichiers (engine/loopcast/migrations/NNNN_nom.sql, appliqués dans l'ordre).

Chaque module du pipeline a sa plage de numéros (docs/architecture-pipeline.md) : deux modules
peuvent ajouter une migration en même temps sans se marcher dessus.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Avant les fichiers, le schéma suivait PRAGMA user_version : 1 = 0001_base, 2 = 0002_phones.
_LEGACY = ["0001_base", "0002_phones"]


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def connect(path: Path | str, *, run_migrations: bool = True) -> sqlite3.Connection:
    """Une connexion par thread : la file de tâches et l'API ouvrent chacune la leur."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    if run_migrations:
        migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Applique les migrations manquantes, chacune dans sa transaction. Renvoie celles appliquées."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    if not done:
        legacy = conn.execute("PRAGMA user_version").fetchone()[0]
        for name in _LEGACY[:legacy]:
            conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (name, _now()))
            done.add(name)
    applied = []
    for path in migration_files():
        name = path.stem
        if name in done:
            continue
        # executescript valide toute transaction ouverte : on encadre nous-mêmes.
        try:
            conn.executescript(
                f"BEGIN;\n{path.read_text()}\n"
                f"INSERT INTO schema_migrations VALUES ('{name}', '{_now()}');\nCOMMIT;"
            )
        except sqlite3.Error as e:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise RuntimeError(f"migration {name} en échec : {e}") from e
        applied.append(name)
    return applied


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
