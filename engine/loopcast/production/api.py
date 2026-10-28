"""File de validation : /api/content.

    GET   /api/content                    liste filtrable (app_id, status, account_id, format), « à valider » d'abord
    GET   /api/content/stats              nombre de contenus par statut (et « à valider »)
    GET   /api/content/{id}               détail : idée, plans (et leurs générations), contrôle qualité, coût
    POST  /api/content/{id}/approve       valider (seulement après un contrôle qualité réussi)
    POST  /api/content/{id}/reject        rejeter avec une note (l'idée est marquée, la note sert au prochain lot)
    PATCH /api/content/{id}               modifier légende et hashtags
    POST  /api/content/{id}/retry         relancer la production ({"regenerate": true} refait les plans IA)
    GET   /api/content/{id}/media/{n}     fichier n (vidéo ou image), requêtes Range acceptées, uniquement sous out/
    GET   /api/content/{id}/poster        image d'aperçu

status=review : les contenus à valider (rendus, contrôle qualité réussi).
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from loopcast.api import deps
from loopcast.production import options, qa, review, store

router = APIRouter(prefix="/api/content", tags=["production"])

_ORDER = """CASE WHEN status='rendered' AND json_extract(qa, '$.ok') = 1 THEN 0
                 WHEN status IN ('draft', 'rendering', 'rendered') THEN 1
                 WHEN status IN ('qa_failed', 'failed') THEN 2
                 WHEN status = 'approved' THEN 3 ELSE 4 END"""


class Note(BaseModel):
    note: str = Field("", max_length=review.NOTE_MAX)


class Edit(BaseModel):
    caption: str | None = Field(None, max_length=review.CAPTION_MAX)
    hashtags: list[str] | None = None


class Relaunch(BaseModel):
    regenerate: bool = False


def _row(request: Request, content_id: str):
    row = store.get_content(deps.conn(request), content_id)
    if row is None:
        raise HTTPException(404, "contenu introuvable")
    return row


def _decide(request: Request, fn, *args):
    try:
        return fn(deps.conn(request), *args)
    except review.ReviewError as e:
        raise HTTPException(e.status, str(e)) from e


def _changed(request: Request, row) -> dict:
    deps.publish(request, "content", {"id": row["id"], "status": row["status"]})
    return store.summary(row)


@router.get("")
def list_content(request: Request, app_id: str | None = None, status: str | None = None,
                 account_id: str | None = None, format: str | None = None, limit: int = 50, offset: int = 0):
    sql, args = "SELECT * FROM content WHERE 1=1", []
    if status == "review":
        sql += " AND status='rendered' AND json_extract(qa, '$.ok') = 1"
    elif status:
        sql += " AND status=?"
        args.append(status)
    for column, value in (("app_id", app_id), ("account_id", account_id), ("format", format)):
        if value:
            sql += f" AND {column}=?"
            args.append(value)
    # À valider d'abord (le plus ancien en premier), puis les productions en cours, les échecs, le reste.
    sql += (f" ORDER BY {_ORDER}, CASE WHEN {_ORDER} = 0 THEN created_at END, "
            "COALESCE(updated_at, created_at) DESC LIMIT ? OFFSET ?")
    args += [max(1, min(limit, 200)), max(0, offset)]
    return [store.summary(r) for r in deps.conn(request).execute(sql, args)]


@router.get("/stats")
def stats(request: Request, app_id: str | None = None):
    where, args = ("WHERE app_id=?", [app_id]) if app_id else ("", [])
    conn = deps.conn(request)
    counts = {r["status"]: r["n"] for r in conn.execute(
        f"SELECT status, COUNT(*) n FROM content {where} GROUP BY status", args)}
    review_n = conn.execute(f"SELECT COUNT(*) FROM content {where} {'AND' if where else 'WHERE'} "
                            "status='rendered' AND json_extract(qa, '$.ok') = 1", args).fetchone()[0]
    return {"by_status": counts, "review": review_n}


@router.get("/{content_id}")
def detail(content_id: str, request: Request):
    conn = deps.conn(request)
    row = _row(request, content_id)
    out = store.summary(row)
    envelope = store.loads(row["props"], {}) or {}
    out["composition"] = envelope.get("composition")
    out["render_props"] = envelope.get("props")
    out["timeline"] = envelope.get("timeline")
    idea_row = store.get_idea(conn, row["idea_id"]) if row["idea_id"] else None
    idea = store.loads(idea_row["idea"], {}) if idea_row else {}
    idea = idea if isinstance(idea, dict) else {}
    out["idea"] = None if idea_row is None else {
        **{k: idea.get(k) for k in ("title", "hook", "angle", "why_it_works", "pillar", "caption", "hashtags",
                                    "phone_id", "props_json")},
        "id": idea_row["id"], "status": idea_row["status"], "error": idea_row["error"]}
    jobs_rows = store.content_jobs(conn, content_id, row["idea_id"])
    generations: dict[int, dict] = {}
    for j in jobs_rows:                                   # la dernière génération de chaque plan
        if j["kind"] == "video.generate":
            payload = store.loads(j["payload"], {}) or {}
            result = store.loads(j["result"], {}) or {}
            error = (j["last_error"] or "").strip().splitlines()
            generations[int(payload.get("shot_index", -1))] = {
                "job_id": j["id"], "status": j["status"], "cost_usd": result.get("cost_usd"),
                "model": result.get("model"), "error": error[-1] if error else None}
    out["shots"] = [{**s, "index": i, "generation": generations.get(i)}
                    for i, s in enumerate(idea.get("shots") or []) if isinstance(s, dict)]
    out["jobs"] = [{"id": j["id"], "kind": j["kind"], "status": j["status"], "attempts": j["attempts"],
                    "updated_at": j["updated_at"], "last_error": j["last_error"]} for j in jobs_rows[-20:]]
    prefix = f"{content_id} :"
    out["events"] = [dict(e) for e in conn.execute(
        "SELECT at, kind, message FROM events WHERE kind LIKE 'content.%' AND substr(message, 1, ?) = ? "
        "ORDER BY id DESC LIMIT 30", (len(prefix), prefix))]
    return out


@router.post("/{content_id}/approve")
def approve(content_id: str, request: Request, body: Note | None = None):
    row = _decide(request, review.approve, content_id, deps.clock(request), body.note if body else None)
    return _changed(request, row)


@router.post("/{content_id}/reject")
def reject(content_id: str, body: Note, request: Request):
    row = _decide(request, review.reject, content_id, deps.clock(request), body.note)
    return _changed(request, row)


@router.patch("/{content_id}")
def edit(content_id: str, body: Edit, request: Request):
    row = _decide(request, review.edit, content_id, deps.clock(request), body.caption, body.hashtags)
    return _changed(request, row)


@router.post("/{content_id}/retry")
def relaunch(content_id: str, request: Request, body: Relaunch | None = None):
    job_id = _decide(request, review.relaunch, content_id, deps.clock(request), bool(body and body.regenerate))
    out = _changed(request, _row(request, content_id))
    out["job_id"] = job_id
    return out


def _safe(request: Request, path: Path) -> Path:
    """Seuls les fichiers sous out/ sont servis (jamais un chemin arbitraire venu de la base)."""
    root = store.out_dir(deps.config(request)).resolve()
    target = path.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "fichier introuvable")
    return target


@router.get("/{content_id}/media/{index}")
def media(content_id: str, index: int, request: Request):
    files = store.loads(_row(request, content_id)["files"], []) or []
    if not 0 <= index < len(files):
        raise HTTPException(404, "fichier introuvable")
    target = _safe(request, Path(files[index]))
    kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    # FileResponse gère Range (206, Content-Range), indispensable à Safari pour lire une vidéo.
    return FileResponse(target, media_type=kind, headers={"Cache-Control": "no-cache"})


@router.get("/{content_id}/poster")
def poster(content_id: str, request: Request):
    row = _row(request, content_id)
    config = deps.config(request)
    dest = store.content_dir(config, content_id) / "poster.jpg"
    if not dest.is_file():
        files = store.loads(row["files"], []) or []
        if not files:
            raise HTTPException(404, "pas encore de rendu")
        source = _safe(request, Path(files[0]))
        try:
            qa.make_poster(source, dest, is_video=row["kind"] != "carousel",
                           ffmpeg=options.ffmpeg_bin(config.settings or {}))
        except (qa.QAError, OSError) as e:
            raise HTTPException(404, f"aperçu indisponible : {e}") from e
    return FileResponse(_safe(request, dest), media_type="image/jpeg", headers={"Cache-Control": "no-cache"})
