"""Outils de test du module apps : base sur disque, config, faux Claude, faux internet, API.

Ce dossier est un paquet (__init__.py) : son conftest ne masque pas celui de tests/ (Clock, UDID…).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import loopcast.apps.demo  # noqa: F401  (réponses de démo)
import loopcast.apps.tasks  # noqa: F401  (enregistre les tâches apps.*)
from loopcast import db, jobs
from loopcast.apps.api import router
from loopcast.config import Config, FarmSettings
from loopcast.llm import FakeLLM
from loopcast.schemas import AnalysisResult

from .helpers import REPO, Bus, FakeWeb, analysis, brief


# --- Fixtures -------------------------------------------------------------------------------------------

@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(root=tmp_path, settings={}, farm=FarmSettings(backend="fake"), phones=[])


@pytest.fixture
def with_brand(cfg) -> Path:
    """Copie la vraie marque de démo (brands/habitudo.json) dans le dépôt de test."""
    target = Path(cfg.root) / "brands"
    target.mkdir(parents=True, exist_ok=True)
    return Path(shutil.copy(REPO / "brands" / "habitudo.json", target / "habitudo.json"))


@pytest.fixture
def dbpath(tmp_path) -> Path:
    return tmp_path / "data" / "loopcast.db"


@pytest.fixture
def aconn(dbpath):
    """Base sur disque (comme en vrai) : l'API ouvre ses propres connexions dessus."""
    conn = db.connect(dbpath)
    yield conn
    conn.close()


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM({
        "asset.describe": lambda req: analysis(),
        "app.analyze": lambda req: AnalysisResult(brief=brief(), questions=[]),
        "app.refine": lambda req: AnalysisResult(brief=brief(confidence=0.8), questions=[]),
    }, cost_usd=0.05)


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


@pytest.fixture
def services(fake_llm, web) -> dict:
    return {"llm": fake_llm, "http": web.client()}


@pytest.fixture
def run(aconn, cfg, clock, services):
    """Exécute les tâches prêtes (au plus `limit`) ; renvoie celles qui ont tourné."""

    def go(kinds: list[str] | None = None, limit: int = 100) -> list[jobs.Job]:
        done = []
        while len(done) < limit:
            job = jobs.run_one(aconn, cfg, "test", clock=clock, services=services, kinds=kinds)
            if job is None:
                break
            done.append(job)
        return done

    return go


@pytest.fixture
def api(cfg, dbpath, aconn, clock, services):
    app = FastAPI()
    app.include_router(router)
    app.state.config = cfg
    app.state.db_path = str(dbpath)
    app.state.services = services
    app.state.clock = clock
    app.state.bus = Bus()
    with TestClient(app) as client:
        client.bus = app.state.bus
        yield client
