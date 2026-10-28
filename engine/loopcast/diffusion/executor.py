"""Exécution des posts dus (tâche diffusion.publish) : un à la fois par téléphone, 2 nouvelles tentatives
(10 puis 30 min, réglage diffusion.retry_minutes), « à finir » notifié, statut et journal par post.

Sûreté avant tout : on ne republie jamais un post dont on ne sait pas s'il est parti. Un post resté
« running » (processus arrêté pendant la publication) passe « à finir » avec une alerte : quelqu'un
regarde dans l'app et clique « Publié » ou « Échec ».
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Callable

from loopcast import jobs
from loopcast.diffusion import alerts, regulator
from loopcast.diffusion.publishers.base import PublishResult
from loopcast.diffusion.settings import HARD_CAP, DiffusionSettings, day_bounds, local_day
from loopcast.diffusion.store import (
    PENDING_STATUSES,
    get_account,
    get_content,
    get_post,
    iso,
    parse_dt,
    tx,
    update_post,
)

log = logging.getLogger(__name__)

TICK_HORIZON_MINUTES = 10           # on enfile les posts dus d'ici le prochain tour


def publish_key(post_id: int, attempts: int) -> str:
    return f"diffusion.publish:{post_id}:{attempts}"


def enqueue_due(conn: sqlite3.Connection, now: datetime, horizon_minutes: int = TICK_HORIZON_MINUTES) -> list[int]:
    """Une tâche diffusion.publish par post prévu d'ici `horizon_minutes`, à l'heure de son créneau."""
    rows = conn.execute(
        "SELECT id, attempts, scheduled_at, app_id FROM posts WHERE status='scheduled' AND scheduled_at <= ? "
        "ORDER BY scheduled_at, id", (iso(now + timedelta(minutes=horizon_minutes)),)).fetchall()
    out = []
    for r in rows:
        when = max(parse_dt(r["scheduled_at"]), now)
        jobs.enqueue(conn, "diffusion.publish", {"post_id": r["id"], "attempt": r["attempts"]},
                     key=publish_key(r["id"], r["attempts"]), app_id=r["app_id"], run_after=when, clock=lambda: now)
        out.append(r["id"])
    return out


def skip_missed(conn: sqlite3.Connection, s: DiffusionSettings, now: datetime) -> list[int]:
    """Créneaux passés depuis plus de `late_tolerance_minutes` sans publication (Mac éteint, file arrêtée) :
    on ne rattrape pas en rafale ; le post est annulé et son contenu redevient disponible."""
    limit = now - timedelta(minutes=s.late_tolerance_minutes)
    rows = conn.execute("SELECT id, account_id, scheduled_at FROM posts WHERE status='scheduled' AND scheduled_at < ?",
                        (iso(limit),)).fetchall()
    with tx(conn):
        for r in rows:
            when = parse_dt(r["scheduled_at"]).astimezone(s.tz).strftime("%d/%m %H:%M")
            update_post(conn, r["id"], now, f"créneau de {when} manqué (Mac éteint ou file de tâches arrêtée ?) : "
                                            "rien n'est parti, le contenu sera replanifié", status="skipped")
            alerts.event(conn, now, "diffusion.skipped", f"post #{r['id']} : créneau de {when} manqué", r["account_id"])
    return [r["id"] for r in rows]


def recover_stuck(conn: sqlite3.Connection, s: DiffusionSettings, now: datetime,
                  notifier: alerts.Notifier | None = None) -> list[int]:
    """Posts restés « running » : on ignore s'ils sont partis, donc jamais de nouvelle tentative automatique."""
    limit = now - timedelta(minutes=s.running_timeout_minutes)
    rows = conn.execute("SELECT id, account_id FROM posts WHERE status='running' AND COALESCE(updated_at, '') < ?",
                        (iso(limit),)).fetchall()
    with tx(conn):
        for r in rows:
            update_post(conn, r["id"], now, "publication interrompue (redémarrage ?) : vérifier dans l'app si le post "
                                            "est en ligne, puis cliquer « Publié » ou « Échec »", status="needs_human")
            alerts.alert(conn, now, "diffusion.needs_human",
                         f"{r['account_id']} : post #{r['id']} interrompu en pleine publication, à vérifier dans l'app",
                         account_id=r["account_id"], notify_settings=s.notify, notifier=notifier)
    return [r["id"] for r in rows]


