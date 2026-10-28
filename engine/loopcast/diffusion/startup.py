"""Au démarrage du serveur (ou du worker) : enfiler le premier tick de l'autopilote.

    from loopcast.diffusion.startup import startup
    startup(conn, config, clock)

Idempotent : la clé du tick est celle de la tranche de 10 min en cours, appeler startup() plusieurs
fois (redémarrages rapprochés) ne crée jamais deux ticks. Ensuite, chaque tick enfile le suivant.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Callable

from loopcast.jobs import utcnow


def startup(conn: sqlite3.Connection, config: Any, clock: Callable[[], datetime] = utcnow) -> int:
    """Enfile le tick de la tranche en cours ; renvoie l'id de la tâche (existante ou nouvelle)."""
    from loopcast.diffusion import autopilot, tasks  # noqa: F401 : enregistre les handlers diffusion.*

    return autopilot.enqueue_tick(conn, clock())
