"""Routes /api/diffusion : calendrier, comptes, posts « à finir », vues, pause, tick.

Les lectures ne recalculent rien (le tick le fait toutes les 10 min) ; les actions de l'équipe passent
par les mêmes fonctions que l'autopilote et préviennent le front (deps.publish, événement « diffusion »).
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from loopcast import accounts
from loopcast.api import deps
from loopcast.diffusion import autopilot, executor, metrics, planner, regulator
from loopcast.diffusion.settings import HARD_CAP, DiffusionSettings, day_bounds, local_day
from loopcast.diffusion.store import POST_SELECT, Post, get_account, get_content, get_post, get_state, iso

router = APIRouter(prefix="/api/diffusion", tags=["diffusion"])

POST_STATUSES = ("scheduled", "running", "needs_human", "posted", "failed", "skipped")
WHEN = "COALESCE(p.posted_at, p.scheduled_at)"        # le jour d'un post : sa publication, sinon son créneau


class PostedBody(BaseModel):
    external_id: str | None = Field(None, max_length=200, description="Id du post sur la plateforme, s'il est connu")
    url: str | None = Field(None, max_length=500)
    note: str = Field("", max_length=500)


class FailedBody(BaseModel):
    note: str = Field("", max_length=500)


class MetricsBody(BaseModel):
    views: int = Field(ge=0)
    likes: int | None = Field(None, ge=0)


class PauseBody(BaseModel):
    reason: str = Field("", max_length=300)
    hours: int | None = Field(None, ge=1, le=24 * 90, description="Absent = jusqu'à la reprise")


def _settings(request: Request) -> DiffusionSettings:
    return DiffusionSettings.from_config(deps.config(request))


def _publishers(request: Request):
    publishers, _ = autopilot.services_of(deps.config(request), deps.services(request))
    return publishers


def _post_view(conn, post: Post, s: DiffusionSettings, with_content: bool = False) -> dict:
    d = post.to_dict()
    when = post.posted_at or post.scheduled_at
    if when is not None:
        local = when.astimezone(s.tz)
        d["local_date"], d["local_time"] = local.date().isoformat(), local.strftime("%H:%M")
    if with_content:
        content = get_content(conn, post.content_id)
        d["content"] = None if content is None else {
            "id": content.id, "format": content.format, "kind": content.kind, "lang": content.lang,
            "text": content.post_text(), "files": content.files, "ai_label": content.ai_label,
        }
    return d


def _account_view(conn, account: accounts.Account, s: DiffusionSettings, now, publishers) -> dict:
    today = local_day(now, s.tz)
    start, end = day_bounds(today, s.tz)
    st = get_state(conn, account.id)
    counts = {r[0]: r[1] for r in conn.execute(
        """SELECT status, COUNT(*) FROM posts WHERE account_id=? AND COALESCE(posted_at, scheduled_at) >= ?
           AND COALESCE(posted_at, scheduled_at) < ? GROUP BY status""", (account.id, iso(start), iso(end)))}
    recent = [Post.from_row(r) for r in conn.execute(
        POST_SELECT + " WHERE p.account_id=? AND p.status='posted' ORDER BY p.posted_at DESC, p.id DESC LIMIT 5",
        (account.id,))]
    publisher = publishers.for_account(account)
    paused = st is not None and st.paused(now)
    return {
        "id": account.id, "device": account.device, "platform": account.platform, "handle": account.handle,
        "channel": account.channel, "publisher": publisher.name, "reason": getattr(publisher, "reason", "") or "",
        "app_id": account.app_id, "lang": account.lang, "active": account.active, "created": account.created,
        "age_days": account.age_days(today),
        "quota": min(st.quota, HARD_CAP) if st else None, "target": st.target if st else None,
        "state": st.state if st else None,
        "state_label": regulator.STATE_LABELS.get(st.state, st.state) if st else "pas encore calculé",
        "note": st.note if st else "", "ratio": st.ratio if st else None,
        "paused": paused, "paused_until": iso(st.paused_until) if paused else None,
        "paused_reason": st.paused_reason if paused else None,
        "stale": st is None or st.day != today.isoformat(),
        "today": {"date": today.isoformat(), **{k: counts.get(k, 0) for k in POST_STATUSES}},
        "stock": len(planner.candidates(conn, account)),       # prêtes à publier
        "to_review": planner.to_review(conn, account),          # à valider d'abord
        "recent": [_post_view(conn, p, s) for p in recent],
    }


def _account_or_404(conn, account_id: str) -> accounts.Account:
    account = get_account(conn, account_id)
    if account is None:
        raise HTTPException(404, "compte inconnu")
    return account


# --- Lecture ---------------------------------------------------------------------------------------------------

@router.get("/calendar")
def calendar(request: Request, start: date | None = None, days: int = 7, account_id: str | None = None,
             app_id: str | None = None, device: str | None = None, status: str | None = None):
    """Les posts par compte et par jour local. `status` : liste séparée par des virgules (défaut : tout sauf
    les posts annulés)."""
    conn, s, now = deps.conn(request), _settings(request), deps.clock(request)
    days = max(1, min(days, 62))
    first = start or local_day(now, s.tz)
    window_start, _ = day_bounds(first, s.tz)
    _, window_end = day_bounds(first + timedelta(days=days - 1), s.tz)
    sql = POST_SELECT + f" WHERE {WHEN} >= ? AND {WHEN} < ?"
    args: list = [iso(window_start), iso(window_end)]
    statuses = [x.strip() for x in status.split(",") if x.strip()] if status else []
    if statuses:
        sql += f" AND p.status IN ({','.join('?' * len(statuses))})"
        args += statuses
    else:
        sql += " AND p.status != 'skipped'"
    for col, value in (("p.account_id", account_id), ("p.app_id", app_id)):
        if value:
            sql += f" AND {col}=?"
            args.append(value)
    rows = [Post.from_row(r) for r in conn.execute(sql + " ORDER BY COALESCE(p.posted_at, p.scheduled_at), p.id", args)]

    by_account: dict[str, dict] = {}
    for account in accounts.list_accounts(conn, app_id=app_id):
        if (account_id and account.id != account_id) or (device and account.device != device):
            continue
        st = get_state(conn, account.id)
        by_account[account.id] = {"id": account.id, "device": account.device, "platform": account.platform,
                                  "handle": account.handle, "quota": st.quota if st else None,
                                  "days": {(first + timedelta(days=i)).isoformat(): [] for i in range(days)}}
    for post in rows:
        entry = by_account.get(post.account_id)
        if entry is None:
            continue
        view = _post_view(conn, post, s)
        entry["days"].setdefault(view["local_date"], []).append(view)
    return {"start": first.isoformat(), "days": days, "timezone": s.timezone, "accounts": list(by_account.values())}


@router.get("/accounts")
def list_accounts(request: Request, app_id: str | None = None):
    conn, s, now = deps.conn(request), _settings(request), deps.clock(request)
    publishers = _publishers(request)
    return [_account_view(conn, a, s, now, publishers) for a in accounts.list_accounts(conn, app_id=app_id)]


@router.get("/accounts/{account_id}")
def account_detail(account_id: str, request: Request):
    conn, s, now = deps.conn(request), _settings(request), deps.clock(request)
    account = _account_or_404(conn, account_id)
    view = _account_view(conn, account, s, now, _publishers(request))
    view["posts"] = [_post_view(conn, Post.from_row(r), s) for r in conn.execute(
        POST_SELECT + " WHERE p.account_id=? ORDER BY COALESCE(p.posted_at, p.scheduled_at) DESC, p.id DESC LIMIT 30",
        (account_id,))]
    return view


@router.get("/posts")
def list_posts(request: Request, status: str | None = None, account_id: str | None = None, limit: int = 50):
    """`status=needs_human` : l'écran « À finir » (avec la légende et les fichiers à publier)."""
    conn, s = deps.conn(request), _settings(request)
    sql, args = POST_SELECT + " WHERE 1=1", []
    if status:
        statuses = [x.strip() for x in status.split(",") if x.strip()]
        sql += f" AND p.status IN ({','.join('?' * len(statuses))})"
        args += statuses
    if account_id:
        sql += " AND p.account_id=?"
        args.append(account_id)
    sql += " ORDER BY COALESCE(p.posted_at, p.scheduled_at) DESC, p.id DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    return [_post_view(conn, Post.from_row(r), s, with_content=True) for r in conn.execute(sql, args)]


