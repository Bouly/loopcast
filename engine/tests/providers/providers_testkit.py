"""Outils communs aux tests du module providers (pas de conftest.py ici : celui de tests/ suffit et un
second masquerait ses imports)."""

from __future__ import annotations

import json
from datetime import datetime

from loopcast import jobs
from loopcast.providers import catalog
from loopcast.providers.fake import FakeImageProvider, FakeVideoProvider
from loopcast.providers.router import Router

TEST_SCALE = 0.25          # 270 × 480 : des vidéos de test rapides à fabriquer


def video_model(model_id: str, tier: str = "standard", usd_per_s: float = 0.10, **kw) -> catalog.VideoModel:
    defaults = dict(label=model_id, provider="fake", endpoint="fake/text-to-video",
                    endpoint_i2v="fake/image-to-video", min_s=1, max_s=10, humans=True)
    defaults.update(kw)
    return catalog.VideoModel(id=model_id, tier=tier, usd_per_s=usd_per_s, **defaults)


def image_model(model_id: str, tier: str = "standard", usd_per_image: float = 0.04, **kw) -> catalog.ImageModel:
    defaults = dict(label=model_id, provider="fake", endpoint="fake/text-to-image")
    defaults.update(kw)
    return catalog.ImageModel(id=model_id, tier=tier, usd_per_image=usd_per_image, **defaults)


def epoch(clock):
    """L'horloge des tests, en secondes, pour le faux fournisseur."""
    return lambda: clock().timestamp()


def video_router(models, clock, *, per_model: dict | None = None, **fake_kw) -> Router:
    """Un routeur sur faux fournisseurs qui facturent le prix catalogue (pour tester les budgets)."""
    per_model = per_model or {}
    providers = {m.id: FakeVideoProvider(m, scale=TEST_SCALE, bill=True, clock=epoch(clock),
                                         **{**fake_kw, **per_model.get(m.id, {})}) for m in models}
    return Router("video", models, providers, mode="fake", why="tests")


def image_router(models, clock, **fake_kw) -> Router:
    providers = {m.id: FakeImageProvider(m, scale=TEST_SCALE, bill=True, clock=epoch(clock), **fake_kw)
                 for m in models}
    return Router("image", models, providers, mode="fake", why="tests")


def job_row(conn, job_id: int):
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def job_state(conn, job_id: int) -> dict:
    row = job_row(conn, job_id)
    return json.loads(row["result"]) if row["result"] else {}


def run_until_settled(conn, config, clock, services, job_id: int, max_steps: int = 60) -> str:
    """Fait tourner la file (en avançant l'horloge jusqu'au prochain réveil) jusqu'à done / dead."""
    for _ in range(max_steps):
        row = job_row(conn, job_id)
        if row["status"] in ("done", "dead", "cancelled"):
            return row["status"]
        wake = datetime.fromisoformat(row["run_after"])
        if wake > clock():
            clock.now = wake
        jobs.run_one(conn, config, "test", clock=clock, services=services)
    raise AssertionError(f"tâche #{job_id} toujours en cours après {max_steps} passages")


def events(conn, prefix: str = "providers.") -> list[tuple[str, str]]:
    return [(r["kind"], r["message"]) for r in
            conn.execute("SELECT kind, message FROM events WHERE kind LIKE ? ORDER BY id", (prefix + "%",))]
