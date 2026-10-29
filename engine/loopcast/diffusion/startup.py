"""Au démarrage du serveur (ou du worker) : enfiler le premier tick de l'autopilote ; ensuite, le chien de garde.

    from loopcast.diffusion.startup import startup
    startup(conn, config, clock)

Idempotent : la clé du tick est celle de la tranche de 10 min en cours, appeler startup() plusieurs
fois (redémarrages rapprochés) ne crée jamais deux ticks. Ensuite, chaque tick enfile le suivant.

Si la chaîne casse quand même (le tick n'a pas pu écrire son successeur, il est mort, ou quelqu'un l'a
annulé), plus rien ne la relançait jusqu'au prochain redémarrage : ni planification, ni publication, ni
métriques. watchdog(), appelé toutes les ~5 min par le premier exécutant de la file (modules.watchdog),
vérifie qu'un tick est en attente ou en cours, et sinon en enfile un, avec un événement au journal.
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


def watchdog(conn: sqlite3.Connection, config: Any, clock: Callable[[], datetime] = utcnow) -> int | None:
    """Un tick doit toujours être en attente ou en cours ; sinon on en enfile un (celui de la tranche en cours,
    ou de la suivante si la tranche a déjà eu le sien). Renvoie l'id du tick enfilé, None si la chaîne tenait."""
    from loopcast.diffusion import alerts, autopilot, tasks  # noqa: F401 : enregistre les handlers diffusion.*

    if _pending_tick(conn):
        return None
    now = clock()
    last = conn.execute("SELECT id, key, status, last_error FROM jobs WHERE kind='diffusion.tick' "
                        "ORDER BY id DESC LIMIT 1").fetchone()
    job_id = autopilot.enqueue_tick(conn, now)                       # la tranche en cours, tout de suite…
    if not _pending_tick(conn):                                      # … elle a déjà eu son tick : la suivante
        job_id = autopilot.enqueue_tick(conn, now, next_slice=True)
    if last is None:
        why = "aucun tick n'existait"
    else:
        error = (last["last_error"] or "").strip().splitlines()
        why = f"le dernier tick (#{last['id']}, {last['key']}) est « {last['status']} »" + (
            f" : {error[-1][:200]}" if error else "")
    alerts.event(conn, now, "diffusion.watchdog",
                 f"autopilote relancé par le chien de garde : plus aucun tick en attente ({why})")
    return job_id


def _pending_tick(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM jobs WHERE kind='diffusion.tick' AND status IN ('queued', 'running') "
                        "LIMIT 1").fetchone() is not None
