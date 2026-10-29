"""Routes du module strategy : stratégie d'une app (versions, édition, approbation, relance) et idées.

/api/strategy/formats                                   catalogue des formats (pour l'éditeur)
/api/strategy/apps/{app_id}                             stratégie en vigueur, brouillon, versions
/api/strategy/apps/{app_id}/versions/{version}          une version (GET), édition (PUT)
/api/strategy/apps/{app_id}/versions/{version}/approve  approbation
/api/strategy/apps/{app_id}/regenerate                  nouvelle version (strategy.generate)
/api/strategy/events                                    journal du module (filtrable par app_id)
/api/strategy/apps/{app_id}/stock                       stock par téléphone (GET), le compléter (POST)
/api/strategy/apps/{app_id}/phones/{phone_id}/generate  des idées pour un téléphone
/api/strategy/ideas                                     liste filtrable (app_id, phone_id, status)
/api/strategy/ideas/{idea_id}                           détail ; …/approve ; …/reject (avec une note)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from loopcast import accounts, formats, jobs
from loopcast.api import deps
from loopcast.schemas import Strategy
from loopcast.strategy import store, validate

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


class Regenerate(BaseModel):
    note: str = Field("", max_length=2000, description="Consigne de l'équipe pour la nouvelle version")


class GenerateIdeas(BaseModel):
    count: int | None = Field(None, ge=1, le=store.MAX_BATCH)


class Reject(BaseModel):
    note: str = Field("", max_length=2000)


def _app(request: Request, app_id: str) -> dict:
    app = store.get_app(deps.conn(request), app_id)
    if app is None:
        raise HTTPException(404, f"app « {app_id} » inconnue")
    return app


def _version(request: Request, app_id: str, version: int) -> store.StrategyRecord:
    rec = store.strategy_by_version(deps.conn(request), app_id, version)
    if rec is None:
        raise HTTPException(404, f"{app_id} : pas de stratégie v{version}")
    return rec


def _stamp(request: Request) -> str:
    return deps.clock(request).strftime("%Y%m%d%H%M")


def _pending(conn, app_id: str, kind: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT id, kind, status, payload, created_at, last_error FROM jobs
           WHERE app_id=? AND kind=? AND status IN ('queued','running') ORDER BY id DESC""", (app_id, kind))]


# --- Stratégie ------------------------------------------------------------------------------------------

@router.get("/formats")
def list_formats():
    return [{"id": s.id, "title": s.title, "kind": s.kind, "engine": s.engine, "cost_class": s.cost_class,
             "ai_label_required": s.ai_label_required, "description": s.description, "props_hint": s.props_hint}
            for s in formats.catalog()]


@router.get("/apps/{app_id}")
def get_strategy(app_id: str, request: Request):
    """La stratégie en vigueur, le brouillon à valider s'il y en a un, et toutes les versions."""
    app = _app(request, app_id)
    conn = deps.conn(request)
    current = store.current_strategy(conn, app_id)
    draft = store.latest_draft(conn, app_id)
    return {
        "app": {"id": app["id"], "name": app["name"], "status": app["status"]},
        "current": current.to_dict() if current else None,
        "draft": draft.to_dict() if draft else None,
        "versions": [r.to_dict(full=False) for r in store.strategy_versions(conn, app_id)],
        "pending_jobs": _pending(conn, app_id, "strategy.generate"),
    }


@router.get("/apps/{app_id}/versions")
def list_versions(app_id: str, request: Request):
    _app(request, app_id)
    return [r.to_dict(full=False) for r in store.strategy_versions(deps.conn(request), app_id)]


@router.get("/apps/{app_id}/versions/{version}")
def get_version(app_id: str, version: int, request: Request):
    return _version(request, app_id, version).to_dict()


@router.put("/apps/{app_id}/versions/{version}")
def edit_version(app_id: str, version: int, body: Strategy, request: Request):
    """Édition humaine, validée par le schéma Strategy et les contrôles du module. Un brouillon est modifié
    sur place ; une version approuvée ou archivée donne un nouveau brouillon à approuver."""
    rec = _version(request, app_id, version)
    phones = accounts.phones_for_app(deps.config(request), app_id)
    strategy, blocking, warnings = validate.check_strategy(body, phones)
    if blocking:
        raise HTTPException(422, {"message": "stratégie incomplète", "errors": blocking, "warnings": warnings})
    note = "édition manuelle" + (" · à vérifier : " + " ; ".join(warnings) if warnings else "")
    saved = store.save_edit(deps.conn(request), rec, strategy, deps.clock(request), note)
    deps.publish(request, "strategy", {"app_id": app_id, "version": saved.version, "action": "edited"})
    return {**saved.to_dict(), "warnings": warnings}


@router.post("/apps/{app_id}/versions/{version}/approve")
def approve_version(app_id: str, version: int, request: Request):
    rec = _version(request, app_id, version)
    try:
        result = store.approve_strategy(deps.conn(request), rec.id, deps.clock(request), priority=1)
    except store.Conflict as e:
        raise HTTPException(409, str(e)) from e
    deps.publish(request, "strategy", {"app_id": app_id, "version": version, "action": "approved"})
    return result


@router.post("/apps/{app_id}/regenerate")
def regenerate(app_id: str, request: Request, body: Regenerate | None = None):
    """Relance : une nouvelle version, sur la dernière fiche approuvée, avec une consigne éventuelle."""
    _app(request, app_id)
    conn = deps.conn(request)
    brief = store.approved_brief(conn, app_id)
    if brief is None:
        raise HTTPException(409, f"{app_id} : aucune fiche produit approuvée")
    payload = {"app_id": app_id, "brief_id": brief.id, "note": (body.note if body else "").strip()}
    job_id = jobs.enqueue(conn, "strategy.generate", payload, app_id=app_id, priority=1,
                          key=f"strategy.generate:{app_id}:{brief.id}:relance-{_stamp(request)}",
                          clock=lambda: deps.clock(request))
    deps.publish(request, "strategy", {"app_id": app_id, "action": "regenerate", "job_id": job_id})
    return {"job_id": job_id}


