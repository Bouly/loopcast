"""Exécution des posts dus : posted, needs_human, nouvelles tentatives (10 puis 30 min), un à la fois par
téléphone, refus (pause, plafond, contenu retiré), reprise après un arrêt brutal."""

import json
from datetime import timedelta

import pytest

import loopcast.diffusion.tasks  # noqa: F401 : handlers diffusion.*
from loopcast import accounts, db, jobs
from loopcast.diffusion import executor, planner, regulator
from loopcast.diffusion.publishers import FakePublisher, Publishers
from loopcast.diffusion.store import get_account, get_post, iso

from .conftest import make_config, phone


def schedule(conn, clock, content_id="c1", account_id="phone-1:tiktok", minutes=1) -> int:
    account = get_account(conn, account_id)
    return planner.create_post(conn, account, content_id, clock() + timedelta(minutes=minutes), clock(), "prévu (test)")


def run_due(conn, cfg, clock, pubs, notify=None) -> list:
    executor.enqueue_due(conn, clock())
    services = {"publishers": pubs}
    if notify is not None:
        services["notify"] = notify
    done = []
    while (job := jobs.run_one(conn, cfg, "w", clock=clock, services=services)) is not None:
        done.append(job)
    return done


def messages(post_id, conn) -> list[str]:
    return [e["msg"] for e in get_post(conn, post_id).log]


def test_due_post_is_published(conn, cfg, pubs, fake, clock, add_content):
    add_content("c1")
    pid = schedule(conn, clock)
    assert run_due(conn, cfg, clock, pubs) == [] and get_post(conn, pid).status == "scheduled"   # pas encore l'heure
    job = conn.execute("SELECT run_after FROM jobs WHERE kind='diffusion.publish'").fetchone()
    assert job["run_after"] == iso(clock() + timedelta(minutes=1))                             # à l'heure du créneau
    clock.advance(minutes=1)
    run_due(conn, cfg, clock, pubs)
    post = get_post(conn, pid)
    assert post.status == "posted" and post.posted_at == clock() and post.external_id == "fake:phone-1:tiktok:c1"
    assert fake.calls == [("phone-1:tiktok", "c1")]
    assert messages(pid, conn)[1:] == ["tentative 1/3 (fake)", "publié (fake) : publication simulée"]
    assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='diffusion.posted'").fetchone()[0] == 1


def test_manual_channel_needs_a_human(tmp_path, clock, media, sent):
    cfg = make_config(tmp_path, [phone("phone-1", tiktok={"channel": "manual"})])
    conn = db.connect(":memory:")
    accounts.sync_from_config(conn, cfg)
    path = media / "c1.mp4"
    path.write_bytes(b"x")
    conn.execute("""INSERT INTO content(id, app_id, format, lang, status, files, caption, hashtags)
                    VALUES ('c1', 'habitudo', 'notes-app', 'fr', 'approved', ?, 'Ma légende', '["habitudes"]')""",
                 (json.dumps([str(path)]),))
    pid = schedule(conn, clock, minutes=0)
    run_due(conn, cfg, clock, Publishers(cfg))
    post = get_post(conn, pid)
    assert post.status == "needs_human"
    assert "À publier à la main" in messages(pid, conn)[-1] and "Ma légende\n\n#habitudes" in messages(pid, conn)[-1]
    assert len(sent) == 1 and "à finir sur le téléphone phone-1" in sent[0][1]
    executor.mark_posted(conn, pid, clock(), external_id="7301")
    assert get_post(conn, pid).status == "posted" and get_post(conn, pid).external_id == "7301"
    with pytest.raises(executor.PostStateError):
        executor.mark_failed(conn, pid, clock())


def test_two_retries_ten_then_thirty_minutes_then_failed(conn, cfg, clock, add_content, sent):
    pubs = Publishers(cfg, override=FakePublisher(["failed", "failed", "failed"]))
    add_content("c1")
    pid = schedule(conn, clock, minutes=0)
    start = clock()
    run_due(conn, cfg, clock, pubs)
    post = get_post(conn, pid)
    assert (post.status, post.attempts, post.scheduled_at) == ("scheduled", 1, start + timedelta(minutes=10))
    clock.advance(minutes=10)
    run_due(conn, cfg, clock, pubs)
    post = get_post(conn, pid)
    assert (post.status, post.attempts, post.scheduled_at) == ("scheduled", 2, clock() + timedelta(minutes=30))
    assert sent == []                                            # pas d'alerte tant qu'on réessaie
    clock.advance(minutes=30)
    run_due(conn, cfg, clock, pubs)
    post = get_post(conn, pid)
    assert post.status == "failed" and post.attempts == 3
    assert "échec définitif après 3 tentative(s)" in messages(pid, conn)[-1]
    assert len(sent) == 1 and "après 3 tentative(s)" in sent[0][1]
    keys = [r[0] for r in conn.execute("SELECT key FROM jobs WHERE kind='diffusion.publish' ORDER BY id")]
    assert keys == [executor.publish_key(pid, n, start) for n in range(3)]
    assert keys[0] == f"diffusion.publish:{pid}:{start:%Y%m%dT%H%M%S}:0"


