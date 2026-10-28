"""Régulateur : montée en charge, cible (stratégie / réglage), plafond de 5, ralentissement, pause."""

import json
from datetime import timedelta

import pytest

from loopcast import accounts, db
from loopcast.diffusion import regulator
from loopcast.diffusion.settings import DiffusionSettings
from loopcast.diffusion.store import get_state, iso

from .conftest import make_config, phone

ACC = "phone-1:tiktok"


def setup(tmp_path, created="2026-10-01", settings=None, defaults=None):
    cfg = make_config(tmp_path, [phone("phone-1", tiktok={"created": created})], settings=settings, defaults=defaults)
    conn = db.connect(":memory:")
    accounts.sync_from_config(conn, cfg)
    conn.execute("INSERT INTO apps(id, name, status) VALUES ('habitudo', 'Habitudo', 'active')")
    return cfg, conn, DiffusionSettings.from_config(cfg)


def regulate(conn, s, clock):
    account = accounts.list_accounts(conn)[0]
    return regulator.regulate_account(conn, account, s, clock())


def approve_strategy(conn, per_day, status="approved"):
    conn.execute("INSERT INTO strategies(app_id, version, strategy, status, approved_at) VALUES (?,?,?,?,?)",
                 ("habitudo", per_day, json.dumps({"posts_per_day_per_account": per_day}), status, "2026-11-01"))


def history(conn, clock, views_newest_first, account=ACC, start_hours=30):
    """Des posts publiés il y a 30 h, 54 h… (le plus récent d'abord), avec leurs vues."""
    for i, v in enumerate(views_newest_first):
        at = clock() - timedelta(hours=start_hours + 24 * i)
        conn.execute(
            """INSERT INTO posts(content_id, account_id, platform, scheduled_at, status, posted_at, views)
               VALUES (?,?,?,?, 'posted', ?, ?)""", (f"h{i}", account, "tiktok", iso(at), iso(at), v))


@pytest.mark.parametrize("created,quota,state", [
    ("2026-11-13", 1, "ramping"),       # 3 jours
    ("2026-11-06", 2, "ramping"),       # 10 jours
    ("2026-10-20", 3, "active"),        # 27 jours : la cible
])
def test_ramp_by_account_age(tmp_path, clock, created, quota, state):
    _cfg, conn, s = setup(tmp_path, created)
    st = regulate(conn, s, clock)
    assert (st.quota, st.state) == (quota, state)
    assert "cible 3" in st.note


def test_target_comes_from_the_approved_strategy(tmp_path, clock):
    _cfg, conn, s = setup(tmp_path)
    approve_strategy(conn, 2, status="draft")
    assert regulate(conn, s, clock).quota == 3                 # brouillon : ignoré
    approve_strategy(conn, 4)
    st = regulate(conn, s, clock)
    assert st.quota == 4 and "stratégie approuvée" in st.note


@pytest.mark.parametrize("strategy,settings,defaults,expected", [
    (9, {}, {}, 5),                                            # la stratégie ne passe jamais le plafond
    (None, {"pipeline": {"posts_per_day_per_account": 12}}, {}, 5),
    (None, {"pipeline": {"posts_per_day_per_account": 4}}, {"max_per_day": 2}, 2),   # plafond humain
])
def test_hard_cap_of_five(tmp_path, clock, strategy, settings, defaults, expected):
    _cfg, conn, s = setup(tmp_path, settings=settings, defaults=defaults)
    if strategy:
        approve_strategy(conn, strategy)
    st = regulate(conn, s, clock)
    assert st.quota == expected and st.target == expected


def test_slow_down_when_views_drop(tmp_path, clock):
    _cfg, conn, s = setup(tmp_path)
    history(conn, clock, [90, 100, 110, 95, 105] + [1000] * 10)
    st = regulate(conn, s, clock)
    assert st.state == "slowed" and st.quota == 2
    assert st.note.startswith("ralenti : vues ÷10 sur les 5 derniers posts")


def test_speed_up_during_ramp(tmp_path, clock):
    _cfg, conn, s = setup(tmp_path, created="2026-11-06")      # base 2
    history(conn, clock, [3000] * 5 + [1000] * 10)
    st = regulate(conn, s, clock)
    assert (st.state, st.quota) == ("boosted", 3) and "×3" in st.note


