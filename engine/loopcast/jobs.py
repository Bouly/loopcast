"""File de tâches durable dans SQLite : tout le pipeline passe par elle.

- Idempotente : une tâche a une clé ; la créer deux fois ne la crée qu'une fois.
- Sûre en cas de plantage : une tâche prise a un bail (lease) ; si le processus meurt, le bail
  expire et la tâche repart.
- Nouvelles tentatives avec attente croissante (et un peu d'aléa), puis « dead » : visible dans le
  dashboard, jamais perdue en silence.
- Une tâche peut demander à être reprise plus tard sans consommer d'essai (RetryLater) : c'est ce
  que font les générateurs vidéo pendant qu'ils calculent.
- Limite de tâches simultanées par famille (« video. » : 2, par exemple), pour ne pas saturer un
  fournisseur ni le budget.
- Un chien de garde : le premier exécutant appelle modules.watchdog toutes les ~5 min, pour relancer ce
  qui doit toujours tourner (le tick de l'autopilote) même si la chaîne a cassé.

Un module déclare ses tâches avec @handler("app.analyze") ; jobs.run_worker() les exécute.
"""

from __future__ import annotations

import json
import logging
import random
import socket
import sqlite3
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# --- Exceptions qu'un handler peut lever ------------------------------------------------------

class RetryLater(Exception):
    """Pas une erreur : « reviens dans `delay_s` secondes » (sondage d'un générateur, quota…).
    Ne consomme pas d'essai."""

    def __init__(self, delay_s: float, reason: str = "", result: dict | None = None):
        super().__init__(reason or f"reprise dans {delay_s:.0f} s")
        self.delay_s = delay_s
        self.result = result


class Permanent(Exception):
    """Échec définitif : inutile de réessayer (donnée invalide, clé absente, budget épuisé…).
    `result` est gardé sur la tâche (état utile pour comprendre, ou pour qu'une relance reparte de zéro)."""

    def __init__(self, message: str = "", result: dict | None = None):
        super().__init__(message)
        self.result = result


# --- Déclaration des handlers --------------------------------------------------------------------

class Handler(Protocol):
    def __call__(self, ctx: "JobContext", payload: dict) -> dict | None: ...


@dataclass
class HandlerSpec:
    kind: str
    fn: Handler
    max_attempts: int = 3
    lease_s: int = 600                    # au-delà, la tâche est considérée comme orpheline
    backoff_s: tuple[int, ...] = (30, 120, 600, 1800)


HANDLERS: dict[str, HandlerSpec] = {}


def handler(kind: str, *, max_attempts: int = 3, lease_s: int = 600,
            backoff_s: tuple[int, ...] = (30, 120, 600, 1800)):
    """@handler("content.render", max_attempts=2, lease_s=900)"""

    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = HandlerSpec(kind, fn, max_attempts, lease_s, backoff_s)
        return fn

    return deco


# --- Une tâche en cours d'exécution ---------------------------------------------------------------

@dataclass
class Job:
    id: int
    kind: str
    key: str | None
    payload: dict
    attempts: int
    max_attempts: int
    app_id: str | None
    parent_id: int | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Job":
        return cls(r["id"], r["kind"], r["key"], json.loads(r["payload"] or "{}"), r["attempts"],
                   r["max_attempts"], r["app_id"], r["parent_id"])


@dataclass
class JobContext:
    """Ce qu'un handler reçoit : la connexion de SON thread, la config, l'horloge, la tâche."""
    conn: sqlite3.Connection
    config: Any
    job: Job
    clock: Clock = utcnow
    services: dict[str, Any] = field(default_factory=dict)   # llm, providers… injectés (tests : faux)

    def enqueue(self, kind: str, payload: dict | None = None, **kw) -> int:
        kw.setdefault("app_id", self.job.app_id)
        kw.setdefault("parent_id", self.job.id)
        return enqueue(self.conn, kind, payload or {}, clock=self.clock, **kw)

    def service(self, name: str):
        if name not in self.services:
            raise Permanent(f"service « {name} » non configuré")
        return self.services[name]


# --- API de la file ---------------------------------------------------------------------------------

def enqueue(conn: sqlite3.Connection, kind: str, payload: dict | None = None, *, key: str | None = None,
            app_id: str | None = None, parent_id: int | None = None, run_after: datetime | None = None,
            priority: int = 0, max_attempts: int | None = None, clock: Clock = utcnow) -> int:
    """Crée la tâche, ou renvoie l'id de celle qui a déjà cette clé (idempotence)."""
    now = clock()
    spec = HANDLERS.get(kind)
    attempts = max_attempts or (spec.max_attempts if spec else 3)
    cur = conn.execute(
        """INSERT INTO jobs(kind, key, payload, status, priority, attempts, max_attempts, run_after,
                            app_id, parent_id, created_at, updated_at)
           VALUES (?,?,?,?,?,0,?,?,?,?,?,?)
           ON CONFLICT(key) DO NOTHING""",
        (kind, key, json.dumps(payload or {}, ensure_ascii=False), "queued", priority, attempts,
         iso(run_after or now), app_id, parent_id, iso(now), iso(now)),
    )
    if cur.rowcount == 1:
        return cur.lastrowid
    row = conn.execute("SELECT id FROM jobs WHERE key=?", (key,)).fetchone()
    return row["id"]


