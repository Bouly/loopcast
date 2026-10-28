"""Métriques (REPRISE §5.9) et boucle des gagnants (§5.10).

- Toutes les `metrics_every_hours` (tâche diffusion.metrics) : les vues des posts publiés depuis
  `diffusion.metrics_days` jours, via le publisher de chaque compte. Saisie manuelle en secours
  (route, ou `python -m loopcast diffusion metrics set <post_id> --views 1234`).
- Gagnant = top 20 % des vues d'un compte sur 14 jours, parmi au moins 5 posts jugés (publiés depuis plus
  de 24 h), et au-dessus de la médiane. Pour chaque nouveau gagnant : tâche ideas.variations
  (payload {content_id}), traitée par le module strategy, une seule fois par contenu.
"""

from __future__ import annotations

import logging
import sqlite3
import statistics
from datetime import datetime, timedelta

from loopcast import accounts, jobs
from loopcast.diffusion import alerts
from loopcast.diffusion.settings import DiffusionSettings
from loopcast.diffusion.store import get_post, iso, tx, update_post

log = logging.getLogger(__name__)


def metrics_key(now: datetime, every_hours: int) -> str:
    hour = now.hour - now.hour % every_hours
    return f"diffusion.metrics:{now:%Y-%m-%d}T{hour:02d}"


def enqueue_metrics(conn: sqlite3.Connection, s: DiffusionSettings, now: datetime) -> int:
    """Une collecte par tranche de `metrics_every_hours` (clé d'idempotence)."""
    return jobs.enqueue(conn, "diffusion.metrics", {}, key=metrics_key(now, s.metrics_every_hours),
                        clock=lambda: now)


def fetch(conn: sqlite3.Connection, config, now: datetime, *, publishers,
          settings: DiffusionSettings | None = None) -> dict:
    """Relève les vues de chaque compte. Un compte en erreur n'empêche pas les autres."""
    s = settings or DiffusionSettings.from_config(config)
    report = {"updated": 0, "accounts": {}, "errors": []}
    for account in accounts.list_accounts(conn, active_only=False):
        rows = conn.execute(
            """SELECT id, external_id FROM posts WHERE account_id=? AND status='posted' AND external_id IS NOT NULL
               AND posted_at >= ?""", (account.id, iso(now - timedelta(days=s.metrics_days)))).fetchall()
        if not rows:
            continue
        ids = {r["external_id"]: r["id"] for r in rows}
        try:
            got = publishers.for_account(account).fetch_metrics(account, list(ids))
        except Exception as e:  # noqa: BLE001
            log.warning("métriques de %s : %s", account.id, e)
            report["errors"].append(f"{account.id} : {type(e).__name__}: {e}")
            alerts.event(conn, now, "diffusion.metrics_error", f"{account.id} : vues illisibles ({e})", account.id)
            continue
        with tx(conn):
            for external_id, m in got.items():
                if external_id not in ids or m.views is None:
                    continue
                conn.execute(
                    """UPDATE posts SET views=?, likes=COALESCE(?, likes), comments=COALESCE(?, comments),
                              shares=COALESCE(?, shares), metrics_at=?, updated_at=? WHERE id=?""",
                    (int(m.views), m.likes, m.comments, m.shares, iso(now), iso(now), ids[external_id]))
                report["updated"] += 1
        report["accounts"][account.id] = len(got)
    return report


def set_manual(conn: sqlite3.Connection, post_id: int, now: datetime, *, views: int, likes: int | None = None) -> dict:
    """Vues saisies à la main (le post doit être marqué « Publié »)."""
    if views < 0 or (likes is not None and likes < 0):
        raise ValueError("les vues et les j'aime sont des nombres positifs")
    with tx(conn):
        post = get_post(conn, post_id)
        if post is None:
            raise KeyError(f"post #{post_id} introuvable")
        if post.status != "posted":
            raise ValueError(f"post #{post_id} : statut « {post.status} » ; le marquer d'abord « Publié »")
        update_post(conn, post_id, now, f"vues saisies à la main : {views}" + (f", {likes} j'aime" if likes is not None
                                                                              else ""),
                    views=int(views), likes=likes if likes is not None else post.likes, metrics_at=now)
    return get_post(conn, post_id).to_dict()


def detect_winners(conn: sqlite3.Connection, config, now: datetime, *, settings: DiffusionSettings | None = None,
                   account_ids: list[str] | None = None) -> list[dict]:
    """Marque les nouveaux gagnants et demande leurs variations (ideas.variations)."""
    s = settings or DiffusionSettings.from_config(config)
    since = iso(now - timedelta(days=s.winners_window_days))
    until = iso(now - timedelta(hours=s.metrics_min_age_hours))
    found = []
    for account in accounts.list_accounts(conn, active_only=False):
        if account_ids and account.id not in account_ids:
            continue
        rows = conn.execute(
            """SELECT id, content_id, views, winner_at, app_id FROM posts WHERE account_id=? AND status='posted'
               AND views IS NOT NULL AND posted_at >= ? AND posted_at <= ? ORDER BY views DESC, posted_at, id""",
            (account.id, since, until)).fetchall()
        if len(rows) < s.winners_min_posts:
            continue
        median = statistics.median(r["views"] for r in rows)
        top = max(1, int(len(rows) * s.winners_top_share))
        for rank, r in enumerate(rows[:top], start=1):
            if r["views"] <= median or r["winner_at"] is not None:
                continue
            reason = (f"gagnant : {r['views']} vues, n° {rank} sur {len(rows)} posts de {account.id} "
                      f"en {s.winners_window_days} jours (médiane {int(median)}) → variations demandées")
            with tx(conn):
                update_post(conn, r["id"], now, reason, winner_at=now)
                jobs.enqueue(conn, "ideas.variations", {"content_id": r["content_id"]},
                             key=f"ideas.variations:{r['content_id']}", app_id=r["app_id"] or account.app_id,
                             clock=lambda: now)
                alerts.event(conn, now, "diffusion.winner", f"{account.id} : contenu {r['content_id']} — {reason}",
                             account.id)
            found.append({"post_id": r["id"], "content_id": r["content_id"], "account_id": account.id,
                          "views": r["views"]})
    return found


def run(conn: sqlite3.Connection, config, now: datetime, *, publishers,
        settings: DiffusionSettings | None = None) -> dict:
    """La tâche diffusion.metrics : relevé des vues puis boucle des gagnants."""
    s = settings or DiffusionSettings.from_config(config)
    report = fetch(conn, config, now, publishers=publishers, settings=s)
    report["winners"] = detect_winners(conn, config, now, settings=s)
    return report