def test_never_below_one_when_slowed(tmp_path, clock):
    _cfg, conn, s = setup(tmp_path, created="2026-11-13")      # base 1
    history(conn, clock, [40] * 5 + [1000] * 10)
    assert regulate(conn, s, clock).quota == 1


def test_three_dead_posts_pause_and_alert(tmp_path, clock, sent):
    _cfg, conn, s = setup(tmp_path)
    history(conn, clock, [3, 12, 0, 500, 800])
    conn.execute("""INSERT INTO posts(content_id, account_id, platform, scheduled_at, status)
                    VALUES ('next', ?, 'tiktok', ?, 'scheduled')""", (ACC, iso(clock() + timedelta(hours=3))))
    st = regulate(conn, s, clock)
    assert st.state == "paused" and st.quota == 0
    assert st.paused_until == clock() + timedelta(hours=48)
    assert "3 posts d'affilée sous 30 vues (3, 12, 0)" in st.note
    assert len(sent) == 1 and "aller voir dans l'app" in sent[0][1]
    assert conn.execute("SELECT status FROM posts WHERE content_id='next'").fetchone()[0] == "skipped"
    clock.advance(hours=1)
    assert regulate(conn, s, clock).state == "paused"           # toujours en pause, pas de 2e alerte
    assert len(sent) == 1


def test_recent_posts_are_not_judged(tmp_path, clock):
    _cfg, conn, s = setup(tmp_path)
    history(conn, clock, [3, 12, 0], start_hours=10)            # moins de 24 h : pas encore jugés
    assert regulate(conn, s, clock).state == "active"


def test_pause_ends_without_repausing_on_the_same_posts(tmp_path, clock, sent):
    _cfg, conn, s = setup(tmp_path)
    history(conn, clock, [3, 12, 0])
    assert regulate(conn, s, clock).state == "paused"
    clock.advance(hours=49)
    st = regulate(conn, s, clock)
    assert st.state == "active" and st.quota == 3 and len(sent) == 1


def test_account_not_created_yet_or_unknown_date(tmp_path, clock):
    _cfg, conn, s = setup(tmp_path, created="2026-11-20")
    st = regulate(conn, s, clock)
    assert (st.state, st.quota) == ("not_started", 0) and "2026-11-20" in st.note
    _cfg, conn, s = setup(tmp_path, created="")
    st = regulate(conn, s, clock)
    assert st.quota == 1 and "date de création inconnue" in st.note


def test_paused_app_and_inactive_account(tmp_path, clock):
    _cfg, conn, s = setup(tmp_path)
    conn.execute("UPDATE apps SET status='paused'")
    assert regulate(conn, s, clock).quota == 0
    conn.execute("UPDATE apps SET status='active'")
    conn.execute("UPDATE accounts SET active=0")
    st = regulator.regulate_account(conn, accounts.list_accounts(conn, active_only=False)[0], s, clock())
    assert st.state == "inactive" and st.quota == 0


def test_human_pause_and_resume(tmp_path, clock, sent):
    cfg, conn, s = setup(tmp_path)
    history(conn, clock, [3, 12, 0])                            # des posts morts AVANT la reprise
    st = regulator.pause(conn, cfg, ACC, clock(), reason="vérifier le compte", settings=s)
    assert st.state == "paused" and "à la main" in st.note and "jusqu'à reprise" in st.note
    clock.advance(days=5)
    assert regulator.regulate_all(conn, cfg, clock(), settings=s, force=True)[0].state == "paused"
    st = regulator.resume(conn, cfg, ACC, clock(), settings=s)
    assert st.state == "active" and st.quota == 3               # les vieux posts morts ne repausent pas
    assert sent == []                                           # une pause à la main n'alerte personne
    kinds = [r[0] for r in conn.execute("SELECT kind FROM events ORDER BY id")]
    assert "diffusion.paused" in kinds and "diffusion.resumed" in kinds


def test_regulate_all_runs_hourly(tmp_path, clock):
    cfg, conn, s = setup(tmp_path)
    first = regulator.regulate_all(conn, cfg, clock(), settings=s)[0]
    clock.advance(minutes=20)
    assert regulator.regulate_all(conn, cfg, clock(), settings=s)[0].regulated_at == first.regulated_at
    clock.advance(minutes=45)
    assert regulator.regulate_all(conn, cfg, clock(), settings=s)[0].regulated_at == clock()
    assert get_state(conn, ACC).day == "2026-11-16"