def publish_post(conn: sqlite3.Connection, config, post_id: int, *, publishers, clock: Callable[[], datetime],
                 settings: DiffusionSettings | None = None, notifier: alerts.Notifier | None = None,
                 attempt: int | None = None) -> dict:
    """Publie un post s'il est dû. Lève jobs.RetryLater s'il est trop tôt ou si le téléphone est occupé."""
    s = settings or DiffusionSettings.from_config(config)
    now = clock()
    with tx(conn):
        post = get_post(conn, post_id)
        if post is None:
            raise jobs.Permanent(f"post #{post_id} introuvable")
        if post.status != "scheduled":
            return {"post_id": post_id, "skipped": f"statut {post.status}"}
        if attempt is not None and attempt != post.attempts:
            return {"post_id": post_id, "skipped": "tentative déjà traitée"}
        if post.scheduled_at - now > timedelta(seconds=60):
            raise jobs.RetryLater((post.scheduled_at - now).total_seconds(), "pas encore l'heure du créneau")
        refusal = _refusal(conn, s, post, now, notifier)
        if refusal:
            update_post(conn, post_id, now, f"annulé : {refusal}", status="skipped")
            alerts.event(conn, now, "diffusion.skipped", f"post #{post_id} annulé : {refusal}", post.account_id)
            return {"post_id": post_id, "status": "skipped", "log": refusal}
        account = get_account(conn, post.account_id)
        busy = conn.execute(
            """SELECT id FROM posts WHERE status = 'running' AND id != ?
               AND substr(account_id, 1, instr(account_id, ':') - 1) = ? LIMIT 1""",
            (post_id, account.device)).fetchone()
        if busy:
            raise jobs.RetryLater(60, f"le téléphone {account.device} publie déjà le post #{busy['id']}")
        content = get_content(conn, post.content_id)
        missing = [str(p) for p in content.media if not p.exists()]
        if not content.media or missing:
            reason = f"fichier introuvable : {', '.join(missing) or 'aucun fichier rendu'}"
            update_post(conn, post_id, now, f"échec : {reason}", status="failed")
            alerts.alert(conn, now, "diffusion.failed", f"{account.id} : post #{post_id} impossible, {reason}",
                         account_id=account.id, notify_settings=s.notify, notifier=notifier)
            return {"post_id": post_id, "status": "failed", "log": reason}
        publisher = publishers.for_account(account)
        attempt_no = post.attempts + 1
        update_post(conn, post_id, now, f"tentative {attempt_no}/{s.max_attempts} ({publisher.name})",
                    status="running", attempts=attempt_no, channel=account.channel)

    # Hors transaction : un publisher peut prendre plusieurs minutes (iPhone, API qui calcule).
    try:
        result = publisher.publish(account, content, content.media)
    except Exception as e:  # noqa: BLE001 : un publisher qui plante = un échec du post, pas de la tâche
        log.warning("publication du post #%s : %s", post_id, e)
        result = PublishResult.failed(f"{type(e).__name__}: {e}")
    return _apply(conn, s, post_id, account, publisher.name, attempt_no, result, clock(), notifier)


def _refusal(conn, s: DiffusionSettings, post, now: datetime, notifier) -> str | None:
    """Pourquoi ce post ne doit plus partir (ou None)."""
    account = get_account(conn, post.account_id)
    if account is None or not account.active:
        return "compte inactif ou retiré de devices.yaml"
    st = regulator.current_state(conn, account, s, now, notifier=notifier)
    if st.paused(now) or st.state in ("paused", "inactive", "not_started"):
        return f"compte {regulator.STATE_LABELS.get(st.state, st.state)} ({st.note})"
    content = get_content(conn, post.content_id)
    if content is None:
        return "contenu supprimé"
    if content.status != "approved":
        return f"contenu retiré de la diffusion (statut {content.status})"
    start, end = day_bounds(local_day(now, s.tz), s.tz)
    marks = ",".join("?" * len(PENDING_STATUSES))
    done = conn.execute(
        f"""SELECT COUNT(*) FROM posts WHERE account_id=? AND status IN ({marks})
            AND COALESCE(posted_at, scheduled_at) >= ? AND COALESCE(posted_at, scheduled_at) < ?""",
        (account.id, *PENDING_STATUSES, iso(start), iso(end))).fetchone()[0]
    if done >= HARD_CAP:
        return f"plafond de {HARD_CAP} posts par jour atteint"
    if done >= st.quota:
        return f"quota du jour atteint ({st.quota})"
    return None