def claim(conn: sqlite3.Connection, worker: str, *, clock: Clock = utcnow,
          limits: dict[str, int] | None = None, kinds: list[str] | None = None) -> Job | None:
    """Prend atomiquement la prochaine tâche prête, en respectant les limites par famille."""
    now = clock()
    limits = limits or {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        running: dict[str, int] = {}
        if limits:
            for r in conn.execute("SELECT kind, COUNT(*) n FROM jobs WHERE status='running' GROUP BY kind"):
                running[r["kind"]] = r["n"]
        # Seulement les familles que ce processus sait traiter : une tâche d'un module absent attend
        # (un autre processus, plus récent, la prendra) sans bloquer les autres.
        known = [k for k in HANDLERS if not kinds or any(k == p or k.startswith(p) for p in kinds)]
        if not known:
            conn.execute("COMMIT")
            return None
        marks = ",".join("?" * len(known))
        rows = conn.execute(
            f"""SELECT * FROM jobs WHERE status='queued' AND run_after <= ? AND kind IN ({marks})
                ORDER BY priority DESC, run_after, id LIMIT 200""",
            (iso(now), *known),
        ).fetchall()
        chosen = None
        for r in rows:
            if _over_limit(r["kind"], running, limits):
                continue
            chosen = r
            break
        if chosen is None:
            conn.execute("COMMIT")
            return None
        spec = HANDLERS[chosen["kind"]]
        conn.execute(
            """UPDATE jobs SET status='running', attempts=attempts+1, worker=?, lease_until=?, updated_at=?
               WHERE id=?""",
            (worker, iso(now + timedelta(seconds=spec.lease_s)), iso(now), chosen["id"]),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (chosen["id"],)).fetchone()
        conn.execute("COMMIT")
        return Job.from_row(row)
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _over_limit(kind: str, running: dict[str, int], limits: dict[str, int]) -> bool:
    for prefix, limit in limits.items():
        if kind.startswith(prefix):
            if sum(n for k, n in running.items() if k.startswith(prefix)) >= limit:
                return True
    return False


def complete(conn: sqlite3.Connection, job: Job, result: dict | None, *, clock: Clock = utcnow) -> None:
    now = iso(clock())
    conn.execute(
        """UPDATE jobs SET status='done', result=?, lease_until=NULL, last_error=NULL, updated_at=?, finished_at=?
           WHERE id=? AND status='running'""",
        (json.dumps(result or {}, ensure_ascii=False), now, now, job.id),
    )


def retry_later(conn: sqlite3.Connection, job: Job, e: RetryLater, *, clock: Clock = utcnow) -> None:
    now = clock()
    conn.execute(
        """UPDATE jobs SET status='queued', attempts=MAX(attempts-1, 0), run_after=?, lease_until=NULL,
                  result=COALESCE(?, result), last_error=NULL, updated_at=?
           WHERE id=? AND status='running'""",
        (iso(now + timedelta(seconds=max(1.0, e.delay_s))),
         json.dumps(e.result, ensure_ascii=False) if e.result is not None else None, iso(now), job.id),
    )


def fail(conn: sqlite3.Connection, job: Job, error: str, *, permanent: bool = False,
         clock: Clock = utcnow, rng: random.Random | None = None, result: dict | None = None) -> str:
    """Remet la tâche en file avec attente croissante, ou la passe en « dead ». Renvoie le statut."""
    now = clock()
    spec = HANDLERS.get(job.kind)
    if permanent or job.attempts >= job.max_attempts:
        conn.execute(
            """UPDATE jobs SET status='dead', last_error=?, lease_until=NULL, updated_at=?, finished_at=?,
                      result=COALESCE(?, result)
               WHERE id=?""",
            (error[-4000:], iso(now), iso(now),
             json.dumps(result, ensure_ascii=False) if result is not None else None, job.id),
        )
        _event(conn, now, "job_dead", f"{job.kind} #{job.id} abandonnée : {error.splitlines()[-1][:300]}")
        return "dead"
    backoff = spec.backoff_s if spec else (30, 120, 600)
    base = backoff[min(job.attempts - 1, len(backoff) - 1)]
    delay = base * (0.8 + 0.4 * (rng or random).random())
    conn.execute(
        """UPDATE jobs SET status='queued', last_error=?, run_after=?, lease_until=NULL, updated_at=?
           WHERE id=?""",
        (error[-4000:], iso(now + timedelta(seconds=delay)), iso(now), job.id),
    )
    return "queued"


def requeue_expired(conn: sqlite3.Connection, *, clock: Clock = utcnow) -> int:
    """Les tâches dont le bail a expiré (processus mort, Mac redémarré) repartent ou meurent."""
    now = clock()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status='running' AND lease_until < ?", (iso(now),)
    ).fetchall()
    for r in rows:
        fail(conn, Job.from_row(r), "bail expiré : le processus s'est arrêté pendant la tâche", clock=clock)
    return len(rows)


