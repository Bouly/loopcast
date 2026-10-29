"""Routes /api/diffusion et commandes `python -m loopcast diffusion …`."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from loopcast import cli
from loopcast.api.app import create_app
from loopcast.diffusion import cli as dcli
from loopcast.diffusion.startup import startup
from loopcast.diffusion.store import get_post
from loopcast.farm.backend import FakeBackend


@pytest.fixture
def api(cfg, conn, clock, pubs):
    app = create_app(cfg, conn, FakeBackend([]), services={"publishers": pubs}, db_path=":memory:")
    app.state.clock = clock
    with TestClient(app) as client:
        yield client


def test_tick_then_calendar_and_accounts(api, add_content):
    for i in range(3):
        add_content(f"c{i}")
    report = api.post("/api/diffusion/tick").json()
    assert report["errors"] == [] and report["regulator"]["phone-1:tiktok"] == {"quota": 3, "state": "active"}
    cal = api.get("/api/diffusion/calendar", params={"days": 2}).json()
    assert cal["timezone"] == "Europe/Paris" and cal["start"] == "2026-11-16"
    tt = next(a for a in cal["accounts"] if a["id"] == "phone-1:tiktok")
    today = tt["days"]["2026-11-16"]
    assert len(today) == 3 and tt["days"]["2026-11-17"] == []
    assert [p["local_time"] for p in today] == sorted(p["local_time"] for p in today)
    only = api.get("/api/diffusion/calendar", params={"account_id": "phone-1:instagram"}).json()["accounts"]
    assert [a["id"] for a in only] == ["phone-1:instagram"]

    accounts = {a["id"]: a for a in api.get("/api/diffusion/accounts").json()}
    tt = accounts["phone-1:tiktok"]
    assert (tt["quota"], tt["state_label"], tt["paused"], tt["stale"]) == (3, "actif", False, False)
    assert tt["today"]["scheduled"] == 3 and tt["publisher"] == "fake" and "actif" in tt["note"]
    assert api.get("/api/diffusion/accounts/phone-9:tiktok").status_code == 404


def test_posts_to_finish_and_team_actions(api, conn, clock, add_content, add_post):
    add_content("c1")
    pid = add_post("c1", "phone-1:tiktok", clock() - timedelta(hours=1), status="needs_human")
    todo = api.get("/api/diffusion/posts", params={"status": "needs_human"}).json()
    assert [p["id"] for p in todo] == [pid]
    assert todo[0]["content"]["text"].startswith("Légende c1") and todo[0]["content"]["files"][0].endswith("c1.mp4")
    r = api.post(f"/api/diffusion/posts/{pid}/posted", json={"external_id": "7301", "url": "https://tiktok.com/x"})
    assert r.status_code == 200 and r.json()["status"] == "posted" and r.json()["external_id"] == "7301"
    assert api.post(f"/api/diffusion/posts/{pid}/posted").status_code == 409
    assert api.post("/api/diffusion/posts/999/failed").status_code == 404
    r = api.post(f"/api/diffusion/posts/{pid}/metrics", json={"views": 1500, "likes": 80})
    assert r.status_code == 200 and (r.json()["views"], r.json()["likes"]) == (1500, 80)
    assert api.post(f"/api/diffusion/posts/{pid}/metrics", json={"views": -1}).status_code == 422
    assert api.get(f"/api/diffusion/posts/{pid}").json()["log"][-1]["msg"].startswith("vues saisies")
    kinds = [e["kind"] for e in api.get("/api/diffusion/events").json()]
    assert "diffusion.posted" in kinds


def test_pause_and_resume(api, conn, add_content):
    for i in range(3):
        add_content(f"c{i}")
    api.post("/api/diffusion/tick")
    r = api.post("/api/diffusion/accounts/phone-1:tiktok/pause", json={"reason": "vérifier le profil", "hours": 24})
    assert r.status_code == 200 and r.json()["paused"] and r.json()["state_label"] == "en pause"
    assert "vérifier le profil" in r.json()["note"] and r.json()["today"]["skipped"] == 3
    r = api.post("/api/diffusion/accounts/phone-1:tiktok/resume")
    assert r.status_code == 200 and not r.json()["paused"] and r.json()["state"] == "active"
    assert r.json()["today"]["scheduled"] == 3                     # replanifié tout de suite
    assert api.post("/api/diffusion/accounts/phone-9:tiktok/pause").status_code == 404


def test_status(api, conn, cfg, clock):
    startup(conn, cfg, clock)
    s = api.get("/api/diffusion/status").json()
    assert s["hard_cap"] == 5 and s["next_tick"] == "2026-11-16T05:00:00+00:00" and s["needs_human"] == 0


# --- CLI -------------------------------------------------------------------------------------------------------

@pytest.fixture
def cli_env(cfg, conn, clock, monkeypatch):
    monkeypatch.setattr(dcli, "_open", lambda args: (cfg, conn))
    monkeypatch.setattr("loopcast.jobs.utcnow", clock)
    return conn


def test_cli_metrics_set(cli_env, clock, add_content, add_post, capsys):
    add_content("c1")
    pid = add_post("c1", "phone-1:tiktok", clock() - timedelta(days=1))
    assert cli.main(["diffusion", "metrics", "set", str(pid), "--views", "1234"]) == 0
    assert get_post(cli_env, pid).views == 1234 and "1234 vues enregistrées" in capsys.readouterr().out
    assert cli.main(["diffusion", "metrics", "set", "999", "--views", "1"]) == 1


def test_cli_plan_calendar_tick(cli_env, clock, add_content, capsys):
    """`--dry-run` sur la vraie base : la planification se simule (canal réel : ici le repli manuel, donc aux
    heures de présence), mais rien ne part et rien n'est inventé. Avant : FakePublisher marquait le contenu
    « posted » avec un faux identifiant et de fausses vues."""
    for i in range(3):
        add_content(f"c{i}")
    assert cli.main(["diffusion", "plan", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "phone-1:tiktok" in out and "quota 3" in out and "nouveaux 3" in out
    assert cli.main(["diffusion", "calendar", "--days", "1"]) == 0
    planned = cli_env.execute("SELECT COUNT(*) FROM posts WHERE status='scheduled'").fetchone()[0]
    assert planned >= 3 and capsys.readouterr().out.count("scheduled") == planned
    first = cli_env.execute("SELECT id, scheduled_at FROM posts ORDER BY scheduled_at, id LIMIT 1").fetchone()
    clock.now = datetime.fromisoformat(first["scheduled_at"]) + timedelta(minutes=1)
    assert cli.main(["diffusion", "tick", "--dry-run"]) == 0
    assert '"diffusion.publish #' in capsys.readouterr().out
    post = get_post(cli_env, first["id"])
    assert post.status == "dry_run" and post.external_id is None and post.posted_at is None and post.views is None
    assert "essai à blanc" in post.log[-1]["msg"] and "rien n'est parti" in post.log[-1]["msg"]
    assert cli_env.execute("SELECT COUNT(*) FROM posts WHERE status='posted'").fetchone()[0] == 0
    assert cli.main(["diffusion", "accounts"]) == 0
    assert "phone-1:tiktok" in capsys.readouterr().out


def test_cli_pause_resume_and_marks(cli_env, clock, add_content, add_post, capsys):
    assert cli.main(["diffusion", "pause", "phone-1:tiktok", "--reason", "contrôle"]) == 0
    assert "en pause (à la main)" in capsys.readouterr().out
    assert cli.main(["diffusion", "resume", "phone-1:tiktok"]) == 0
    add_content("c1")
    pid = add_post("c1", "phone-1:tiktok", clock(), status="needs_human")
    assert cli.main(["diffusion", "failed", str(pid), "--note", "app plantée"]) == 0
    assert get_post(cli_env, pid).status == "failed"
    assert cli.main(["diffusion", "posted", str(pid)]) == 0             # finalement en ligne
    assert get_post(cli_env, pid).status == "posted"