@router.get("/events")
def list_events(request: Request, app_id: str | None = None, limit: int = 100):
    """Le journal du module (stratégie prête, idées écartées ou abandonnées, budget…), le plus récent d'abord."""
    sql = "SELECT * FROM events WHERE (kind LIKE 'strategy.%' OR kind LIKE 'ideas.%')"
    args: list = []
    if app_id:                       # les messages commencent par l'app : « habitudo : … », « habitudo · phone-1 : … »
        sql += " AND (message LIKE ? OR message LIKE ?)"
        args += [f"{app_id} :%", f"{app_id} ·%"]
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    return [dict(r) for r in deps.conn(request).execute(sql, args)]


# --- Stock et génération d'idées -----------------------------------------------------------------------------

@router.get("/apps/{app_id}/stock")
def get_stock(app_id: str, request: Request):
    _app(request, app_id)
    conn = deps.conn(request)
    config = deps.config(request)
    target = store.pipeline_settings(config.settings)["stock_target"]
    return {"target": target, "phones": [
        {"phone_id": p.id, "lang": p.lang, "accounts": store.phone_accounts(p),
         **store.phone_stock(conn, app_id, p.id)} for p in accounts.phones_for_app(config, app_id)]}


@router.post("/apps/{app_id}/stock")
def fill_stock(app_id: str, request: Request):
    _app(request, app_id)
    job_id = jobs.enqueue(deps.conn(request), "ideas.ensure_stock", {"app_id": app_id}, app_id=app_id, priority=1,
                          key=f"ideas.ensure_stock:{app_id}:manuel-{_stamp(request)}",
                          clock=lambda: deps.clock(request))
    deps.publish(request, "strategy", {"app_id": app_id, "action": "stock", "job_id": job_id})
    return {"job_id": job_id}


@router.post("/apps/{app_id}/phones/{phone_id}/generate")
def generate_for_phone(app_id: str, phone_id: str, request: Request, body: GenerateIdeas | None = None):
    _app(request, app_id)
    config = deps.config(request)
    if phone_id not in {p.id for p in accounts.phones_for_app(config, app_id)}:
        raise HTTPException(404, f"{phone_id} ne promeut pas {app_id} (devices.yaml)")
    conn = deps.conn(request)
    if store.current_strategy(conn, app_id) is None:
        raise HTTPException(409, f"{app_id} : aucune stratégie approuvée")
    count = (body.count if body else None) or store.pipeline_settings(config.settings)["ideas_per_batch"]
    job_id = jobs.enqueue(conn, "ideas.generate", {"app_id": app_id, "phone_id": phone_id, "count": count},
                          app_id=app_id, priority=1, key=f"ideas.generate:{app_id}:{phone_id}:manuel-{_stamp(request)}",
                          clock=lambda: deps.clock(request))
    deps.publish(request, "strategy", {"app_id": app_id, "phone_id": phone_id, "action": "generate", "job_id": job_id})
    return {"job_id": job_id, "count": count}


# --- Idées --------------------------------------------------------------------------------------------------------

@router.get("/ideas")
def list_ideas(request: Request, app_id: str | None = None, phone_id: str | None = None, status: str | None = None,
               parent_id: str | None = None, limit: int = 100, offset: int = 0):
    """`status` accepte plusieurs valeurs séparées par des virgules (« proposed,approved »). Chaque idée porte
    sa vidéo (`video` : statut, à valider ou non, posts), ou None tant qu'elle n'est pas produite."""
    conn = deps.conn(request)
    rows = store.list_ideas(conn, app_id=app_id, phone_id=phone_id, status=status, parent_id=parent_id,
                            limit=limit, offset=offset)
    videos = store.idea_videos(conn, [r["id"] for r in rows])
    return [{**r, "video": videos.get(r["id"])} for r in rows]


@router.get("/ideas/{idea_id}")
def get_idea(idea_id: str, request: Request):
    conn = deps.conn(request)
    idea = store.get_idea(conn, idea_id)
    if idea is None:
        raise HTTPException(404, f"idée « {idea_id} » introuvable")
    idea["content"] = [dict(r) for r in conn.execute(
        "SELECT id, status, format, files, created_at FROM content WHERE idea_id=? ORDER BY created_at", (idea_id,))]
    idea["variations"] = [r["id"] for r in conn.execute(
        "SELECT i.id FROM ideas i JOIN content c ON c.id = i.parent_id WHERE c.idea_id=? ORDER BY i.id", (idea_id,))]
    return idea


@router.post("/ideas/{idea_id}/approve")
def approve_idea(idea_id: str, request: Request):
    try:
        result = store.approve_idea(deps.conn(request), idea_id, deps.clock(request))
    except store.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except store.Conflict as e:
        raise HTTPException(409, str(e)) from e
    deps.publish(request, "strategy", {"idea_id": idea_id, "status": "approved"})
    return result


@router.post("/ideas/{idea_id}/reject")
def reject_idea(idea_id: str, request: Request, body: Reject | None = None):
    try:
        result = store.reject_idea(deps.conn(request), idea_id, body.note if body else "", deps.clock(request))
    except store.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except store.Conflict as e:
        raise HTTPException(409, str(e)) from e
    deps.publish(request, "strategy", {"idea_id": idea_id, "status": "rejected"})
    return result