def test_replanned_post_is_published(conn, cfg, settings, pubs, fake, clock, add_content):
    """Un post annulé après que sa tâche a été enfilée (pause), puis replanifié : il part à son nouveau
    créneau. Avant : la tâche de la première planification (terminée, elle avait vu « skipped ») avait la même
    clé que celle de la nouvelle, jobs.enqueue la renvoyait et le post n'était plus jamais publié."""
    add_content("c1")
    pid = schedule(conn, clock, minutes=5)
    executor.enqueue_due(conn, clock())                                   # tâche enfilée pour le créneau
    regulator.pause(conn, cfg, "phone-1:tiktok", clock(), reason="vérification", hours=1, settings=settings)
    clock.advance(minutes=5)
    run_due(conn, cfg, clock, pubs)                                       # la tâche voit « skipped »
    assert get_post(conn, pid).status == "skipped" and fake.calls == []
    regulator.resume(conn, cfg, "phone-1:tiktok", clock(), settings=settings)
    account = get_account(conn, "phone-1:tiktok")
    assert planner.create_post(conn, account, "c1", clock() + timedelta(minutes=30), clock(), "test") == pid
    clock.advance(minutes=30)
    run_due(conn, cfg, clock, pubs)
    assert get_post(conn, pid).status == "posted" and fake.calls == [("phone-1:tiktok", "c1")]


def test_replanned_post_still_gets_its_retries(conn, cfg, settings, clock, add_content):
    """Même piège sur le chemin des nouvelles tentatives : la tentative 2 d'une nouvelle planification ne doit
    pas retomber sur la clé (terminée) de la tentative 2 de la planification précédente."""
    fake = FakePublisher(["failed", "failed", "posted"])
    pubs = Publishers(cfg, override=fake)
    add_content("c1")
    pid = schedule(conn, clock, minutes=0)
    run_due(conn, cfg, clock, pubs)                                       # tentative 1 : échec, essai à +10 min
    regulator.pause(conn, cfg, "phone-1:tiktok", clock(), reason="vérification", hours=1, settings=settings)
    clock.advance(minutes=10)
    run_due(conn, cfg, clock, pubs)                                       # l'essai voit « skipped »
    regulator.resume(conn, cfg, "phone-1:tiktok", clock(), settings=settings)
    account = get_account(conn, "phone-1:tiktok")
    planner.create_post(conn, account, "c1", clock() + timedelta(minutes=5), clock(), "test")
    clock.advance(minutes=5)
    run_due(conn, cfg, clock, pubs)                                       # nouvelle planification : échec
    assert (get_post(conn, pid).status, get_post(conn, pid).attempts) == ("scheduled", 1)
    clock.advance(minutes=10)
    run_due(conn, cfg, clock, pubs)                                       # son nouvel essai part
    assert get_post(conn, pid).status == "posted" and len(fake.calls) == 3


def test_crash_in_publisher_counts_as_a_failed_attempt(conn, cfg, clock, add_content):
    pubs = Publishers(cfg, override=FakePublisher(["error", "posted"]))
    add_content("c1")
    pid = schedule(conn, clock, minutes=0)
    run_due(conn, cfg, clock, pubs)
    assert "RuntimeError: panne simulée" in messages(pid, conn)[-1]
    clock.advance(minutes=10)
    run_due(conn, cfg, clock, pubs)
    assert get_post(conn, pid).status == "posted"
    assert all(r[0] == "done" for r in conn.execute("SELECT status FROM jobs"))   # la tâche ne meurt pas


def test_definitive_failure_is_not_retried(conn, cfg, clock, add_content):
    pubs = Publishers(cfg, override=FakePublisher(["fatal"]))
    add_content("c1")
    pid = schedule(conn, clock, minutes=0)
    run_due(conn, cfg, clock, pubs)
    assert (get_post(conn, pid).status, get_post(conn, pid).attempts) == ("failed", 1)


