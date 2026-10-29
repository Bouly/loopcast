"""API FastAPI (back seul : le front est dans web/, servi depuis web/dist s'il a été construit).

Pour l'instant : la ferme d'iPhones (état, journal, captures, prise en main à distance).
Accès à distance uniquement par Tailscale : le serveur écoute sur 127.0.0.1 par défaut.

Pas de compte ni de mot de passe : une requête qui modifie quelque chose (POST, PUT, PATCH, DELETE) venue
d'une autre origine que le dashboard est refusée (OriginGuard), pour qu'une page web ouverte sur le Mac ne
puisse pas agir à notre place.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from loopcast.config import Config
from loopcast.farm.backend import DeviceBackend
from loopcast.farm.control import BUNDLES, ControlError, PhoneController
from loopcast.farm.health import FARM_EVENT_KINDS, make_checks, status_dict
from loopcast.farm.live import EventBus, ScreenCache
from loopcast.farm.supervisor import Supervisor, list_phones
from loopcast.notify import is_alert, notify


class Tap(BaseModel):
    x: float
    y: float


class Swipe(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    duration_ms: int = Field(300, ge=50, le=5000)


class TypeText(BaseModel):
    text: str = Field(min_length=1, max_length=2200)


class Button(BaseModel):
    name: str


class App(BaseModel):
    app: str            # clé de BUNDLES (tiktok, instagram…) ou bundle id complet


# --- Contrôle d'origine (CSRF) -------------------------------------------------------------------------------

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DEV_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")    # front de dev (web/vite.config.ts)


def _origin(url: str) -> tuple[str, str, int] | None:
    """(schéma, hôte, port) d'une origine, port par défaut explicité ; None si illisible (« null »…)."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts.scheme, parts.hostname.lower(), port or (443 if parts.scheme == "https" else 80)


def allowed_origins(config: Any) -> list[str]:
    """Réglage `api.allowed_origins` : origines acceptées en plus de celle du serveur (Tailscale en HTTPS…)."""
    raw = ((getattr(config, "settings", None) or {}).get("api") or {}).get("allowed_origins") or []
    return [raw] if isinstance(raw, str) else [str(o) for o in raw]


class OriginGuard:
    """Refuse (403) toute requête qui modifie (POST, PUT, PATCH, DELETE) et dont l'en-tête Origin n'est pas
    celle du dashboard : une page web ouverte sur le Mac ne peut ni valider un contenu, ni relancer une tâche,
    ni reprendre un compte à notre place. Acceptées : la même origine que la requête (en-tête Host),
    localhost / 127.0.0.1 sur le port du serveur, le front de dev (port 5173) et `api.allowed_origins`.
    Sans en-tête Origin (CLI, curl, scripts), la requête passe."""

    def __init__(self, app: Any, allowed: Iterable[str] = ()):
        self.app = app
        self.allowed = {o for o in (_origin(a) for a in (*DEV_ORIGINS, *allowed)) if o is not None}

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS:
            origins = [v.decode("latin-1") for k, v in scope["headers"] if k == b"origin"]
            refused = next((o for o in origins if not self._accepts(o, scope)), None)
            if refused is not None:
                response = JSONResponse({"detail": f"requête refusée : origine « {refused[:200]} » non autorisée "
                                                   "(page d'un autre site ?). Si elle est légitime, l'ajouter à "
                                                   "api.allowed_origins."}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _accepts(self, origin: str, scope: dict) -> bool:
        o = _origin(origin)
        if o is None:
            return False
        if o in self.allowed:
            return True
        host = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"host"), "")
        own = _origin(f"{scope.get('scheme', 'http')}://{host}") if host else None
        if own is not None and o == own:
            return True                                        # même origine que la page qui a fait la requête
        server = scope.get("server") or (None, None)
        port = server[1] or (own[2] if own else None)
        return o[1] in LOOPBACK_HOSTS and o[2] == port


# Famille de tâche → événement que la section concernée du front écoute (web/src/live.tsx).
JOB_EVENTS = {"apps.": "apps", "strategy.": "strategy", "ideas.": "strategy", "content.": "content",
              "video.": "providers", "image.": "providers", "diffusion.": "diffusion"}


def publish_job(bus, job, status: str) -> None:
    """Une tâche vient de changer d'état : l'écran Production (« jobs ») et la section concernée l'apprennent."""
    data = {"job_id": job.id, "kind": job.kind, "status": status, "app_id": job.app_id}
    bus.publish("jobs", data)
    for prefix, kind in JOB_EVENTS.items():
        if job.kind.startswith(prefix):
            bus.publish(kind, data)
            break


