"""Ce dont les routes des modules ont besoin, sans dépendre de create_app.

    from loopcast.api import deps

    @router.get("/{app_id}")
    def get_app(app_id: str, request: Request):
        conn = deps.conn(request)            # connexion SQLite propre à ce thread
        config = deps.config(request)
        ...
        deps.publish(request, "apps", {"id": app_id})   # prévient le front (SSE)
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from loopcast import db

_local = threading.local()


def conn(request: Request):
    """Une connexion SQLite par thread de l'API (FastAPI exécute les routes `def` dans un pool)."""
    path = str(request.app.state.db_path)
    if path == ":memory:":
        # Base en mémoire (tests) : une seule connexion par application, jamais mise en cache entre apps.
        return request.app.state.conn
    cache = getattr(_local, "conns", None)
    if cache is None:
        cache = _local.conns = {}
    c = cache.get(path)
    if c is None:
        c = cache[path] = db.connect(path, run_migrations=False)
    return c


def config(request: Request) -> Any:
    return request.app.state.config


def services(request: Request) -> dict[str, Any]:
    return request.app.state.services


def clock(request: Request) -> datetime:
    fn = getattr(request.app.state, "clock", None)
    return fn() if fn else datetime.now(timezone.utc)


def publish(request: Request, kind: str, data: dict) -> None:
    """Événement temps réel vers le front (/api/live)."""
    bus = getattr(request.app.state, "bus", None)
    if bus is not None:
        bus.publish(kind, data)
