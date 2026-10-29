"""Routes communes au pipeline : file de tâches et coûts (le reste vient des modules)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from loopcast import costs, jobs
from loopcast.api import deps

router = APIRouter(prefix="/api", tags=["pipeline"])


def _job(r) -> dict:
    d = dict(r)
    for k in ("payload", "result"):
        try:
            d[k] = json.loads(d[k]) if d.get(k) else None
        except ValueError:
            pass
    return d


@router.get("/jobs")
def list_jobs(request: Request, status: str | None = None, app_id: str | None = None, kind: str | None = None,
              limit: int = 100):
    sql, args = "SELECT * FROM jobs WHERE 1=1", []
    if status:
        sql += " AND status=?"
        args.append(status)
    if app_id:
        sql += " AND app_id=?"
        args.append(app_id)
    if kind:
        sql += " AND kind LIKE ?"
        args.append(kind.rstrip("%") + "%")
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    return [_job(r) for r in deps.conn(request).execute(sql, args)]


@router.get("/jobs/stats")
def job_stats(request: Request):
    return jobs.stats(deps.conn(request))


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, request: Request):
    if not jobs.retry(deps.conn(request), job_id, clock=lambda: deps.clock(request)):
        raise HTTPException(409, "seule une tâche abandonnée ou annulée peut être relancée")
    deps.publish(request, "jobs", {"id": job_id})
    return {"ok": True}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, request: Request):
    if not jobs.cancel(deps.conn(request), job_id, clock=lambda: deps.clock(request)):
        raise HTTPException(409, "seule une tâche en attente ou abandonnée peut être annulée")
    deps.publish(request, "jobs", {"id": job_id})
    return {"ok": True}


@router.get("/costs")
def cost_summary(request: Request):
    return costs.summary(deps.conn(request), deps.clock(request), deps.config(request).settings)


@router.get("/status")
def status(request: Request):
    """Ce qui est branché : Claude (réel, démo ou absent), fournisseurs (réel, démo ou indisponible, et
    pourquoi), exécutants, et si l'on tourne sur la base de démo."""
    services = deps.services(request)
    llm = services.get("llm")
    return {
        "llm": getattr(llm, "name", "absent"),
        "services": sorted(k for k in services if k != "llm"),
        "generators": {k: {"mode": getattr(s, "mode", None), "real": bool(getattr(s, "real", False)),
                           "why": s.why, "disabled_formats": list(getattr(s, "disabled_formats", []))}
                       for k, s in sorted(services.items()) if k != "llm" and isinstance(getattr(s, "why", None), str)},
        "demo": bool(getattr(deps.config(request), "demo", False)),
        "jobs": jobs.stats(deps.conn(request)),
    }