def create_app(
    config: Config,
    conn: sqlite3.Connection,
    backend: DeviceBackend,
    controller: PhoneController | None = None,
    supervise: bool = False,
    web_dist: Path | None = None,
    services: dict | None = None,
    run_jobs: bool = False,
    db_path: Path | str | None = None,
) -> FastAPI:
    """`run_jobs` : lance les exécutants de la file de tâches (le pipeline) avec le serveur."""
    from loopcast import jobs, modules

    modules.load_all()
    controller = controller or PhoneController(config, conn)
    bus = EventBus()
    supervisor = Supervisor(config, conn, backend, checks=make_checks(config))
    screens = ScreenCache(conn, backend, controller, bus)
    stop = threading.Event()

    def on_events(events: list) -> None:
        for udid, kind, message in events:
            bus.publish("log", {"udid": udid, "kind": kind, "message": message})
            if is_alert(kind):
                notify("Loopcast · ferme", message, config.settings.get("notify"))

    def on_tick(result) -> None:
        on_events(result.events)
        bus.publish("phones", {"seen": result.seen})
        if result.farm_changed:
            bus.publish("farm", {})

    def supervise_loop() -> None:
        while not stop.is_set():
            try:
                on_tick(supervisor.tick())
            except Exception:
                pass   # déjà journalisé par le superviseur ; la boucle continue
            stop.wait(config.farm.poll_seconds)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        bus.bind(asyncio.get_running_loop())
        # Les tâches de fond n'ont pas accès au bus : la file prévient, on relaie au front en direct.
        remove_listener = jobs.add_listener(lambda job, status: publish_job(bus, job, status))
        if supervise:
            threading.Thread(target=supervise_loop, name="supervision", daemon=True).start()
            threading.Thread(target=screens.run_forever, args=(stop, config.farm.thumb_seconds),
                             name="captures", daemon=True).start()
        if run_jobs:
            modules.startup(conn, config, jobs.utcnow)
            jobs_cfg = config.settings.get("jobs") or {}
            jobs.run_worker(str(app.state.db_path), config, stop, services=app.state.services,
                            threads=int(jobs_cfg.get("threads", 3)), limits=jobs_cfg.get("limits") or {})
        yield
        remove_listener()
        stop.set()

    app = FastAPI(title="Loopcast", lifespan=lifespan)
    app.add_middleware(OriginGuard, allowed=allowed_origins(config))
    # État partagé avec les routes des modules (loopcast/api/deps.py).
    app.state.config = config
    app.state.conn = conn
    app.state.db_path = str(db_path) if db_path else str(config.db_path)
    app.state.bus = bus
    app.state.services = services if services is not None else modules.services(config)
    from loopcast.api.core import router as core_router

    app.include_router(core_router)
    for router in modules.routers():
        app.include_router(router)

    def known(udid: str) -> dict:
        row = conn.execute("SELECT * FROM phones WHERE udid=?", (udid,)).fetchone()
        if row is None:
            raise HTTPException(404, "iPhone inconnu")
        return dict(row)

    def control(fn, *args):
        try:
            return fn(*args)
        except ControlError as e:
            raise HTTPException(409, str(e)) from e

    def changed(udid: str) -> None:
        bus.publish("phones", {"udid": udid})

    # --- état ---------------------------------------------------------------------------

    @app.get("/api/phones")
    def phones():
        rows = list_phones(conn, config)
        for r in rows:
            screen = screens.get(r["udid"]) if r["udid"] else None
            r["screen_etag"] = screen.etag if screen else None
        return rows

    @app.post("/api/farm/refresh")
    def refresh():
        result = supervisor.tick()
        on_tick(result)
        return {"seen": result.seen, "events": len(result.events)}

    @app.get("/api/farm/status")
    def farm_status():
        """Appium, tunneld, signature de WebDriverAgent, et les problèmes de la ferme en cours."""
        health = supervisor.health
        if health is None and supervisor.checks is not None:     # avant le premier tour de supervision
            health = supervisor.checks.check(supervisor.clock())
        return status_dict(health, supervisor.farm_problems, config)

    @app.get("/api/events")
    def events(limit: int = 100, phone: str | None = None):
        limit = max(1, min(limit, 500))
        if phone:
            rows = conn.execute(
                "SELECT * FROM events WHERE phone_udid=? ORDER BY id DESC LIMIT ?", (phone, limit)).fetchall()
        else:   # le journal de la ferme : les iPhones, et la ferme elle-même (Appium, tunneld, signature)
            farm_kinds = ("farm_error", *FARM_EVENT_KINDS)
            rows = conn.execute(
                f"SELECT * FROM events WHERE phone_udid IS NOT NULL OR kind IN ({','.join('?' * len(farm_kinds))}) "
                "ORDER BY id DESC LIMIT ?", (*farm_kinds, limit)).fetchall()
        return [dict(r) for r in rows]

    @app.get("/api/live")
    async def live(request: Request):
        """Flux SSE : `phones` (l'état a changé), `screen` (nouvelle vignette), `log` (journal), `farm` (Appium,
        tunneld ou signature ont changé)."""
        queue = bus.subscribe()

        async def body():
            try:
                yield "retry: 3000\n\n"
                while not await request.is_disconnected():
                    try:
                        yield await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"     # garde la connexion ouverte à travers les proxys
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(body(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/api/phones/{udid}/screenshot")
    def screenshot(udid: str, request: Request):
        row = known(udid)
        screen = screens.get(udid)
        if screen is None or request.query_params.get("fresh"):
            screen = screens.capture(udid, bool(row["session_id"])) or screen
        if screen is None:
            raise HTTPException(502, "capture indisponible pour l'instant")
        if request.headers.get("if-none-match") == screen.etag:
            return Response(status_code=304)
        return Response(screen.png, media_type="image/png",
                        headers={"ETag": screen.etag, "Cache-Control": "private, max-age=3600"})

    # --- prise en main --------------------------------------------------------------------

    @app.post("/api/phones/{udid}/session")
    def start_session(udid: str):
        known(udid)
        sid = control(controller.start, udid)
        changed(udid)
        return {"session_id": sid, "size": control(controller.window_size, udid)}

    @app.delete("/api/phones/{udid}/session")
    def stop_session(udid: str):
        known(udid)
        controller.stop(udid)
        changed(udid)
        return {"ok": True}

    @app.get("/api/phones/{udid}/size")
    def size(udid: str):
        known(udid)
        return control(controller.window_size, udid)

    @app.post("/api/phones/{udid}/tap")
    def tap(udid: str, body: Tap):
        known(udid)
        control(controller.tap, udid, body.x, body.y)
        return {"ok": True}

    @app.post("/api/phones/{udid}/swipe")
    def swipe(udid: str, body: Swipe):
        known(udid)
        control(controller.swipe, udid, body.x1, body.y1, body.x2, body.y2, body.duration_ms)
        return {"ok": True}

    @app.post("/api/phones/{udid}/type")
    def type_text(udid: str, body: TypeText):
        known(udid)
        control(controller.type_text, udid, body.text)
        return {"ok": True}

    @app.post("/api/phones/{udid}/button")
    def button(udid: str, body: Button):
        known(udid)
        control(controller.press_button, udid, body.name)
        return {"ok": True}

    @app.post("/api/phones/{udid}/launch")
    def launch(udid: str, body: App):
        known(udid)
        control(controller.launch_app, udid, BUNDLES.get(body.app, body.app))
        return {"ok": True}

    @app.get("/api/phones/{udid}/stream")
    async def stream(udid: str):
        """Relaie le flux MJPEG de WDA : le navigateur n'a accès qu'à ce serveur, pas aux ports Appium."""
        row = known(udid)
        if not row["session_id"]:
            raise HTTPException(409, "pas de session ouverte")
        url = control(controller.stream_url, udid)
        client = httpx.AsyncClient(timeout=httpx.Timeout(10, read=None))
        try:
            upstream = await client.send(client.build_request("GET", url), stream=True)
        except httpx.HTTPError as e:
            await client.aclose()
            raise HTTPException(502, f"flux indisponible : {e}") from e

        async def body():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        media_type = upstream.headers.get("content-type", "multipart/x-mixed-replace")
        return StreamingResponse(body(), media_type=media_type, headers={"Cache-Control": "no-store"})

    # --- front construit (web/dist), avec repli sur index.html pour le routage côté client -------

    if web_dist and (web_dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            target = (web_dist / path).resolve()
            if path and target.is_file() and target.is_relative_to(web_dist.resolve()):
                return FileResponse(target)
            return FileResponse(web_dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app
