"""Comportements entre modules, trouvés pendant l'intégration (essai de bout en bout en démo)."""

import threading
import time

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
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: served.append((app, kw["port"])))

    def fake_worker(db_path, config, stop, **kw):
        workers.append((db_path, kw["services"]))
        stop.set()                                                    # la commande rend la main aussitôt

    monkeypatch.setattr(jobs, "run_worker", fake_worker)

    assert cli.main(["serve", "--demo", "--no-supervise", "--no-jobs"]) == 0
    assert cli.main(["--demo", "serve", "--no-supervise", "--no-jobs", "--port", "9000"]) == 0
    assert cli.main(["worker", "--demo"]) == 0
    assert cli.main(["farm", "list", "--demo"]) == 0
    assert cli.main(["--demo", "jobs", "list"]) == 0

    demo_db = str(tmp_path / "data" / "demo.db")
    assert opened and set(opened) == {demo_db}
    assert not (tmp_path / "data" / "loopcast.db").exists()
    app, port = served[0]
    assert port == 8788 and served[1][1] == 9000        # à côté du vrai Loopcast (8787), sauf --port explicite
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


# --- Chien de garde : ce qui doit toujours tourner est relancé ------------------------------------------------

def _wait_until(cond, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.01)
    return cond()


def test_the_first_executor_runs_the_watchdog_at_start_then_periodically(tmp_path):
    """jobs.run_worker : au lancement puis toutes les `watchdog_s` ; une panne du chien de garde n'arrête rien."""
    calls: list[str] = []

    def watchdog(conn, config, clock):
        calls.append(threading.current_thread().name)
        if len(calls) == 1:
            raise RuntimeError("panne passagère")

    path = tmp_path / "loopcast.db"
    db.connect(path).close()                                          # base migrée, comme au démarrage du serveur
    stop = threading.Event()
    threads = jobs.run_worker(str(path), _config(tmp_path), stop, threads=2, poll_s=0.01,
                              watchdog_s=0.05, watchdog=watchdog)
    try:
        assert _wait_until(lambda: len(calls) >= 3)
    finally:
        stop.set()
        for t in threads:
            t.join(2)
    assert set(calls) == {"jobs-0"}                                   # le premier exécutant seulement


def test_by_default_the_worker_watchdog_is_the_modules_one(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(modules, "watchdog", lambda conn, config, clock: seen.append(config))
    path = tmp_path / "loopcast.db"
    db.connect(path).close()
    stop = threading.Event()
    cfg = _config(tmp_path)
    threads = jobs.run_worker(str(path), cfg, stop, threads=1, poll_s=0.01)
    try:
        assert _wait_until(lambda: seen)
    finally:
        stop.set()
        for t in threads:
            t.join(2)
    assert seen[0] is cfg


def test_module_watchdogs_restart_the_autopilot_even_if_another_one_fails(tmp_path, clock, monkeypatch, caplog):
    """modules.watchdog : chaque module qui a un chien de garde passe ; un module en panne n'arrête pas les autres."""
    from loopcast.providers import startup as providers_startup

    def broken(conn, config, clock):
        conn.execute("BEGIN IMMEDIATE")
        raise RuntimeError("registre illisible")

    monkeypatch.setattr(providers_startup, "watchdog", broken)       # providers passe avant diffusion
    conn = db.connect(":memory:")
    modules.watchdog(conn, _config(tmp_path), clock)
    assert not conn.in_transaction                                    # rien de laissé ouvert
    assert [r[0] for r in conn.execute("SELECT key FROM jobs WHERE kind='diffusion.tick'")] == [
        "diffusion.tick:2026-11-02T09:00"]
    assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='diffusion.watchdog'").fetchone()[0] == 1
    assert "chien de garde du module loopcast.providers.startup en échec" in caplog.text
    modules.watchdog(conn, _config(tmp_path), clock)                  # la chaîne tient : rien de plus
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind='diffusion.tick'").fetchone()[0] == 1