@router.get("/posts/{post_id}")
def post_detail(post_id: int, request: Request):
    conn = deps.conn(request)
    post = get_post(conn, post_id)
    if post is None:
        raise HTTPException(404, "post inconnu")
    return _post_view(conn, post, _settings(request), with_content=True)


@router.get("/events")
def events(request: Request, account_id: str | None = None, limit: int = 100):
    sql, args = "SELECT * FROM events WHERE kind LIKE 'diffusion.%'", []
    if account_id:
        sql += " AND account_id=?"
        args.append(account_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    return [dict(r) for r in deps.conn(request).execute(sql, args)]


@router.get("/status")
def status(request: Request):
    conn, s, now = deps.conn(request), _settings(request), deps.clock(request)
    start, end = day_bounds(local_day(now, s.tz), s.tz)
    nxt = conn.execute("SELECT MIN(run_after) FROM jobs WHERE kind='diffusion.tick' AND status='queued'").fetchone()[0]
    last = conn.execute("""SELECT status, finished_at, last_error FROM jobs WHERE kind='diffusion.tick'
                           AND status IN ('done', 'dead') ORDER BY finished_at DESC LIMIT 1""").fetchone()
    counts = {r[0]: r[1] for r in conn.execute(
        """SELECT status, COUNT(*) FROM posts WHERE COALESCE(posted_at, scheduled_at) >= ?
           AND COALESCE(posted_at, scheduled_at) < ? GROUP BY status""", (iso(start), iso(end)))}
    waiting = conn.execute("SELECT COUNT(*) FROM posts WHERE status='needs_human'").fetchone()[0]
    return {
        "now": iso(now), "timezone": s.timezone, "dry_run": s.dry_run, "hard_cap": HARD_CAP,
        "next_tick": nxt, "last_tick": dict(last) if last else None,
        "today": counts, "needs_human": waiting,
    }


# --- Actions de l'équipe -----------------------------------------------------------------------------------------

@router.post("/posts/{post_id}/posted")
def mark_posted(post_id: int, request: Request, body: PostedBody | None = None):
    body = body or PostedBody()
    try:
        post = executor.mark_posted(deps.conn(request), post_id, deps.clock(request), external_id=body.external_id,
                                    url=body.url, note=body.note)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from e
    except executor.PostStateError as e:
        raise HTTPException(409, str(e)) from e
    deps.publish(request, "diffusion", {"post": post_id, "status": "posted"})
    return post


@router.post("/posts/{post_id}/failed")
def mark_failed(post_id: int, request: Request, body: FailedBody | None = None):
    body = body or FailedBody()
    try:
        post = executor.mark_failed(deps.conn(request), post_id, deps.clock(request), note=body.note)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from e
    except executor.PostStateError as e:
        raise HTTPException(409, str(e)) from e
    deps.publish(request, "diffusion", {"post": post_id, "status": "failed"})
    return post


@router.post("/posts/{post_id}/metrics")
def set_metrics(post_id: int, body: MetricsBody, request: Request):
    conn, now = deps.conn(request), deps.clock(request)
    try:
        post = metrics.set_manual(conn, post_id, now, views=body.views, likes=body.likes)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    metrics.detect_winners(conn, deps.config(request), now, account_ids=[post["account_id"]])
    deps.publish(request, "diffusion", {"post": post_id, "views": body.views})
    return get_post(conn, post_id).to_dict()


@router.post("/accounts/{account_id}/pause")
def pause_account(account_id: str, request: Request, body: PauseBody | None = None):
    body = body or PauseBody()
    conn, s, now = deps.conn(request), _settings(request), deps.clock(request)
    account = _account_or_404(conn, account_id)
    regulator.pause(conn, deps.config(request), account_id, now, reason=body.reason, hours=body.hours, settings=s)
    deps.publish(request, "diffusion", {"account": account_id, "state": "paused"})
    return _account_view(conn, account, s, now, _publishers(request))


@router.post("/accounts/{account_id}/resume")
def resume_account(account_id: str, request: Request):
    conn, s, now = deps.conn(request), _settings(request), deps.clock(request)
    account = _account_or_404(conn, account_id)
    publishers = _publishers(request)
    regulator.resume(conn, deps.config(request), account_id, now, settings=s)
    planner.plan_day(conn, deps.config(request), now, publishers=publishers, settings=s, devices=[account.device])
    deps.publish(request, "diffusion", {"account": account_id, "state": "resumed"})
    return _account_view(conn, account, s, now, publishers)


@router.post("/tick")
def run_tick(request: Request):
    """Un tour de l'autopilote tout de suite (régulateur recalculé) ; les publications partent par la file."""
    report = autopilot.run_tick(deps.conn(request), deps.config(request), deps.clock(request),
                                services=deps.services(request), force=True)
    deps.publish(request, "diffusion", {"tick": report["at"], "errors": len(report["errors"])})
    return report
