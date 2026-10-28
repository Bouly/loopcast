"""Routes /api/apps : apps, fichiers, sources, questions, fiche produit.

Routes en `def` (pool de threads de FastAPI) avec la connexion SQLite du thread (deps.conn) et l'heure
de deps.clock (injectable). Rien de lent ici : les lectures de sources et les appels à Claude passent
par la file de tâches. Après chaque changement, deps.publish(request, "apps", {...}) prévient le front.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from loopcast.api import deps
from loopcast.apps import assets, store
from loopcast.schemas import ProductBrief

router = APIRouter(prefix="/api/apps", tags=["apps"])

_IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}   # fichiers nommés par empreinte


def _errors(fn: Callable) -> Callable:
    """AppError (message en français + code HTTP) → réponse HTTP."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except store.AppError as e:
            raise HTTPException(e.status, str(e)) from e

    return wrapper


def _changed(request: Request, app_id: str, what: str) -> None:
    deps.publish(request, "apps", {"id": app_id, "change": what})


# --- Corps des requêtes --------------------------------------------------------------------------------

class AppCreate(BaseModel):
    id: str | None = None                  # slug ; déduit du nom s'il manque
    name: str | None = None                # facultatif si brands/<id>.json le donne
    description: str | None = None
    store_url_ios: str | None = None
    store_url_android: str | None = None
    website_url: str | None = None
    langs: list[str] | None = None
    brand: dict | None = None
    analyze: bool = False                  # lancer l'analyse tout de suite


class AppUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    store_url_ios: str | None = None
    store_url_android: str | None = None
    website_url: str | None = None
    langs: list[str] | None = None
    brand: dict | None = None


class AssetUpdate(BaseModel):
    caption: str | None = None
    kind: str | None = None


class SourceCreate(BaseModel):
    url: str | None = None
    text: str | None = None
    title: str | None = None
    kind: str | None = None


class AnswerBody(BaseModel):
    answer: str | list[str]


class AnswerItem(BaseModel):
    id: int
    answer: str | list[str]


class AnswersBody(BaseModel):
    answers: list[AnswerItem] = []
    skip: list[int] = []
    skip_rest: bool = False                # passer les questions restantes


class ApproveBody(BaseModel):
    version: int | None = None


# --- Apps ------------------------------------------------------------------------------------------------

@router.get("")
@_errors
def list_apps(request: Request):
    return store.list_apps(deps.conn(request))


@router.post("", status_code=201)
@_errors
def create_app(body: AppCreate, request: Request):
    conn, now = deps.conn(request), deps.clock(request)
    app = store.create_app(conn, deps.config(request), now=now, app_id=body.id,
                           **body.model_dump(exclude={"id", "analyze"}))
    if body.analyze and store.has_material(conn, app):
        store.request_analysis(conn, app["id"], now=now)
    _changed(request, app["id"], "created")
    return store.app_overview(conn, app["id"])


@router.get("/brands")
@_errors
def brand_files(request: Request):
    """Les fichiers brands/*.json importables (POST /api/apps avec leur id)."""
    return store.brand_files(deps.conn(request), deps.config(request))


@router.get("/{app_id}")
@_errors
def get_app(app_id: str, request: Request):
    return store.app_overview(deps.conn(request), app_id)


@router.patch("/{app_id}")
@_errors
def update_app(app_id: str, body: AppUpdate, request: Request):
    conn = deps.conn(request)
    store.update_app(conn, app_id, body.model_dump(exclude_unset=True), now=deps.clock(request))
    _changed(request, app_id, "app")
    return store.app_overview(conn, app_id)


@router.post("/{app_id}/pause")
@_errors
def pause_app(app_id: str, request: Request):
    store.pause_app(deps.conn(request), app_id, now=deps.clock(request))
    _changed(request, app_id, "status")
    return store.app_overview(deps.conn(request), app_id)


@router.post("/{app_id}/resume")
@_errors
def resume_app(app_id: str, request: Request):
    store.resume_app(deps.conn(request), app_id, now=deps.clock(request))
    _changed(request, app_id, "status")
    return store.app_overview(deps.conn(request), app_id)


@router.post("/{app_id}/analyze")
@_errors
def analyze(app_id: str, request: Request):
    """Lance l'analyse (fiche produit + questions) ; relance celle qui avait échoué."""
    conn = deps.conn(request)
    job_id = store.request_analysis(conn, app_id, now=deps.clock(request))
    _changed(request, app_id, "analysis")
    return {"job_id": job_id, "app": store.app_overview(conn, app_id)}


