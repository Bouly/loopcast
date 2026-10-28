"""Routes /api/providers : fournisseurs et modèles actifs, estimation, budget, génération de test.

    GET  /api/providers            modèles vidéo et image, prix, fournisseur réel ou faux (et pourquoi)
    POST /api/providers/estimate   {kind, request, app_id?} → modèle choisi, prix, avis du budget, alternatives
    GET  /api/providers/budget     dépensé aujourd'hui / ce mois (costs.summary) + vidéo, image, en cours
    POST /api/providers/test       {kind, request, confirm?} → enfile une génération de test (payante : confirm)
    GET  /api/providers/events     événements du module (budget, descente de niveau, nouvel essai, abandon)
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from loopcast import costs, jobs
from loopcast.api import deps
from loopcast.providers.base import parse_request
from loopcast.providers.tasks import KINDS, inflight_usd, quote

router = APIRouter(prefix="/api/providers", tags=["providers"])


class EstimateBody(BaseModel):
    kind: Literal["video", "image"] = "video"
    request: dict = Field(default_factory=dict)
    app_id: str | None = None


class TestBody(EstimateBody):
    confirm: bool = False        # obligatoire quand le fournisseur est payant


def _generator(request: Request, kind: str):
    gen = deps.services(request).get(kind)
    if gen is None:
        raise HTTPException(503, f"service « {kind} » non configuré")
    return gen


def _request(kind: str, raw: dict):
    try:
        return parse_request(kind, raw)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("")
def overview(request: Request):
    services = deps.services(request)
    return {kind: services[kind].describe() if kind in services
            else {"kind": kind, "mode": "absent", "real": False, "why": "service non configuré", "models": []}
            for kind in KINDS}


@router.post("/estimate")
def estimate(body: EstimateBody, request: Request):
    gen = _generator(request, body.kind)
    req = _request(body.kind, body.request)
    return quote(deps.conn(request), deps.config(request).settings, deps.clock(request), gen, req, app_id=body.app_id)


@router.get("/budget")
def budget(request: Request):
    conn, now = deps.conn(request), deps.clock(request)
    out = costs.summary(conn, now, deps.config(request).settings)
    day = costs.day_start(now)
    month = day.replace(day=1)
    out["generation"] = {kind: {"today_usd": round(costs.spent(conn, day, kind=kind), 4),
                                "month_usd": round(costs.spent(conn, month, kind=kind), 4)} for kind in KINDS}
    out["inflight_usd"] = inflight_usd(conn)
    out["resets_at"] = jobs.iso(day + timedelta(days=1))
    return out


@router.post("/test")
def test_generation(body: TestBody, request: Request):
    gen = _generator(request, body.kind)
    req = _request(body.kind, body.request)
    conn, now = deps.conn(request), deps.clock(request)
    q = quote(conn, deps.config(request).settings, now, gen, req, app_id=body.app_id)
    if not q.get("ok"):
        raise HTTPException(422, q.get("error") or "aucun modèle ne convient")
    if gen.real and q["estimate_usd"] > 0 and not body.confirm:
        raise HTTPException(409, f"génération payante chez {gen.mode} (≈ {q['estimate_usd']:.2f} $ avec "
                                 f"{q['model']}) : renvoyer avec confirm=true")
    content_id = f"essai-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
    job_id = jobs.enqueue(conn, f"{body.kind}.generate",
                          {"content_id": content_id, "shot_index": 0, "request": req.model_dump(exclude_none=True)},
                          key=f"providers.test:{content_id}", app_id=body.app_id, clock=lambda: now)
    deps.publish(request, "providers", {"job_id": job_id, "kind": body.kind, "content_id": content_id})
    return {"job_id": job_id, "content_id": content_id, "mode": gen.mode, "why": gen.why, "model": q["model"],
            "estimate_usd": q["estimate_usd"], "list_usd": q["list_usd"]}


@router.get("/events")
def events(request: Request, limit: int = 50):
    rows = deps.conn(request).execute(
        """SELECT id, at, kind, message FROM events
           WHERE kind LIKE 'providers.%'
              OR (kind = 'job_dead' AND (message LIKE 'video.%' OR message LIKE 'image.%'))
           ORDER BY id DESC LIMIT ?""", (max(1, min(limit, 500)),)).fetchall()
    return [dict(r) for r in rows]
