"""Métriques (publishers, saisie manuelle) et boucle des gagnants."""

import json
from datetime import timedelta

import pytest

from loopcast.diffusion import metrics
from loopcast.diffusion.publishers import FakePublisher, Publishers
from loopcast.diffusion.store import get_post


class Flaky(FakePublisher):
    def fetch_metrics(self, account, external_ids):
        if account.platform == "instagram":
            raise RuntimeError("API indisponible")
        return super().fetch_metrics(account, external_ids)


def test_views_come_from_the_publishers(conn, cfg, clock, add_content, add_post):
    for cid in ("c1", "c2", "c3"):
        add_content(cid)
    a = add_post("c1", "phone-1:tiktok", clock() - timedelta(days=2), external_id="tt-1")
    b = add_post("c2", "phone-1:instagram", clock() - timedelta(days=2), external_id="ig-1")
    c = add_post("c3", "phone-1:tiktok", clock() - timedelta(days=60), external_id="tt-old")   # trop ancien
    pubs = Publishers(cfg, override=Flaky(views={"tt-1": 1234, "ig-1": 50, "tt-old": 9}))
    report = metrics.fetch(conn, cfg, clock(), publishers=pubs)
    assert report["updated"] == 1 and len(report["errors"]) == 1 and "phone-1:instagram" in report["errors"][0]
    assert (get_post(conn, a).views, get_post(conn, a).likes, get_post(conn, a).metrics_at) == (1234, 102, clock())
    assert get_post(conn, b).views is None and get_post(conn, c).views is None
    assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='diffusion.metrics_error'").fetchone()[0] == 1


def test_manual_views(conn, clock, add_content, add_post):
    add_content("c1")
    pid = add_post("c1", "phone-1:tiktok", clock() - timedelta(days=1))
    post = metrics.set_manual(conn, pid, clock(), views=1234, likes=56)
    assert (post["views"], post["likes"]) == (1234, 56)
    assert post["log"][-1]["msg"] == "vues saisies à la main : 1234, 56 j'aime"
    with pytest.raises(KeyError):
        metrics.set_manual(conn, 999, clock(), views=1)
    with pytest.raises(ValueError):
        metrics.set_manual(conn, pid, clock(), views=-3)
    conn.execute("UPDATE posts SET status='needs_human' WHERE id=?", (pid,))
    with pytest.raises(ValueError, match="Publié"):
        metrics.set_manual(conn, pid, clock(), views=10)


def judged(add_content, add_post, clock, views, hours_ago=30):
    ids = []
    for i, v in enumerate(views):
        add_content(f"w{i}")
        ids.append(add_post(f"w{i}", "phone-1:tiktok", clock() - timedelta(hours=hours_ago + 24 * i), views=v))
    return ids


def test_top_20_percent_become_winners_once(conn, cfg, clock, add_content, add_post):
    ids = judged(add_content, add_post, clock, [100, 900, 150, 120, 1500, 130, 110, 140, 160, 170])
    found = metrics.detect_winners(conn, cfg, clock())
    assert [w["content_id"] for w in found] == ["w4", "w1"]                 # 1500 et 900 : 2 sur 10
    assert get_post(conn, ids[4]).winner_at == clock() and get_post(conn, ids[0]).winner_at is None
    jobs = [(r["kind"], json.loads(r["payload"]), r["app_id"]) for r in conn.execute("SELECT * FROM jobs ORDER BY id")]
    assert jobs == [("ideas.variations", {"content_id": "w4"}, "habitudo"),
                    ("ideas.variations", {"content_id": "w1"}, "habitudo")]
    assert metrics.detect_winners(conn, cfg, clock() + timedelta(hours=6)) == []
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


def test_no_winner_without_five_judged_posts(conn, cfg, clock, add_content, add_post):
    judged(add_content, add_post, clock, [100, 5000, 120, 90])
    judged_young = add_post("w0", "phone-1:instagram", clock() - timedelta(hours=3), views=99999)   # pas encore jugé
    assert metrics.detect_winners(conn, cfg, clock()) == []
    assert get_post(conn, judged_young).winner_at is None


def test_flat_results_have_no_winner(conn, cfg, clock, add_content, add_post):
    judged(add_content, add_post, clock, [300] * 8)
    assert metrics.detect_winners(conn, cfg, clock()) == []


def test_old_posts_are_out_of_the_window(conn, cfg, clock, add_content, add_post):
    judged(add_content, add_post, clock, [300] * 5)
    add_content("old")
    old = add_post("old", "phone-1:tiktok", clock() - timedelta(days=20), views=9000)
    assert metrics.detect_winners(conn, cfg, clock()) == []        # le gros succès date de plus de 14 jours
    assert get_post(conn, old).winner_at is None


def test_one_collect_per_slice(conn, settings, clock):
    a = metrics.enqueue_metrics(conn, settings, clock())                    # 05:00 UTC : tranche 00-06
    assert metrics.enqueue_metrics(conn, settings, clock() + timedelta(minutes=50)) == a
    assert metrics.enqueue_metrics(conn, settings, clock() + timedelta(hours=1)) != a
