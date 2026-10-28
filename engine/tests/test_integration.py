"""Comportements entre modules, trouvés pendant l'intégration (essai de bout en bout en démo)."""

from loopcast import accounts, db, jobs, modules
from loopcast.config import Config, FarmSettings, PhoneConfig
from loopcast.diffusion import planner


def _config(tmp_path):
    return Config(root=tmp_path, settings={}, farm=FarmSettings(), phones=[
        PhoneConfig("phone-1", "U1", lang="fr", apps=["habitudo"],
                    accounts={"tiktok": {"handle": "@h.fr", "created": "2026-10-01"}}),
    ])


def test_stock_request_for_an_app_not_added_yet_is_not_an_error(tmp_path, clock):
    """devices.yaml cite une app que l'équipe n'a pas encore ajoutée : la demande de stock ne meurt pas."""
    modules.load_all()
    conn = db.connect(":memory:")
    cfg = _config(tmp_path)
    jid = jobs.enqueue(conn, "ideas.ensure_stock", {"app_id": "habitudo"}, clock=clock)
    jobs.run_one(conn, cfg, "w", clock=clock, services={})
    row = conn.execute("SELECT status, result FROM jobs WHERE id=?", (jid,)).fetchone()
    assert row["status"] == "done" and "pas encore ajoutée" in row["result"]


def test_diffusion_asks_stock_only_for_active_apps(tmp_path, clock):
    conn = db.connect(":memory:")
    cfg = _config(tmp_path)
    accounts.sync_from_config(conn, cfg)
    assert planner.check_stock(conn, cfg, clock()) == {}          # app inconnue : rien
    conn.execute("INSERT INTO apps(id, name, status) VALUES ('habitudo', 'Habitudo', 'questions')")
    assert planner.check_stock(conn, cfg, clock()) == {}          # pas encore de stratégie approuvée
    conn.execute("UPDATE apps SET status='active' WHERE id='habitudo'")
    low = planner.check_stock(conn, cfg, clock())
    assert list(low) == ["habitudo"]
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind='ideas.ensure_stock'").fetchone()[0] == 1