def cancel(conn: sqlite3.Connection, job_id: int, *, clock: Clock = utcnow) -> bool:
    now = iso(clock())
    cur = conn.execute(
        "UPDATE jobs SET status='cancelled', updated_at=?, finished_at=? WHERE id=? AND status IN ('queued','dead')",
        (now, now, job_id),
    )
    return cur.rowcount == 1


def retry(conn: sqlite3.Connection, job_id: int, *, clock: Clock = utcnow) -> bool:
    """Relance à la main une tâche « dead » (depuis le dashboard)."""
    now = iso(clock())
    cur = conn.execute(
        """UPDATE jobs SET status='queued', attempts=0, run_after=?, last_error=NULL, updated_at=?, finished_at=NULL
           WHERE id=? AND status IN ('dead','cancelled')""",
        (now, now, job_id),
    )
    return cur.rowcount == 1


def run_one(conn: sqlite3.Connection, config: Any, worker: str, *, clock: Clock = utcnow,
            services: dict[str, Any] | None = None, limits: dict[str, int] | None = None,
            kinds: list[str] | None = None) -> Job | None:
    """Exécute au plus une tâche. Renvoie la tâche traitée (ou None s'il n'y avait rien)."""
    job = claim(conn, worker, clock=clock, limits=limits, kinds=kinds)
    if job is None:
        return None
    spec = HANDLERS[job.kind]
    ctx = JobContext(conn=conn, config=config, job=job, clock=clock, services=services or {})
    try:
        result = spec.fn(ctx, job.payload)
        if conn.in_transaction:          # un handler qui a oublié de valider sa transaction
            conn.execute("COMMIT")
        complete(conn, job, result, clock=clock)
    except RetryLater as e:
        _rollback(conn)
        retry_later(conn, job, e, clock=clock)
    except Permanent as e:
        _rollback(conn)
        fail(conn, job, f"{type(e).__name__}: {e}", permanent=True, clock=clock, result=e.result)
    except Exception as e:  # noqa: BLE001 : une tâche ne doit jamais faire tomber le worker
        _rollback(conn)
        log.warning("tâche %s #%s en échec : %s", job.kind, job.id, e)
        fail(conn, job, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=6)}", clock=clock)
    return job


def _rollback(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.execute("ROLLBACK")


WATCHDOG_S = 300.0              # le chien de garde des modules passe toutes les 5 min


def run_worker(db_path: str, config: Any, stop: threading.Event, *, services: dict[str, Any] | None = None,
               threads: int = 3, poll_s: float = 2.0, limits: dict[str, int] | None = None,
               clock: Clock = utcnow, watchdog_s: float = WATCHDOG_S,
               watchdog: Callable[[sqlite3.Connection, Any, Clock], Any] | None = None) -> list[threading.Thread]:
    """Lance `threads` exécutants, chacun avec SA connexion SQLite. Renvoie les threads.

    Le premier exécutant remet en file les tâches au bail expiré et, au lancement puis toutes les `watchdog_s`
    secondes, passe le chien de garde (`watchdog`, par défaut modules.watchdog) : ce qui doit toujours tourner
    est relancé s'il manque (un tick de l'autopilote mort sans successeur, par exemple)."""
    from loopcast import db

    if watchdog is None:
        from loopcast import modules

        watchdog = modules.watchdog

    def loop(n: int) -> None:
        conn = None
        name = f"{socket.gethostname()}:{threading.get_ident()}:{n}"
        next_watch = time.monotonic()
        while not stop.is_set():
            try:
                if conn is None:             # base momentanément inaccessible : l'exécutant réessaie, il ne meurt pas
                    conn = db.connect(db_path)
                if n == 0:
                    if watchdog_s > 0 and time.monotonic() >= next_watch:
                        next_watch = time.monotonic() + watchdog_s
                        watchdog(conn, config, clock)
                    requeue_expired(conn, clock=clock)
                if run_one(conn, config, name, clock=clock, services=services, limits=limits) is None:
                    stop.wait(poll_s)
            except Exception:  # noqa: BLE001
                log.exception("exécutant %s : erreur inattendue", name)
                try:
                    if conn is not None:
                        _rollback(conn)      # jamais de transaction laissée ouverte : elle bloquerait toute la file
                except sqlite3.Error:
                    pass
                stop.wait(poll_s)

    out = []
    for n in range(threads):
        t = threading.Thread(target=loop, args=(n,), name=f"jobs-{n}", daemon=True)
        t.start()
        out.append(t)
    return out


def stats(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """{kind: {status: n}} pour le dashboard."""
    out: dict[str, dict[str, int]] = {}
    for r in conn.execute("SELECT kind, status, COUNT(*) n FROM jobs GROUP BY kind, status"):
        out.setdefault(r["kind"], {})[r["status"]] = r["n"]
    return out


def _event(conn: sqlite3.Connection, now: datetime, kind: str, message: str) -> None:
    conn.execute("INSERT INTO events(at, kind, message) VALUES (?,?,?)", (iso(now), kind, message))
