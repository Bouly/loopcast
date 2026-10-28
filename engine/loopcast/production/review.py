"""Décisions humaines sur un contenu (file de validation, CLI) : valider, rejeter, corriger la légende, relancer.

Un rejet marque l'idée (`ideas.status = rejected`) et garde la note dans `content.review_note` :
`rejection_notes(conn, app_id)` les rend au module strategy pour le prochain lot d'idées.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from loopcast import jobs
from loopcast.jobs import iso
from loopcast.production import store
from loopcast.production.formats_extra import AI_KINDS
from loopcast.production.store import tx

CAPTION_MAX = 2200                 # TikTok et Instagram
HASHTAGS_MAX = 30                  # Instagram
NOTE_MAX = 1000
_TAG = re.compile(r"^#?[^\s#]{1,100}$")
LOCKED_POSTS = ("scheduled", "running", "needs_human", "posted")


class ReviewError(Exception):
    """Action impossible dans l'état actuel (message pour l'équipe ; `status` = code HTTP)."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _content(conn: sqlite3.Connection, content_id: str) -> sqlite3.Row:
    row = store.get_content(conn, content_id)
    if row is None:
        raise ReviewError("contenu introuvable", 404)
    return row


def _posts(conn: sqlite3.Connection, content_id: str) -> list[str]:
    marks = ",".join("?" * len(LOCKED_POSTS))
    return [r["status"] for r in conn.execute(
        f"SELECT status FROM posts WHERE content_id=? AND status IN ({marks})", (content_id, *LOCKED_POSTS))]


def approve(conn: sqlite3.Connection, content_id: str, now: datetime, note: str | None = None) -> sqlite3.Row:
    row = _content(conn, content_id)
    if row["status"] == "approved":
        return row
    if row["status"] != "rendered":
        raise ReviewError(f"impossible de valider un contenu au statut « {row['status']} »")
    if not store.qa_ok(row):
        raise ReviewError("contrôle qualité pas encore réussi : rien de non contrôlé n'est validé")
    with tx(conn):
        store.set_content(conn, content_id, now, status="approved", approved_at=iso(now),
                          review_note=(note or "").strip()[:NOTE_MAX] or row["review_note"])
        store.event(conn, now, "content.approved", f"{content_id} : validé", row["account_id"])
    return _content(conn, content_id)


def reject(conn: sqlite3.Connection, content_id: str, now: datetime, note: str = "") -> sqlite3.Row:
    row = _content(conn, content_id)
    if row["status"] == "rejected":
        return row
    if row["status"] in store.ACTIVE:
        raise ReviewError("production en cours : attendre la fin du rendu")
    if _posts(conn, content_id):
        raise ReviewError("déjà planifié ou publié : annuler la publication d'abord")
    note = (note or "").strip()[:NOTE_MAX]
    with tx(conn):
        store.set_content(conn, content_id, now, status="rejected", review_note=note or None, approved_at=None)
        store.set_idea(conn, row["idea_id"], now, "rejected", None)
        store.event(conn, now, "content.rejected", f"{content_id} : rejeté" + (f" ({note})" if note else ""),
                    row["account_id"])
    return _content(conn, content_id)


def edit(conn: sqlite3.Connection, content_id: str, now: datetime, caption: str | None = None,
         hashtags: list[str] | None = None) -> sqlite3.Row:
    row = _content(conn, content_id)
    if any(s in ("running", "posted") for s in _posts(conn, content_id)):
        raise ReviewError("déjà publié : la légende ne peut plus changer")
    fields: dict = {}
    if caption is not None:
        if len(caption) > CAPTION_MAX:
            raise ReviewError(f"légende de {len(caption)} caractères, {CAPTION_MAX} au plus", 422)
        fields["caption"] = caption.strip()
    if hashtags is not None:
        clean: list[str] = []
        for tag in hashtags:
            tag = str(tag).strip()
            if not tag:
                continue
            if not _TAG.match(tag):
                raise ReviewError(f"hashtag invalide : « {tag} » (un seul mot, sans espace)", 422)
            tag = "#" + tag.lstrip("#")
            if tag.lower() not in (t.lower() for t in clean):
                clean.append(tag)
        if len(clean) > HASHTAGS_MAX:
            raise ReviewError(f"{len(clean)} hashtags, {HASHTAGS_MAX} au plus", 422)
        fields["hashtags"] = clean
    if fields:
        with tx(conn):
            store.set_content(conn, content_id, now, **fields)
            store.event(conn, now, "content.edited", f"{content_id} : légende modifiée", row["account_id"])
    return _content(conn, content_id)


def relaunch(conn: sqlite3.Connection, content_id: str, now: datetime, regenerate: bool = False) -> int:
    """Nouvelle production du même contenu ; `regenerate` refait aussi les plans IA (nouvelle dépense).
    Renvoie l'id de la tâche content.produce."""
    row = _content(conn, content_id)
    if row["status"] == "approved":
        raise ReviewError("contenu déjà validé : le rejeter d'abord")
    if store.in_flight(conn, content_id, row["idea_id"]):
        raise ReviewError("production en cours : attendre qu'elle se termine")
    run = (row["run"] or 0) + 1
    idea = store.get_idea(conn, row["idea_id"]) if row["idea_id"] else None
    if idea is None:
        raise ReviewError("idée introuvable : impossible de relancer", 404)
    data = store.loads(idea["idea"], {})
    shots = (data.get("shots") if isinstance(data, dict) else None) or []
    ai_shots = [i for i, s in enumerate(shots) if isinstance(s, dict) and s.get("kind") in AI_KINDS]
    with tx(conn):
        store.set_content(conn, content_id, now, status="draft", run=run, auto_retries=0, error=None, qa=None,
                          files=None, duration_s=None, approved_at=None, review_note=None)
        store.set_idea(conn, row["idea_id"], now, "producing")
        if not regenerate:
            # Les générations abandonnées repartent (sinon la production échouerait aussitôt).
            for job in store.content_jobs(conn, content_id, row["idea_id"], ("dead", "cancelled")):
                if job["kind"] == "video.generate":
                    jobs.retry(conn, job["id"], clock=lambda: now)
        job_id = jobs.enqueue(conn, "content.produce",
                              {"idea_id": row["idea_id"], "run": run, "regenerate": ai_shots if regenerate else []},
                              key=f"content.produce:{content_id}:r{run}", app_id=row["app_id"], clock=lambda: now)
        store.event(conn, now, "content.relaunched", f"{content_id} : production {run} relancée"
                    + (" avec régénération des plans IA" if regenerate and ai_shots else ""), row["account_id"])
    return job_id


def rejection_notes(conn: sqlite3.Connection, app_id: str, limit: int = 20) -> list[dict]:
    """Les derniers rejets commentés d'une app, pour le prochain lot d'idées (module strategy)."""
    rows = conn.execute(
        """SELECT c.id, c.format, c.lang, c.account_id, c.review_note, c.updated_at, i.hook, i.pillar
           FROM content c LEFT JOIN ideas i ON i.id = c.idea_id
           WHERE c.app_id=? AND c.status='rejected' AND COALESCE(c.review_note, '') <> ''
           ORDER BY c.updated_at DESC LIMIT ?""", (app_id, limit)).fetchall()
    return [{"content_id": r["id"], "format": r["format"], "lang": r["lang"], "account_id": r["account_id"],
             "hook": r["hook"], "pillar": r["pillar"], "note": r["review_note"], "at": r["updated_at"]} for r in rows]
