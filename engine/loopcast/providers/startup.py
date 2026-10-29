"""Chien de garde du module providers (modules.watchdog : au lancement des exécutants, puis toutes les ~5 min).

Toute génération soumise finit inscrite au registre des coûts. La tâche video.generate (ou image.generate)
l'inscrit elle-même : terminée, en échec, ou annulée pour délai dépassé. Mais une tâche morte, ou annulée de
l'extérieur — la production renonce à un contenu après son délai, une annulation depuis le dashboard — ne
repasse plus : ses générations soumises sont inscrites ici, à leur estimation (tasks.settle_abandoned).
En attendant, le budget les compte déjà (tasks.inflight_usd).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Callable

from loopcast.jobs import iso, utcnow


def watchdog(conn: sqlite3.Connection, config: Any, clock: Callable[[], datetime] = utcnow) -> int:
    """Inscrit les générations abandonnées ; renvoie leur nombre (un événement « providers.cost » s'il y en a)."""
    from loopcast.providers import tasks

    now = clock()
    n = tasks.settle_abandoned(conn, now)
    if n:
        conn.execute("INSERT INTO events(at, kind, message) VALUES (?,?,?)",
                     (iso(now), "providers.cost", f"{n} génération(s) abandonnée(s) inscrite(s) au registre des "
                                                 "coûts à leur estimation (elles ont pu être facturées)"))
    return n
