"""Autopilote : la tâche diffusion.tick, toutes les 10 minutes, qui se ré-enfile elle-même.

Chaque tick a une clé « diffusion.tick:<début de la tranche de 10 min> » : deux ticks pour la même
tranche n'existent jamais, même si le serveur redémarre ou si startup() est appelé plusieurs fois. Le tick
suivant est enfilé AVANT le travail : une erreur n'interrompt jamais la chaîne.

Un tour (chaque étape est indépendante : une étape en erreur n'empêche pas les suivantes) :
1. comptes : alignés sur devices.yaml (accounts.sync_from_config) ;
2. posts restés « running » (processus arrêté pendant une publication) → « à finir », avec alerte ;
3. régulateur : toutes les heures (et au changement de jour local) ;
4. créneaux manqués (Mac éteint…) → annulés, leur contenu redevient disponible ;
5. planification du jour (idempotente : ne complète que ce qui manque) ;
6. posts dus d'ici le prochain tour → tâches diffusion.publish, à l'heure de leur créneau ;
7. métriques toutes les `metrics_every_hours` → tâche diffusion.metrics (puis boucle des gagnants) ;
8. stock de contenus validés → diffusion.stock_bas + ideas.ensure_stock.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from loopcast import accounts, jobs
from loopcast.diffusion import alerts, executor, metrics, planner, regulator
from loopcast.diffusion.settings import DiffusionSettings
from loopcast.diffusion.store import iso, tx

log = logging.getLogger(__name__)

TICK_MINUTES = 10


def slice_start(now: datetime) -> datetime:
    now = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return now - timedelta(minutes=now.minute % TICK_MINUTES)


def tick_key(start: datetime) -> str:
    return f"diffusion.tick:{start:%Y-%m-%dT%H:%M}"


def enqueue_tick(conn: sqlite3.Connection, now: datetime, *, next_slice: bool = False) -> int:
    """Le tick de la tranche en cours (tout de suite) ou de la suivante (à son début). Idempotent."""
    start = slice_start(now) + (timedelta(minutes=TICK_MINUTES) if next_slice else timedelta(0))
    return jobs.enqueue(conn, "diffusion.tick", {"slice": iso(start)}, key=tick_key(start),
                        run_after=max(start, now), priority=1, clock=lambda: now)


def services_of(config, services: dict[str, Any] | None) -> tuple[Any, Any]:
    """Les publishers et le notificateur injectés (tests, démo), sinon ceux de la configuration."""
    from loopcast.diffusion.publishers import Publishers

    services = services or {}
    return services.get("publishers") or Publishers.from_config(config), services.get("notify")


def run_tick(conn: sqlite3.Connection, config, now: datetime, *, services: dict[str, Any] | None = None,
             force: bool = False) -> dict:
    """Un tour complet. `force` recalcule le régulateur même s'il a tourné dans l'heure."""
    s = DiffusionSettings.from_config(config)
    publishers, notifier = services_of(config, services)
    report: dict[str, Any] = {"at": iso(now), "errors": []}

    def step(name: str, fn: Callable[[], Any]) -> None:
        try:
            report[name] = fn()
        except Exception as e:  # noqa: BLE001 : une étape en erreur ne bloque pas les autres
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            log.exception("diffusion.tick, étape %s", name)
            report["errors"].append(f"{name} : {type(e).__name__}: {e}")
            alerts.event(conn, now, "diffusion.error", f"tick, étape « {name} » : {type(e).__name__}: {e}")

    def sync() -> int:
        with tx(conn):
            return len(accounts.sync_from_config(conn, config))

    step("accounts", sync)
    step("stuck", lambda: executor.recover_stuck(conn, s, now, notifier))
    step("regulator", lambda: {st.account_id: {"quota": st.quota, "state": st.state}
                               for st in regulator.regulate_all(conn, config, now, settings=s, force=force,
                                                                notifier=notifier)})
    step("missed", lambda: executor.skip_missed(conn, s, now))
    step("plan", lambda: [p.to_dict() for p in planner.plan_day(conn, config, now, publishers=publishers, settings=s,
                                                                 notifier=notifier)
                          if p.planned or p.trimmed or p.missing])
    step("due", lambda: executor.enqueue_due(conn, now))
    step("metrics", lambda: metrics.enqueue_metrics(conn, s, now))
    step("stock", lambda: {app: dict(items)
                           for app, items in planner.check_stock(conn, config, now, settings=s).items()})
    return report


def run_once(conn: sqlite3.Connection, config, clock: Callable[[], datetime], *,
             services: dict[str, Any] | None = None, force: bool = True, max_jobs: int = 200) -> dict:
    """Un tour, puis les tâches diffusion.* prêtes, tout de suite (CLI `diffusion tick`, sans serveur)."""
    from loopcast.diffusion import tasks  # noqa: F401 : enregistre les handlers

    report = run_tick(conn, config, clock(), services=services, force=force)
    ran: list[str] = []
    for _ in range(max_jobs):
        job = jobs.run_one(conn, config, "cli", clock=clock, services=services or {},
                           kinds=["diffusion.publish", "diffusion.metrics"])
        if job is None:
            break
        ran.append(f"{job.kind} #{job.id}")
    report["jobs"] = ran
    return report
