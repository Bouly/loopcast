"""Autopilote : le tick se ré-enfile sans jamais se doubler, et une journée entière tourne seule."""

import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import loopcast.diffusion.tasks  # noqa: F401 : handlers diffusion.*
from loopcast import accounts, db, jobs
from loopcast.diffusion import autopilot, planner
from loopcast.diffusion.publishers import FakePublisher, Publishers
from loopcast.diffusion.startup import startup

from .conftest import make_config, phone

PARIS = ZoneInfo("Europe/Paris")


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def tick_keys(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT key FROM jobs WHERE kind='diffusion.tick' ORDER BY id")]


def test_startup_is_idempotent(conn, cfg, clock):
    first = startup(conn, cfg, clock)
    clock.advance(minutes=7)                                       # même tranche de 10 min (05:00-05:10)
    assert startup(conn, cfg, clock) == first
    assert tick_keys(conn) == ["diffusion.tick:2026-11-16T05:00"]


def test_tick_enqueues_the_next_one_exactly_once(conn, cfg, pubs, clock, add_content):
    add_content("c1")
    startup(conn, cfg, clock)
    job = jobs.run_one(conn, cfg, "w", clock=clock, services={"publishers": pubs})
    assert job.kind == "diffusion.tick"
    assert tick_keys(conn) == ["diffusion.tick:2026-11-16T05:00", "diffusion.tick:2026-11-16T05:10"]
    # un second tick dans la même tranche (relance à la main, redémarrage) ne crée pas de doublon
    autopilot.enqueue_tick(conn, clock(), next_slice=True)
    startup(conn, cfg, clock)
    assert len(tick_keys(conn)) == 2
    assert jobs.run_one(conn, cfg, "w", clock=clock, services={"publishers": pubs},
                        kinds=["diffusion.tick"]) is None                                 # 05:10 pas encore
    row = conn.execute("SELECT status, result FROM jobs WHERE id=?", (job.id,)).fetchone()
    assert row["status"] == "done" and '"errors": []' in row["result"]


def test_failing_step_does_not_break_the_chain(conn, cfg, pubs, clock, add_content, monkeypatch):
    add_content("c1")

    def boom(*a, **kw):
        raise RuntimeError("stock illisible")

    monkeypatch.setattr(planner, "check_stock", boom)
    startup(conn, cfg, clock)
    jobs.run_one(conn, cfg, "w", clock=clock, services={"publishers": pubs})
    tick = conn.execute("SELECT status, last_error FROM jobs WHERE key='diffusion.tick:2026-11-16T05:00'").fetchone()
    assert tick["status"] == "dead" and "stock : RuntimeError: stock illisible" in tick["last_error"]
    assert "diffusion.tick:2026-11-16T05:10" in tick_keys(conn)                         # la chaîne continue
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 2                 # le reste a tourné
    assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='diffusion.error'").fetchone()[0] == 1


def _locked_tick_writes(monkeypatch, times: int) -> None:
    """Les `times` prochaines écritures d'un diffusion.tick échouent (« database is locked » : un voisin tient
    le verrou de la base plus longtemps que son délai d'attente)."""
    real, left = jobs.enqueue, {"n": times}

    def flaky(conn, kind, *a, **kw):
        if kind == "diffusion.tick" and left["n"]:
            left["n"] -= 1
            raise sqlite3.OperationalError("database is locked")
        return real(conn, kind, *a, **kw)

    monkeypatch.setattr(autopilot.jobs, "enqueue", flaky)


def test_a_failed_write_of_the_next_tick_is_retried(conn, cfg, pubs, clock, monkeypatch):
    """Avant : max_attempts=1, une seule écriture ratée et le tick mourait sans successeur ; plus rien jusqu'au
    prochain redémarrage. Maintenant il est réessayé peu après, et la chaîne repart."""
    startup(conn, cfg, clock)
    _locked_tick_writes(monkeypatch, 1)
    services = {"publishers": pubs}
    job = jobs.run_one(conn, cfg, "w", clock=clock, services=services)
    row = conn.execute("SELECT status, attempts, run_after FROM jobs WHERE id=?", (job.id,)).fetchone()
    assert row["status"] == "queued" and row["attempts"] == 1
    assert datetime.fromisoformat(row["run_after"]) - clock() <= timedelta(seconds=36)    # attente courte
    clock.advance(minutes=1)
    assert jobs.run_one(conn, cfg, "w", clock=clock, services=services).id == job.id
    assert tick_keys(conn) == ["diffusion.tick:2026-11-16T05:00", "diffusion.tick:2026-11-16T05:10"]
    assert conn.execute("SELECT status FROM jobs WHERE id=?", (job.id,)).fetchone()[0] == "done"


def test_the_watchdog_restarts_a_broken_chain(conn, cfg, pubs, clock, monkeypatch):
    """Le tick meurt sans avoir pu écrire son successeur (trois écritures ratées) : le chien de garde,
    au plus 5 min plus tard, en enfile un et l'inscrit au journal ; la chaîne repart."""
    from loopcast.diffusion.startup import watchdog

    startup(conn, cfg, clock)
    assert watchdog(conn, cfg, clock) is None                                    # un tick attend : rien à faire
    _locked_tick_writes(monkeypatch, 3)
    services = {"publishers": pubs}
    for _ in range(3):                                                           # 05:00, 05:02, 05:04
        assert jobs.run_one(conn, cfg, "w", clock=clock, services=services) is not None
        clock.advance(minutes=2)
    assert [r[0] for r in conn.execute("SELECT status FROM jobs WHERE kind='diffusion.tick'")] == ["dead"]
    assert jobs.run_one(conn, cfg, "w", clock=clock, services=services) is None  # plus rien ne tourne

    clock.advance(minutes=2)                                                     # 05:08 : passage du chien de garde
    new_id = watchdog(conn, cfg, clock)
    assert tick_keys(conn) == ["diffusion.tick:2026-11-16T05:00", "diffusion.tick:2026-11-16T05:10"]
    (event,) = conn.execute("SELECT message FROM events WHERE kind='diffusion.watchdog'").fetchall()
    assert "autopilote relancé" in event[0] and "« dead » : sqlite3.OperationalError: database is locked" in event[0]
    assert watchdog(conn, cfg, clock) is None                                    # une seule fois
    clock.set(2026, 11, 16, 5, 10)
    assert jobs.run_one(conn, cfg, "w", clock=clock, services=services).id == new_id
    assert len(tick_keys(conn)) == 3                                             # et la chaîne continue


def test_the_watchdog_starts_a_tick_when_none_ever_existed(conn, cfg, clock):
    from loopcast.diffusion.startup import watchdog

    job_id = watchdog(conn, cfg, clock)
    assert tick_keys(conn) == ["diffusion.tick:2026-11-16T05:00"]
    assert conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0] == "queued"
    assert "aucun tick n'existait" in conn.execute("SELECT message FROM events WHERE kind='diffusion.watchdog'"
                                                   ).fetchone()[0]