# --- Fichiers ----------------------------------------------------------------------------------------------

@router.get("/{app_id}/assets")
@_errors
def list_assets(app_id: str, request: Request, kind: str | None = None):
    return assets.list_assets(deps.conn(request), app_id, kind)


@router.post("/{app_id}/assets", status_code=201)
@_errors
def upload_assets(app_id: str, request: Request, files: list[UploadFile] = File(...),
                  kind: str | None = Form(None), caption: str = Form("")):
    """Envoi multipart (un ou plusieurs fichiers). Un fichier déjà connu renvoie l'asset existant
    (`duplicate`) ; un fichier refusé n'empêche pas les autres (`errors`)."""
    conn, config, now = deps.conn(request), deps.config(request), deps.clock(request)
    stored, errors = [], []
    for f in files:
        try:
            asset, created = assets.store_asset(conn, config, app_id, f.file, f.filename or "fichier", now=now,
                                                kind=kind or None, caption=caption)
            stored.append({**asset, "duplicate": not created})
        except store.NotFound:
            raise
        except store.AppError as e:
            if len(files) == 1:
                raise
            errors.append({"filename": f.filename, "error": str(e)})
    if not stored:
        raise HTTPException(400, errors[0]["error"] if errors else "aucun fichier reçu")
    _changed(request, app_id, "assets")
    created = sum(not a["duplicate"] for a in stored)
    return {"assets": stored, "created": created, "duplicates": len(stored) - created, "errors": errors}


@router.get("/{app_id}/assets/{asset_id}")
@_errors
def get_asset(app_id: str, asset_id: int, request: Request):
    return assets.get_asset(deps.conn(request), app_id, asset_id)


@router.patch("/{app_id}/assets/{asset_id}")
@_errors
def update_asset(app_id: str, asset_id: int, body: AssetUpdate, request: Request):
    asset = assets.update_asset(deps.conn(request), app_id, asset_id, now=deps.clock(request),
                                caption=body.caption, kind=body.kind)
    _changed(request, app_id, "assets")
    return asset


@router.delete("/{app_id}/assets/{asset_id}")
@_errors
def delete_asset(app_id: str, asset_id: int, request: Request):
    assets.delete_asset(deps.conn(request), deps.config(request), app_id, asset_id, now=deps.clock(request))
    _changed(request, app_id, "assets")
    return {"ok": True}


@router.post("/{app_id}/assets/{asset_id}/describe")
@_errors
def describe_asset(app_id: str, asset_id: int, request: Request):
    """Redemande la description par Claude (après une légende ou une description ratée)."""
    job_id = assets.request_description(deps.conn(request), app_id, asset_id, now=deps.clock(request))
    _changed(request, app_id, "assets")
    return {"job_id": job_id}


@router.get("/{app_id}/assets/{asset_id}/file")
@_errors
def asset_file(app_id: str, asset_id: int, request: Request):
    """Le fichier, avec les requêtes Range (Safari ne lit pas une vidéo sans), servi depuis data/apps/ seulement."""
    asset = assets.get_asset(deps.conn(request), app_id, asset_id)
    path = assets.safe_path(deps.config(request), app_id, asset["path"])
    if not path.is_file():
        raise HTTPException(404, "fichier introuvable sur le disque")
    return FileResponse(path, media_type=asset["mime"] or "application/octet-stream", headers=_IMMUTABLE,
                        filename=asset["filename"] or path.name, content_disposition_type="inline")


@router.get("/{app_id}/assets/{asset_id}/thumb")
@_errors
def asset_thumb(app_id: str, asset_id: int, request: Request):
    asset = assets.get_asset(deps.conn(request), app_id, asset_id)
    if not asset.get("thumb"):
        raise HTTPException(404, "pas de miniature pour ce fichier")
    path = assets.safe_path(deps.config(request), app_id, asset["thumb"])
    if not path.is_file():
        raise HTTPException(404, "miniature introuvable sur le disque")
    return FileResponse(path, media_type="image/jpeg", headers=_IMMUTABLE)


# --- Sources -----------------------------------------------------------------------------------------------

@router.get("/{app_id}/sources")
@_errors
def list_sources(app_id: str, request: Request):
    """Les sources, avec un aperçu du texte (le texte entier : GET …/sources/{id})."""
    out = []
    for s in store.list_sources(deps.conn(request), app_id):
        content = s.pop("content") or ""
        out.append({**s, "chars": len(content), "preview": content[:600]})
    return out


