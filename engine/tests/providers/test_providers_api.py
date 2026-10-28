"""Branchement (services.build), routes /api/providers et commandes `python -m loopcast providers …`."""

import httpx
import pytest
from fastapi.testclient import TestClient

from loopcast import cli as loopcast_cli
from loopcast import db, jobs
from loopcast.api.app import create_app
from loopcast.providers import catalog, fal
from loopcast.providers import cli as providers_cli
from loopcast.providers import tasks
from loopcast.providers.router import Router
from loopcast.providers.services import build


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(fal.llm, "keychain_secret", lambda service: None)


def refusing_fal_router() -> tuple[Router, list]:
    """Un routeur « fal.ai » dont le moindre appel réseau serait une erreur de test."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    client = fal.FalClient("k", http=httpx.Client(transport=httpx.MockTransport(handler)))
    models = catalog.video_models()
    return Router("video", models, {m.id: fal.FalVideoProvider(m, client) for m in models}, mode="fal",
                  why="fal.ai (tests)"), calls


def test_build_without_key_says_it_is_fake(config, no_key):
    services = build(config)
    assert set(services) == {"video", "image"}
    video = services["video"]
    assert video.mode == "fake" and not video.real and "aucune clé fal.ai" in video.why
    assert {p.name for p in video.providers.values()} == {"fake"}
    assert build(config, demo=True)["image"].why.startswith("mode démo")


def test_build_with_key_uses_fal_and_survives_a_broken_catalog(config, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "k-test")
    video = build(config)["video"]
    assert video.mode == "fal" and "FAL_KEY" in video.why and video.providers["h3-max-768p"].name == "fal"
    config.settings["providers"] = {"video": {"models": [{"id": "h3-max-768p", "usd_per_sec": 0.1}]}}
    broken = build(config)["video"]
    assert broken.mode == "fake" and "catalogue invalide" in broken.why and "usd_per_sec" in broken.why


@pytest.fixture
def api(config, backend, tmp_path, no_key):
    path = tmp_path / "api.db"
    conn = db.connect(path)
    app = create_app(config, conn, backend, services=build(config), db_path=path)
    with TestClient(app) as client:
        client.conn = conn
        yield client


def test_overview_and_estimate(api):
    body = api.get("/api/providers").json()
    assert body["video"]["mode"] == "fake" and "aucune clé" in body["video"]["why"]
    h3 = next(m for m in body["video"]["models"] if m["id"] == "h3-max-768p")
    assert h3["prices"]["5s"] == 0.4 and h3["served_by"] == "fake" and h3["source"].startswith("https://fal.ai")
    assert {m["id"] for m in body["image"]["models"]} >= {"nano-banana", "flux2-pro"}

    r = api.post("/api/providers/estimate", json={"kind": "video", "request": {
        "prompt": "A woman talks to camera", "duration_s": 8, "audio": True, "humans": True, "lang": "fr"}})
    q = r.json()
    assert r.status_code == 200 and q["model"] == "h3-max-768p" and q["list_usd"] == pytest.approx(0.64)
    assert q["estimate_usd"] == 0 and q["budget"]["ok"]
    kling = next(a for a in q["alternatives"] if a["id"] == "kling3-std")
    assert not kling["eligible"] and "fr" in kling["why"]
    bad = api.post("/api/providers/estimate", json={"kind": "video", "request": {"prompt": "x", "duration_s": 25}})
    assert bad.status_code == 422 and "invalide" in bad.json()["detail"]


def test_budget_and_events(api):
    from datetime import datetime, timezone

    from loopcast import costs

    now = datetime.now(timezone.utc)
    costs.record(api.conn, at=now, provider="fal", kind="video", cost_usd=1.25, app_id="habitudo")
    api.conn.execute("INSERT INTO events(at, kind, message) VALUES (?, 'providers.budget', 'en attente')", (jobs.iso(now),))
    api.conn.execute("INSERT INTO events(at, kind, message) VALUES (?, 'job_dead', 'video.generate #3 abandonnée')",
                     (jobs.iso(now),))
    api.conn.execute("INSERT INTO events(at, kind, message) VALUES (?, 'phone_new', 'autre module')", (jobs.iso(now),))
    budget = api.get("/api/providers/budget").json()
    assert budget["today_usd"] == pytest.approx(1.25) and budget["budget"]["daily_usd"] == 25.0
    assert budget["generation"]["video"]["today_usd"] == pytest.approx(1.25) and budget["inflight_usd"] == 0
    assert [e["kind"] for e in api.get("/api/providers/events").json()] == ["job_dead", "providers.budget"]


def test_test_generation_is_enqueued(api):
    r = api.post("/api/providers/test", json={"kind": "video", "request": {"prompt": "Test shot", "duration_s": 2}})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "fake" and body["model"] == "h3-max-768p" and body["content_id"].startswith("essai-")
    row = api.conn.execute("SELECT kind, payload FROM jobs WHERE id=?", (body["job_id"],)).fetchone()
    assert row["kind"] == "video.generate" and '"duration_s": 2' in row["payload"]


def test_paid_test_generation_needs_confirmation(config, backend, tmp_path):
    router, calls = refusing_fal_router()
    path = tmp_path / "paid.db"
    app = create_app(config, db.connect(path), backend, services={"video": router}, db_path=path)
    with TestClient(app) as client:
        req = {"kind": "video", "request": {"prompt": "x", "duration_s": 5}}
        refused = client.post("/api/providers/test", json=req)
        assert refused.status_code == 409 and "confirm=true" in refused.json()["detail"]
        assert client.post("/api/providers/test", json={**req, "confirm": True}).status_code == 200
        assert client.get("/api/providers").json()["image"]["mode"] == "absent"
    assert calls == []                              # l'API n'a fait qu'enfiler : aucun appel à fal.ai


def test_cli_list_estimate_and_test(monkeypatch, capsys, config, conn):
    monkeypatch.setattr(providers_cli, "_setup", lambda args: (config, conn, build(config, demo=True)))
    monkeypatch.setattr(tasks.time, "sleep", lambda seconds: None)
    assert loopcast_cli.main(["providers", "list"]) == 0
    out = capsys.readouterr().out
    assert "mode démo" in out and "h3-max-768p" in out and "seedance25-720p" not in out
    assert loopcast_cli.main(["providers", "estimate", "--duration", "6", "--audio", "--humans", "--lang", "fr"]) == 0
    assert "Modèle : h3-max-768p" in capsys.readouterr().out
    assert loopcast_cli.main(["providers", "test", "--duration", "2", "--quality", "eco"]) == 0
    out = capsys.readouterr().out
    assert "Fichier : " in out and "h3-turbo-768p via fake" in out and "1080×1920" in out


def test_cli_paid_test_asks_for_yes(monkeypatch, capsys, config, conn):
    router, calls = refusing_fal_router()
    monkeypatch.setattr(providers_cli, "_setup", lambda args: (config, conn, {"video": router}))
    assert loopcast_cli.main(["providers", "test"]) == 1
    assert "relancer avec --yes" in capsys.readouterr().out and calls == []