def simulate(conn, cfg, clock, pubs, until: datetime) -> None:
    """Le serveur tourne : exécutants de la file toutes les minutes, autopilote toutes les 10 min."""
    startup(conn, cfg, clock)
    while clock() < until:
        while jobs.run_one(conn, cfg, "w", clock=clock, services={"publishers": pubs}) is not None:
            pass
        clock.advance(minutes=1)


def test_a_whole_day_runs_unattended(tmp_path, clock, media):
    cfg = make_config(tmp_path, [phone("phone-1", tiktok={}, instagram={}),
                                 phone("phone-2", "en", tiktok={"channel": "api_draft"}, slot=1)])
    conn = db.connect(":memory:")
    accounts.sync_from_config(conn, cfg)
    conn.execute("INSERT INTO apps(id, name, status) VALUES ('habitudo', 'Habitudo', 'active')")
    for i in range(8):
        for lang, ph in (("fr", "phone-1"), ("en", "phone-2")):
            path = media / f"{ph}-{i}.mp4"
            path.write_bytes(b"x")
            conn.execute("""INSERT INTO content(id, app_id, format, lang, status, files, account_id)
                            VALUES (?, 'habitudo', ?, ?, 'approved', ?, ?)""",
                         (f"{ph}-{i}", ["notes-app", "chat-story", "hook-demo"][i % 3], lang, f'["{path}"]',
                          f"{ph}:tiktok"))
    fake = FakePublisher()
    simulate(conn, cfg, clock, Publishers(cfg, override=fake), until=utc(2026, 11, 16, 23))

    for account_id in ("phone-1:tiktok", "phone-1:instagram", "phone-2:tiktok"):
        rows = conn.execute("SELECT * FROM posts WHERE account_id=? ORDER BY posted_at", (account_id,)).fetchall()
        assert [r["status"] for r in rows] == ["posted"] * 3, account_id
        times = [datetime.fromisoformat(r["posted_at"]) for r in rows]
        assert all(b - a >= timedelta(minutes=180) for a, b in zip(times, times[1:]))
        assert all(t.astimezone(PARIS).date().isoformat() == "2026-11-16" for t in times)
        if account_id == "phone-2:tiktok":                                   # brouillon : quelqu'un doit être là
            minutes = [t.astimezone(PARIS).hour * 60 + t.astimezone(PARIS).minute for t in times]
            assert all(9 * 60 <= m <= 21 * 60 for m in minutes)
    tt = {r[0] for r in conn.execute("SELECT content_id FROM posts WHERE account_id='phone-1:tiktok'")}
    ig = {r[0] for r in conn.execute("SELECT content_id FROM posts WHERE account_id='phone-1:instagram'")}
    assert tt == ig                                                           # même contenu, même téléphone
    assert len(fake.calls) == 9

    keys = tick_keys(conn)
    assert len(keys) == len(set(keys)) == 18 * 6 + 1                        # un tick par tranche, jamais deux
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind='diffusion.tick' AND status='done'").fetchone()[0] == 108
    metrics_runs = [r[0] for r in conn.execute("SELECT key FROM jobs WHERE kind='diffusion.metrics' ORDER BY id")]
    assert metrics_runs == [f"diffusion.metrics:2026-11-16T{h:02d}" for h in (0, 6, 12, 18)]
    asks = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind='ideas.ensure_stock'").fetchone()[0]
    assert asks >= 1                                                          # 8 contenus < 3 jours × 3 posts

    # Le lendemain : la journée suivante se planifie seule avec le stock restant.
    simulate(conn, cfg, clock, Publishers(cfg, override=fake), until=utc(2026, 11, 17, 23))
    day2 = conn.execute("""SELECT COUNT(*) FROM posts WHERE account_id='phone-1:tiktok' AND status='posted'
                           AND posted_at >= '2026-11-16T23:00:00+00:00'""").fetchone()[0]
    assert day2 == 3