@router.post("/{app_id}/sources", status_code=201)
@_errors
def add_source(app_id: str, body: SourceCreate, request: Request):
    """Un lien (App Store, Google Play, site : lu en tâche de fond) ou un texte collé."""
    source, created = store.add_source(deps.conn(request), app_id, now=deps.clock(request), url=body.url,
                                       text=body.text, title=body.title, kind=body.kind)
    _changed(request, app_id, "sources")
    return {"source": source, "created": created}


@router.get("/{app_id}/sources/{source_id}")
@_errors
def get_source(app_id: str, source_id: int, request: Request):
    return store.get_source(deps.conn(request), app_id, source_id)


@router.post("/{app_id}/sources/{source_id}/refresh")
@_errors
def refresh_source(app_id: str, source_id: int, request: Request):
    job_id = store.refresh_source(deps.conn(request), app_id, source_id, now=deps.clock(request))
    _changed(request, app_id, "sources")
    return {"job_id": job_id}


@router.delete("/{app_id}/sources/{source_id}")
@_errors
def delete_source(app_id: str, source_id: int, request: Request):
    store.delete_source(deps.conn(request), app_id, source_id, now=deps.clock(request))
    _changed(request, app_id, "sources")
    return {"ok": True}


# --- Questions ---------------------------------------------------------------------------------------------

@router.get("/{app_id}/questions")
@_errors
def list_questions(app_id: str, request: Request, status: str | None = None):
    """Toutes les questions (par tour), ou seulement `?status=open|answered|skipped`."""
    return store.list_questions(deps.conn(request), app_id, status)


@router.post("/{app_id}/questions/answers")
@_errors
def answer_questions(app_id: str, body: AnswersBody, request: Request):
    """Plusieurs réponses d'un coup. Quand plus rien n'est ouvert, la fiche est affinée (`refine_job`)."""
    res = store.answer_questions(deps.conn(request), app_id, now=deps.clock(request),
                                 answers={a.id: a.answer for a in body.answers}, skip=body.skip,
                                 skip_rest=body.skip_rest)
    _changed(request, app_id, "questions")
    return res


@router.post("/{app_id}/questions/{question_id}/answer")
@_errors
def answer_question(app_id: str, question_id: int, body: AnswerBody, request: Request):
    res = store.answer_questions(deps.conn(request), app_id, now=deps.clock(request),
                                 answers={question_id: body.answer})
    _changed(request, app_id, "questions")
    return res


@router.post("/{app_id}/questions/{question_id}/skip")
@_errors
def skip_question(app_id: str, question_id: int, request: Request):
    res = store.answer_questions(deps.conn(request), app_id, now=deps.clock(request), skip=[question_id])
    _changed(request, app_id, "questions")
    return res


# --- Fiche produit -------------------------------------------------------------------------------------------

@router.get("/{app_id}/brief")
@_errors
def latest_brief(app_id: str, request: Request):
    """La dernière version, et le numéro de la dernière version approuvée (celle qui fait foi)."""
    conn = deps.conn(request)
    store.get_app(conn, app_id)
    row = store.latest_brief(conn, app_id)
    if row is None:
        raise HTTPException(404, "pas encore de fiche produit : lancer l'analyse")
    approved = store.latest_brief(conn, app_id, approved=True)
    return {**row, "approved_version": approved["version"] if approved else None}


@router.get("/{app_id}/brief/versions")
@_errors
def brief_versions(app_id: str, request: Request):
    return store.list_briefs(deps.conn(request), app_id)


@router.get("/{app_id}/brief/versions/{version}")
@_errors
def brief_version(app_id: str, version: int, request: Request):
    return store.get_brief(deps.conn(request), app_id, version)


@router.put("/{app_id}/brief")
@_errors
def edit_brief(app_id: str, body: ProductBrief, request: Request):
    """Édition à la main (validée par ProductBrief) : nouvelle version, à approuver."""
    row = store.save_brief(deps.conn(request), app_id, body, now=deps.clock(request))
    _changed(request, app_id, "brief")
    return row


@router.post("/{app_id}/brief/approve")
@_errors
def approve_brief(app_id: str, request: Request, body: ApproveBody | None = None):
    """Approuve la dernière version et demande la stratégie (strategy.generate)."""
    res = store.approve_brief(deps.conn(request), app_id, now=deps.clock(request),
                              version=body.version if body else None)
    _changed(request, app_id, "brief")
    return res
