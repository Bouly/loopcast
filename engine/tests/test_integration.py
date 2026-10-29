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


def test_demo_never_touches_the_real_base(tmp_path, monkeypatch):
    """`--demo` (serve, worker, farm… ou avant n'importe quelle commande) : base data/demo.db, fichiers sous
    data/demo/, iPhones, Claude, générateurs et publication simulés. data/loopcast.db n'est jamais ouverte.
    Avant : serve --demo et worker --demo faisaient tourner la boucle simulée sur la vraie base."""
    from loopcast import cli
    from loopcast import config as cfg
    from loopcast.diffusion.publishers import FakePublisher

    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text("notify: {ntfy_url: 'https://ntfy.example/equipe'}\n")
    opened: list[str] = []
    real_connect = db.connect
    monkeypatch.setattr(db, "connect", lambda path, **kw: opened.append(str(path)) or real_connect(path, **kw))
    served, workers = [], []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: served.append(app))

    def fake_worker(db_path, config, stop, **kw):
        workers.append((db_path, kw["services"]))
        stop.set()                                                    # la commande rend la main aussitôt

    monkeypatch.setattr(jobs, "run_worker", fake_worker)

    assert cli.main(["serve", "--demo", "--no-supervise", "--no-jobs"]) == 0
    assert cli.main(["worker", "--demo"]) == 0
    assert cli.main(["farm", "list", "--demo"]) == 0
    assert cli.main(["--demo", "jobs", "list"]) == 0

    demo_db = str(tmp_path / "data" / "demo.db")
    assert opened and set(opened) == {demo_db}
    assert not (tmp_path / "data" / "loopcast.db").exists()
    app = served[0]
    assert app.state.db_path == demo_db and app.state.config.data_dir == tmp_path / "data" / "demo"
    assert app.state.config.out_dir == tmp_path / "data" / "demo" / "out"
    assert "ntfy_url" not in app.state.config.settings["notify"]          # pas de push démo vers l'équipe
    for services in (app.state.services, workers[0][1]):
        assert services["llm"].name == "demo" and services["video"].mode == "fake"
        assert isinstance(services["publishers"].override, FakePublisher)
    assert workers[0][0] == demo_db
    conn = real_connect(demo_db)
    assert conn.execute("SELECT COUNT(*) FROM phones").fetchone()[0] == 2  # les iPhones simulés, dans la démo
    # Sans --demo, la vraie base, comme avant.
    assert cfg.load().db_path == tmp_path / "data" / "loopcast.db" and cfg.load().data_dir == tmp_path / "data"


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