def test_never_more_than_five_a_day_whatever_the_strategy(tmp_path, clock, media):
    cfg = make_config(tmp_path, [phone("phone-1", tiktok={})],
                      defaults={"windows": ["06:00-23:30"], "min_gap_minutes": 20})
    conn = db.connect(":memory:")
    accounts.sync_from_config(conn, cfg)
    conn.execute("INSERT INTO apps(id, name, status) VALUES ('habitudo', 'Habitudo', 'active')")
    conn.execute("""INSERT INTO strategies(app_id, version, strategy, status, approved_at)
                    VALUES ('habitudo', 1, '{"posts_per_day_per_account": 12}', 'approved', '2026-11-01')""")
    for i in range(20):
        path = media / f"c{i}.mp4"
        path.write_bytes(b"x")
        conn.execute("""INSERT INTO content(id, app_id, format, lang, status, files)
                        VALUES (?, 'habitudo', 'notes-app', 'fr', 'approved', ?)""", (f"c{i}", f'["{path}"]'))
    simulate(conn, cfg, clock, Publishers(cfg, override=FakePublisher()), until=utc(2026, 11, 16, 23))
    assert conn.execute("SELECT COUNT(*) FROM posts WHERE status='posted'").fetchone()[0] == 5


def test_dry_run_publishes_nothing_and_invents_nothing(tmp_path, conn, clock, add_content):
    """diffusion.dry_run sur la vraie base, deux jours d'autopilote : le journal dit ce qui serait parti, au
    rythme réel (jamais plus que le quota du jour, un contenu une fois par jour), mais aucun contenu n'est
    consommé, aucune vue n'est inventée, ni gagnant ni variation (Claude), régulateur intact.
    Avant : FakePublisher marquait les contenus « posted » avec de fausses vues qui pilotaient le reste."""
    from loopcast.diffusion import services as diffusion_services
    from loopcast.diffusion.publishers import DryRunPublisher
    from loopcast.diffusion.store import get_account, read_log

    for i in range(8):
        add_content(f"c{i}", fmt=["notes-app", "chat-story", "hook-demo"][i % 3])
    dry = make_config(tmp_path, settings={"diffusion": {"dry_run": True}})
    pubs = diffusion_services.build(dry)["publishers"]
    assert isinstance(pubs.for_account(get_account(conn, "phone-1:tiktok")), DryRunPublisher)
    simulate(conn, dry, clock, pubs, until=utc(2026, 11, 17, 23))

    rows = conn.execute("SELECT * FROM posts").fetchall()
    assert rows and {r["status"] for r in rows} <= {"dry_run", "scheduled"}
    assert all(r["external_id"] is None and r["posted_at"] is None and r["views"] is None for r in rows)
    runs = [(r["account_id"], e["at"]) for r in rows for e in read_log(r["log"]) if "essai à blanc" in e["msg"]]
    assert runs
    per_day: dict = {}
    for account_id, at in runs:
        day = datetime.fromisoformat(at).astimezone(PARIS).date()
        per_day[(account_id, day)] = per_day.get((account_id, day), 0) + 1
    assert max(per_day.values()) <= 3                                    # la cadence réelle, pas plus
    for r in rows:                                                       # un contenu au plus une fois par jour
        days = [datetime.fromisoformat(e["at"]).astimezone(PARIS).date() for e in read_log(r["log"])
                if "essai à blanc" in e["msg"]]
        assert len(days) == len(set(days))
    for account_id in ("phone-1:tiktok", "phone-1:instagram"):
        assert len(planner.candidates(conn, get_account(conn, account_id))) == 8    # stock intact
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE kind='ideas.variations'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM posts WHERE winner_at IS NOT NULL").fetchone()[0] == 0
    st = conn.execute("SELECT state, quota FROM account_state WHERE account_id='phone-1:tiktok'").fetchone()
    assert (st["state"], st["quota"]) == ("active", 3)