def test_one_post_at_a_time_per_phone(conn, cfg, pubs, fake, clock, add_content):
    add_content("c1")
    add_content("c2")
    busy = schedule(conn, clock, "c2", "phone-1:instagram", minutes=0)
    conn.execute("UPDATE posts SET status='running', updated_at=? WHERE id=?", (iso(clock()), busy))
    pid = schedule(conn, clock, minutes=0)
    run_due(conn, cfg, clock, pubs)
    assert get_post(conn, pid).status == "scheduled" and fake.calls == []
    job = conn.execute("SELECT status, attempts, run_after FROM jobs WHERE kind='diffusion.publish'").fetchone()
    assert (job["status"], job["attempts"]) == ("queued", 0)                  # RetryLater : pas d'essai consommé
    assert job["run_after"] == iso(clock() + timedelta(seconds=60))
    conn.execute("UPDATE posts SET status='posted' WHERE id=?", (busy,))
    clock.advance(minutes=1)
    run_due(conn, cfg, clock, pubs)
    assert get_post(conn, pid).status == "posted"


def test_paused_account_does_not_publish(conn, cfg, pubs, fake, clock, add_content, settings):
    add_content("c1")
    regulator.pause(conn, cfg, "phone-1:tiktok", clock(), reason="vérification", settings=settings)
    pid = schedule(conn, clock, minutes=0)                       # prévu pendant la pause (course)
    run_due(conn, cfg, clock, pubs)
    post = get_post(conn, pid)
    assert post.status == "skipped" and "compte en pause" in messages(pid, conn)[-1] and fake.calls == []


def test_withdrawn_content_is_not_published(conn, cfg, pubs, fake, clock, add_content):
    add_content("c1")
    pid = schedule(conn, clock, minutes=0)
    conn.execute("UPDATE content SET status='rejected' WHERE id='c1'")
    run_due(conn, cfg, clock, pubs)
    assert get_post(conn, pid).status == "skipped" and "statut rejected" in messages(pid, conn)[-1]


def test_missing_file_fails_at_once(conn, cfg, pubs, fake, clock, add_content, sent):
    add_content("c1", files=["/nulle/part.mp4"])
    pid = schedule(conn, clock, minutes=0)
    run_due(conn, cfg, clock, pubs)
    assert get_post(conn, pid).status == "failed" and fake.calls == []
    assert len(sent) == 1 and "fichier introuvable" in sent[0][1]


def test_hard_cap_at_publish_time(conn, cfg, pubs, fake, clock, add_content, add_post):
    conn.execute("""INSERT INTO strategies(app_id, version, strategy, status, approved_at)
                    VALUES ('habitudo', 1, '{"posts_per_day_per_account": 9}', 'approved', '2026-11-01')""")
    for i in range(5):
        add_content(f"done{i}")
        add_post(f"done{i}", "phone-1:tiktok", clock() - timedelta(minutes=10 + i))   # 5 posts déjà en ligne
    add_content("c1")
    pid = schedule(conn, clock, minutes=0)
    run_due(conn, cfg, clock, pubs)
    assert get_post(conn, pid).status == "skipped" and "plafond de 5" in messages(pid, conn)[-1]
    assert fake.calls == []


def test_stuck_running_post_goes_to_a_human(conn, cfg, clock, add_content, settings, sent):
    add_content("c1")
    pid = schedule(conn, clock, minutes=0)
    conn.execute("UPDATE posts SET status='running', attempts=1, updated_at=? WHERE id=?", (iso(clock()), pid))
    assert executor.recover_stuck(conn, settings, clock() + timedelta(minutes=20)) == []
    assert executor.recover_stuck(conn, settings, clock() + timedelta(minutes=50)) == [pid]
    assert get_post(conn, pid).status == "needs_human" and "vérifier dans l'app" in messages(pid, conn)[-1]
    assert len(sent) == 1


def test_missed_slot_is_skipped_not_published_late(conn, cfg, pubs, fake, clock, add_content, settings):
    add_content("c1")
    pid = schedule(conn, clock, minutes=0)
    clock.advance(hours=3)                                       # le Mac était éteint
    assert executor.skip_missed(conn, settings, clock()) == [pid]
    run_due(conn, cfg, clock, pubs)
    assert get_post(conn, pid).status == "skipped" and fake.calls == []
    assert "manqué" in messages(pid, conn)[-1]


def test_too_early_waits_for_the_slot(conn, cfg, pubs, clock, add_content):
    add_content("c1")
    pid = schedule(conn, clock, minutes=8)
    with pytest.raises(jobs.RetryLater) as e:
        executor.publish_post(conn, cfg, pid, publishers=pubs, clock=clock)
    assert 470 <= e.value.delay_s <= 480
    assert executor.publish_post(conn, cfg, pid, publishers=pubs, clock=clock, attempt=3) == {
        "post_id": pid, "skipped": "tentative déjà traitée"}
