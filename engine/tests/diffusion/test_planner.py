"""Planification : créneaux (fenêtres, écarts, fuseau, déterminisme), choix du contenu, Instagram du
même téléphone, unicité par plateforme, stock bas."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from loopcast import accounts, db
from loopcast.diffusion import planner, regulator
from loopcast.diffusion.publishers import FakePublisher, Publishers
from loopcast.diffusion.settings import DiffusionSettings, parse_windows
from loopcast.diffusion.store import get_account, iso

from .conftest import Clock, make_config, phone

PARIS = ZoneInfo("Europe/Paris")
WINDOWS = parse_windows(["07:30-09:00", "12:00-14:00", "18:00-22:30"])


def posts(conn, account_id, statuses=("scheduled",)):
    marks = ",".join("?" * len(statuses))
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM posts WHERE account_id=? AND status IN ({marks}) ORDER BY scheduled_at",
        (account_id, *statuses))]


def at(p) -> datetime:
    return datetime.fromisoformat(p["scheduled_at"])


def minute(dt: datetime, tz=PARIS) -> int:
    local = dt.astimezone(tz)
    return local.hour * 60 + local.minute


def in_windows(dt: datetime, windows=WINDOWS, tz=PARIS) -> bool:
    return any(s <= minute(dt, tz) <= e for s, e in windows)


def build(tmp_path, phones, settings=None, defaults=None, publisher=None):
    cfg = make_config(tmp_path, phones, settings=settings, defaults=defaults)
    conn = db.connect(":memory:")
    accounts.sync_from_config(conn, cfg)
    conn.execute("INSERT INTO apps(id, name, status) VALUES ('habitudo', 'Habitudo', 'active')")
    return cfg, conn, DiffusionSettings.from_config(cfg), Publishers(cfg, override=publisher or FakePublisher())


def test_three_posts_in_the_windows_and_instagram_follows(conn, cfg, settings, pubs, clock, add_content):
    for i, fmt in enumerate(["notes-app", "chat-story", "hook-demo", "slideshow"]):
        add_content(f"c{i}", fmt=fmt)
    plans = {p.account_id: p for p in planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=settings)}
    tt, ig = posts(conn, "phone-1:tiktok"), posts(conn, "phone-1:instagram")
    assert len(tt) == len(ig) == 3 and plans["phone-1:instagram"].planned[0].paired
    for rows in (tt, ig):
        assert all(in_windows(at(p)) for p in rows)
        assert all((at(b) - at(a)) >= timedelta(minutes=180) for a, b in zip(rows, rows[1:]))
    # un créneau par fenêtre : matin, midi, soir
    assert [next(i for i, (s, e) in enumerate(WINDOWS) if s <= minute(at(p)) <= e) for p in tt] == [0, 1, 2]
    # Instagram : les mêmes contenus que TikTok, chacun un peu après
    tt_at = {p["content_id"]: at(p) for p in tt}
    for p in ig:
        assert p["content_id"] in tt_at and at(p) > tt_at[p["content_id"]]
    log = json.loads(ig[0]["log"])
    assert "même contenu que phone-1:tiktok" in log[0]["msg"]


def test_slots_follow_the_account_timezone(tmp_path, add_content):
    ny = ZoneInfo("America/New_York")
    cfg, conn, s, pubs = build(tmp_path, [phone("phone-1", tiktok={})], defaults={"timezone": "America/New_York"})
    clock = Clock(datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc))          # 05:00 à New York
    for i in range(3):
        conn.execute("""INSERT INTO content(id, app_id, format, lang, status, files, account_id)
                        VALUES (?, 'habitudo', 'notes-app', 'fr', 'approved', '["/x.mp4"]', 'phone-1:tiktok')""",
                     (f"c{i}",))
    planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=s)
    rows = posts(conn, "phone-1:tiktok")
    assert len(rows) == 3
    assert all(in_windows(at(p), tz=ny) for p in rows)
    assert all(at(p).astimezone(ny).date().isoformat() == "2026-11-16" for p in rows)


def test_plan_is_deterministic_and_idempotent(tmp_path, clock):
    times = []
    for run in range(2):
        cfg, conn, s, pubs = build(tmp_path / str(run), [phone("phone-1", tiktok={}, instagram={})])
        for i in range(4):
            conn.execute("""INSERT INTO content(id, app_id, format, lang, status, files, approved_at)
                            VALUES (?, 'habitudo', 'notes-app', 'fr', 'approved', '["/x.mp4"]', ?)""",
                         (f"c{i}", f"2026-11-1{i}"))
        planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=s)
        planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=s)          # deuxième passage : rien de plus
        times.append([(p["account_id"], p["content_id"], p["scheduled_at"])
                      for p in conn.execute("SELECT * FROM posts ORDER BY scheduled_at")])
    assert len(times[0]) == 6 and times[0] == times[1]


def test_human_channel_only_when_someone_is_there(tmp_path, clock, add_content):
    cfg, conn, s, pubs = build(tmp_path, [phone("phone-1", tiktok={"channel": "api_draft"})])
    for i in range(3):
        conn.execute("""INSERT INTO content(id, app_id, format, lang, status, files)
                        VALUES (?, 'habitudo', 'notes-app', 'fr', 'approved', '["/x.mp4"]')""", (f"c{i}",))
    assert pubs.requires_human(get_account(conn, "phone-1:tiktok"))
    planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=s)
    rows = posts(conn, "phone-1:tiktok")
    assert len(rows) == 3
    assert all(9 * 60 <= minute(at(p)) <= 21 * 60 for p in rows)                # jamais le matin à 07:30


def test_content_never_goes_to_another_account_of_the_platform(tmp_path, clock, media):
    cfg, conn, s, pubs = build(tmp_path, [phone("phone-1", tiktok={}), phone("phone-3", tiktok={}, slot=2)])

    def content(cid, target=None):
        conn.execute("""INSERT INTO content(id, app_id, format, lang, status, files, account_id, approved_at)
                        VALUES (?, 'habitudo', 'notes-app', 'fr', 'approved', '["/x.mp4"]', ?, ?)""",
                     (cid, target, f"2026-11-0{len(cid)}"))

    content("mine", "phone-1:tiktok")
    content("theirs", "phone-3:tiktok")
    content("free1")
    content("free2")
    content("free3")
    yesterday = iso(clock() - timedelta(days=1))
    conn.execute("""INSERT INTO posts(content_id, account_id, platform, scheduled_at, status, posted_at)
                    VALUES ('free1', 'phone-3:tiktok', 'tiktok', ?, 'posted', ?)""", (yesterday, yesterday))
    conn.execute("""INSERT INTO posts(content_id, account_id, platform, scheduled_at, status, posted_at)
                    VALUES ('free3', 'phone-3:instagram', 'instagram', ?, 'posted', ?)""", (yesterday, yesterday))
    plans = {p.account_id: p for p in planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=s)}
    mine = {p["content_id"] for p in posts(conn, "phone-1:tiktok")}
    assert mine == {"mine", "free2"}                     # ni la voix de phone-3, ni ce qui est déjà parti ailleurs
    assert plans["phone-1:tiktok"].missing == 1 and "contenu" in plans["phone-1:tiktok"].reason
    # free3 est parti sur l'Instagram de phone-3 : son TikTok peut le reprendre (même téléphone)
    assert {p["content_id"] for p in posts(conn, "phone-3:tiktok")} == {"theirs", "free3"}


def test_create_post_refuses_a_taken_content(conn, clock, add_content):
    add_content("c1")
    conn.execute("""INSERT INTO posts(content_id, account_id, platform, scheduled_at, status)
                    VALUES ('c1', 'phone-9:tiktok', 'tiktok', ?, 'scheduled')""", (iso(clock()),))
    account = get_account(conn, "phone-1:tiktok")
    assert planner.create_post(conn, account, "c1", clock() + timedelta(hours=2), clock(), "essai") is None
    assert conn.execute("SELECT COUNT(*) FROM posts WHERE content_id='c1'").fetchone()[0] == 1


def test_least_used_format_first(tmp_path, clock, media):
    cfg, conn, s, pubs = build(tmp_path, [phone("phone-1", tiktok={})])

    def content(cid, fmt, approved):
        conn.execute("""INSERT INTO content(id, app_id, format, lang, status, files, account_id, approved_at)
                        VALUES (?, 'habitudo', ?, 'fr', 'approved', '["/x.mp4"]', 'phone-1:tiktok', ?)""",
                     (cid, fmt, approved))

    for i, fmt in enumerate(["notes-app", "notes-app", "chat-story"]):
        content(f"old{i}", fmt, "2026-11-01")
        when = iso(clock() - timedelta(days=3 - i))
        conn.execute("""INSERT INTO posts(content_id, account_id, platform, scheduled_at, status, posted_at)
                        VALUES (?, 'phone-1:tiktok', 'tiktok', ?, 'posted', ?)""", (f"old{i}", when, when))
    content("n1", "notes-app", "2026-11-10")
    content("k1", "chat-story", "2026-11-11")
    content("h1", "hook-demo", "2026-11-12")
    planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=s)
    assert [p["content_id"] for p in posts(conn, "phone-1:tiktok")] == ["h1", "n1", "k1"]


def test_this_phone_first_then_winner_variations(tmp_path, clock):
    cfg, conn, s, pubs = build(tmp_path, [phone("phone-1", tiktok={})])
    conn.execute("INSERT INTO ideas(id, app_id, lang, format, hook, idea) VALUES ('i1', 'habitudo', 'fr', 'notes-app', "
                 "'h', '{\"phone_id\": \"phone-1\"}')")
    rows = [("free-old", None, None, None, "2026-11-01"),          # sans téléphone
            ("var", None, "parent", None, "2026-11-09"),           # variation d'un gagnant, sans téléphone
            ("by-idea", None, None, "i1", "2026-11-10")]            # destiné à phone-1 par son idée
    for cid, target, parent, idea, approved in rows:
        conn.execute("""INSERT INTO content(id, app_id, format, lang, status, files, account_id, parent_id, idea_id,
                                            approved_at)
                        VALUES (?, 'habitudo', 'notes-app', 'fr', 'approved', '["/x.mp4"]', ?, ?, ?, ?)""",
                     (cid, target, parent, idea, approved))
    planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=s)
    assert [p["content_id"] for p in posts(conn, "phone-1:tiktok")] == ["by-idea", "var", "free-old"]


def test_low_stock_raises_event_and_asks_strategy_once(conn, cfg, settings, clock, add_content):
    add_content("c1")
    low = planner.check_stock(conn, cfg, clock(), settings=settings)
    assert low == {"habitudo": [("phone-1:instagram", 1), ("phone-1:tiktok", 1)]}
    planner.check_stock(conn, cfg, clock() + timedelta(minutes=30), settings=settings)
    jobs = conn.execute("SELECT kind, payload, app_id FROM jobs").fetchall()
    assert [(j["kind"], json.loads(j["payload"]), j["app_id"]) for j in jobs] == [
        ("ideas.ensure_stock", {"app_id": "habitudo"}, "habitudo")]
    events = conn.execute("SELECT message FROM events WHERE kind='diffusion.stock_bas'").fetchall()
    assert len(events) == 1 and "1 contenu(s) prêt(s) sur 6" in events[0][0]
    planner.check_stock(conn, cfg, clock() + timedelta(hours=6), settings=settings)   # tranche suivante
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


def test_empty_stock_alerts_once_a_day(conn, cfg, settings, pubs, clock, sent):
    planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=settings)
    planner.plan_day(conn, cfg, clock() + timedelta(hours=1), publishers=pubs, settings=settings)
    alerts = [m for _, m in sent if "créneau(x) vide(s)" in m]
    assert len(alerts) == 2                                     # une par compte (TikTok, Instagram), pas plus


def test_mid_day_plans_only_the_future(conn, cfg, settings, pubs, clock, add_content):
    for i in range(3):
        add_content(f"c{i}")
    clock.set(2026, 11, 16, 12, 30)                              # 13:30 à Paris
    planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=settings)
    rows = posts(conn, "phone-1:tiktok")
    assert len(rows) == 3 and all(at(p) >= clock() + timedelta(minutes=5) for p in rows)


def test_lower_quota_trims_future_posts(conn, cfg, settings, pubs, clock, add_content):
    for i in range(3):
        add_content(f"c{i}")
    planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=settings)
    conn.execute("""INSERT INTO strategies(app_id, version, strategy, status, approved_at)
                    VALUES ('habitudo', 1, '{"posts_per_day_per_account": 1}', 'approved', '2026-11-16T05:30')""")
    clock.advance(hours=1)
    regulator.regulate_all(conn, cfg, clock(), settings=settings, force=True)
    plans = {p.account_id: p for p in planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=settings)}
    assert plans["phone-1:tiktok"].trimmed == 2
    left = posts(conn, "phone-1:tiktok")
    assert len(left) == 1 and minute(at(left[0])) < 9 * 60      # on garde le plus proche
    assert len(posts(conn, "phone-1:tiktok", ("skipped",))) == 2


def test_skipped_post_is_replanned_on_the_same_row(conn, cfg, settings, pubs, clock, add_content):
    add_content("c1")
    planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=settings)
    post = posts(conn, "phone-1:tiktok")[0]
    conn.execute("UPDATE posts SET status='skipped' WHERE id=?", (post["id"],))
    clock.advance(hours=4)
    planner.plan_day(conn, cfg, clock(), publishers=pubs, settings=settings)
    again = posts(conn, "phone-1:tiktok")
    assert len(again) == 1 and again[0]["id"] == post["id"] and at(again[0]) > clock()
    assert "replanifié" in json.loads(again[0]["log"])[-1]["msg"]


def test_never_more_than_five_a_day(tmp_path, clock):
    cfg, conn, s, pubs = build(tmp_path, [phone("phone-1", tiktok={})],
                               defaults={"windows": ["06:00-23:30"], "min_gap_minutes": 30})
    conn.execute("""INSERT INTO strategies(app_id, version, strategy, status, approved_at)
                    VALUES ('habitudo', 1, '{"posts_per_day_per_account": 9}', 'approved', '2026-11-01')""")
    for i in range(12):
        conn.execute("""INSERT INTO content(id, app_id, format, lang, status, files)
                        VALUES (?, 'habitudo', 'notes-app', 'fr', 'approved', '["/x.mp4"]')""", (f"c{i}",))
    for hours in (0, 3, 8):
        planner.plan_day(conn, cfg, clock() + timedelta(hours=hours), publishers=pubs, settings=s)
    assert len(posts(conn, "phone-1:tiktok")) == 5