def _apply(conn, s: DiffusionSettings, post_id: int, account, publisher_name: str, attempt: int,
           result: PublishResult, now: datetime, notifier) -> dict:
    out = {"post_id": post_id, "status": result.status, "attempt": attempt, "log": result.log}
    with tx(conn):
        if result.status == "posted":
            update_post(conn, post_id, now, f"publié ({publisher_name}) : {result.log}", status="posted",
                        posted_at=now, external_id=result.external_id, url=result.url)
            alerts.event(conn, now, "diffusion.posted", f"{account.id} : post #{post_id} publié", account.id)
        elif result.status == "needs_human":
            update_post(conn, post_id, now, f"à finir par un humain : {result.log}", status="needs_human",
                        external_id=result.external_id)
            first = result.log.splitlines()[0] if result.log else ""
            alerts.alert(conn, now, "diffusion.needs_human",
                         f"{account.id} : post #{post_id} à finir sur le téléphone {account.device}. {first}",
                         account_id=account.id, notify_settings=s.notify, notifier=notifier)
        elif result.retryable and attempt < s.max_attempts:
            delay = s.retry_minutes[attempt - 1]
            again = now + timedelta(minutes=delay)
            update_post(conn, post_id, now,
                        f"échec (tentative {attempt}/{s.max_attempts}) : {result.log} ; nouvelle tentative à "
                        f"{again.astimezone(s.tz):%H:%M}", status="scheduled", scheduled_at=again)
            jobs.enqueue(conn, "diffusion.publish", {"post_id": post_id, "attempt": attempt},
                         key=publish_key(post_id, attempt), app_id=account.app_id, run_after=again, clock=lambda: now)
            alerts.event(conn, now, "diffusion.retry",
                         f"{account.id} : post #{post_id} en échec ({result.log}), nouvel essai dans {delay} min",
                         account.id)
            out["status"], out["retry_at"] = "scheduled", iso(again)
        else:
            update_post(conn, post_id, now, f"échec définitif après {attempt} tentative(s) : {result.log}",
                        status="failed")
            alerts.alert(conn, now, "diffusion.failed",
                         f"{account.id} : post #{post_id} en échec après {attempt} tentative(s) : {result.log}",
                         account_id=account.id, notify_settings=s.notify, notifier=notifier)
    return out


# --- Décisions humaines (dashboard, CLI) ------------------------------------------------------------------------

class PostStateError(ValueError):
    """Action impossible dans l'état actuel du post (message pour l'équipe)."""


def mark_posted(conn: sqlite3.Connection, post_id: int, now: datetime, *, external_id: str | None = None,
                url: str | None = None, note: str = "") -> dict:
    """« Publié » : une personne a publié (ou vérifié) le post dans l'app."""
    with tx(conn):
        post = get_post(conn, post_id)
        if post is None:
            raise KeyError(f"post #{post_id} introuvable")
        if post.status not in ("needs_human", "running", "failed", "scheduled"):
            raise PostStateError(f"post #{post_id} : statut « {post.status} », rien à marquer comme publié")
        update_post(conn, post_id, now, "marqué « Publié » par l'équipe" + (f" : {note}" if note else ""),
                    status="posted", posted_at=now, external_id=external_id or post.external_id, url=url or post.url)
        alerts.event(conn, now, "diffusion.posted", f"{post.account_id} : post #{post_id} publié (à la main)",
                     post.account_id)
    return get_post(conn, post_id).to_dict()


def mark_failed(conn: sqlite3.Connection, post_id: int, now: datetime, *, note: str = "") -> dict:
    """« Échec » : la personne n'a pas pu publier. Le contenu reste réservé à ce compte (pas de reprise auto)."""
    with tx(conn):
        post = get_post(conn, post_id)
        if post is None:
            raise KeyError(f"post #{post_id} introuvable")
        if post.status not in ("needs_human", "running", "scheduled"):
            raise PostStateError(f"post #{post_id} : statut « {post.status} », impossible de le marquer en échec")
        update_post(conn, post_id, now, "marqué « Échec » par l'équipe" + (f" : {note}" if note else ""),
                    status="failed")
        alerts.event(conn, now, "diffusion.failed", f"{post.account_id} : post #{post_id} en échec (à la main)",
                     post.account_id)
    return get_post(conn, post_id).to_dict()
