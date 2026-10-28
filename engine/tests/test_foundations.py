"""Fondations du pipeline : migrations, file de tâches, budgets, client Claude, formats, comptes."""

import json
import random
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from conftest import Clock

from loopcast import accounts, costs, db, formats, jobs, llm
from loopcast.config import Config, FarmSettings, PhoneConfig
from loopcast.schemas import AssetAnalysis


# --- Migrations ---------------------------------------------------------------------------------------

def test_legacy_database_is_upgraded_in_place(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    for name in ("0001_base", "0002_phones"):
        old.executescript((db.MIGRATIONS_DIR / f"{name}.sql").read_text())
    old.execute("PRAGMA user_version = 2")
    old.execute("INSERT INTO phones(udid, phone_id) VALUES ('U1', 'phone-1')")
    old.commit()
    old.close()

    conn = db.connect(path)
    names = [r[0] for r in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]
    assert names[:3] == ["0001_base", "0002_phones", "0003_pipeline"]
    assert conn.execute("SELECT phone_id FROM phones").fetchone()[0] == "phone-1"   # rien de perdu
    assert db.migrate(conn) == []                                                    # idempotent


def test_unique_content_per_platform():
    conn = db.connect(":memory:")
    conn.execute("INSERT INTO posts(content_id, account_id, platform) VALUES ('c1', 'phone-1:tiktok', 'tiktok')")
    conn.execute("INSERT INTO posts(content_id, account_id, platform) VALUES ('c1', 'phone-1:instagram', 'instagram')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO posts(content_id, account_id, platform) VALUES ('c1', 'phone-2:tiktok', 'tiktok')")


# --- File de tâches ----------------------------------------------------------------------------------

@contextmanager
def handlers(**specs):
    saved = dict(jobs.HANDLERS)
    try:
        for kind, (fn, kw) in specs.items():
            jobs.handler(kind.replace("_", "."), **kw)(fn)
        yield
    finally:
        jobs.HANDLERS.clear()
        jobs.HANDLERS.update(saved)


@pytest.fixture
def jconn():
    return db.connect(":memory:")


def test_enqueue_is_idempotent(jconn, clock):
    with handlers(t_ok=(lambda ctx, p: {"done": True}, {})):
        a = jobs.enqueue(jconn, "t.ok", {"x": 1}, key="k1", clock=clock)
        b = jobs.enqueue(jconn, "t.ok", {"x": 2}, key="k1", clock=clock)
        assert a == b
        assert jconn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_success_records_result(jconn, clock):
    with handlers(t_ok=(lambda ctx, p: {"echo": p["x"]}, {})):
        jid = jobs.enqueue(jconn, "t.ok", {"x": 7}, clock=clock)
        assert jobs.run_one(jconn, None, "w", clock=clock).id == jid
        row = jconn.execute("SELECT status, result FROM jobs WHERE id=?", (jid,)).fetchone()
        assert row["status"] == "done" and json.loads(row["result"]) == {"echo": 7}
        assert jobs.run_one(jconn, None, "w", clock=clock) is None


def test_failures_back_off_then_die(jconn, clock):
    def boom(ctx, p):
        raise ValueError("réseau")

    with handlers(t_boom=(boom, {"max_attempts": 3, "backoff_s": (10, 100)})):
        jid = jobs.enqueue(jconn, "t.boom", clock=clock)
        jobs.run_one(jconn, None, "w", clock=clock)
        row = jconn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        assert row["status"] == "queued" and "réseau" in row["last_error"]
        assert jobs.run_one(jconn, None, "w", clock=clock) is None        # pas avant l'attente
        clock.advance(seconds=13)
        jobs.run_one(jconn, None, "w", clock=clock)
        clock.advance(seconds=130)
        jobs.run_one(jconn, None, "w", clock=clock)
        row = jconn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        assert row["status"] == "dead" and row["attempts"] == 3
        assert jconn.execute("SELECT COUNT(*) FROM events WHERE kind='job_dead'").fetchone()[0] == 1
        assert jobs.retry(jconn, jid, clock=clock)
        assert jconn.execute("SELECT status, attempts FROM jobs WHERE id=?", (jid,)).fetchone()[:] == ("queued", 0)


def test_permanent_dies_at_once(jconn, clock):
    def bad(ctx, p):
        raise jobs.Permanent("clé absente")

    with handlers(t_bad=(bad, {"max_attempts": 5})):
        jid = jobs.enqueue(jconn, "t.bad", clock=clock)
        jobs.run_one(jconn, None, "w", clock=clock)
        assert jconn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0] == "dead"


def test_retry_later_keeps_attempts(jconn, clock):
    polls = {"n": 0}

    def poll(ctx, p):
        polls["n"] += 1
        if polls["n"] < 4:
            raise jobs.RetryLater(20, "toujours en calcul", result={"polls": polls["n"]})
        return {"video": "ok"}

    with handlers(t_poll=(poll, {"max_attempts": 1})):
        jid = jobs.enqueue(jconn, "t.poll", clock=clock)
        for _ in range(4):
            jobs.run_one(jconn, None, "w", clock=clock)
            clock.advance(seconds=21)
        row = jconn.execute("SELECT status, attempts FROM jobs WHERE id=?", (jid,)).fetchone()
        assert row["status"] == "done" and row["attempts"] == 1


def test_expired_lease_is_recovered(jconn, clock):
    with handlers(t_slow=(lambda ctx, p: None, {"lease_s": 60, "max_attempts": 2})):
        jid = jobs.enqueue(jconn, "t.slow", clock=clock)
        job = jobs.claim(jconn, "w-mort", clock=clock)            # le processus meurt ici
        assert job.id == jid
        clock.advance(seconds=61)
        assert jobs.requeue_expired(jconn, clock=clock) == 1
        row = jconn.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
        assert row["status"] == "queued"


def test_concurrency_limit_per_family(jconn, clock):
    with handlers(video_a=(lambda ctx, p: None, {}), app_b=(lambda ctx, p: None, {})):
        jobs.enqueue(jconn, "video.a", clock=clock)
        jobs.enqueue(jconn, "video.a", clock=clock)
        jobs.enqueue(jconn, "app.b", clock=clock)
        first = jobs.claim(jconn, "w1", clock=clock, limits={"video.": 1})
        second = jobs.claim(jconn, "w2", clock=clock, limits={"video.": 1})
        assert first.kind == "video.a" and second.kind == "app.b"
        assert jobs.claim(jconn, "w3", clock=clock, limits={"video.": 1}) is None


def test_handler_context_can_enqueue_children(jconn, clock):
    def parent(ctx, p):
        ctx.enqueue("t.child", {"n": 1}, key="child-1")
        return None

    with handlers(t_parent=(parent, {}), t_child=(lambda ctx, p: None, {})):
        pid = jobs.enqueue(jconn, "t.parent", app_id="habitudo", clock=clock)
        jobs.run_one(jconn, None, "w", clock=clock)
        child = jconn.execute("SELECT * FROM jobs WHERE kind='t.child'").fetchone()
        assert child["parent_id"] == pid and child["app_id"] == "habitudo"


# --- Budgets ------------------------------------------------------------------------------------------

def test_budget_caps(jconn, clock):
    settings = {"budget": {"daily_usd": 10, "daily_usd_per_app": 6, "monthly_usd": 100}}
    costs.record(jconn, at=clock(), provider="fal", kind="video", cost_usd=5.5, app_id="a")
    assert costs.check_budget(jconn, settings, clock(), 0.4, app_id="a").ok
    refused = costs.check_budget(jconn, settings, clock(), 1.0, app_id="a")
    assert not refused.ok and "a" in refused.reason and refused.retry_at > clock()
    assert costs.check_budget(jconn, settings, clock(), 4.0, app_id="b").ok
    assert not costs.check_budget(jconn, settings, clock(), 4.6, app_id="b").ok    # plafond global
    clock.advance(days=1)
    assert costs.check_budget(jconn, settings, clock(), 4.6, app_id="a").ok        # nouveau jour


# --- Client Claude -------------------------------------------------------------------------------------

class _FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class _FakeClient:
    def __init__(self, msg):
        self.kwargs = None
        outer = self

        class _Messages:
            def stream(self, **kw):
                outer.kwargs = kw
                return _FakeStream(msg)

        self.beta = SimpleNamespace(messages=_Messages())


def _analysis():
    return AssetAnalysis(screen="accueil", shows="liste d'habitudes", feature="suivi", on_screen_text=["Aujourd'hui"],
                         usable_in_video=True, caution="")


def _msg(parsed, stop="end_turn", model="claude-opus-5-5"):
    usage = SimpleNamespace(input_tokens=2000, output_tokens=500, cache_read_input_tokens=1000,
                            cache_creation_input_tokens=0)
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop, usage=usage, model=model, stop_details=None)


def test_anthropic_llm_structured_call():
    client = _FakeClient(_msg(_analysis()))
    res = llm.AnthropicLLM({"llm": {"tasks": {"asset.describe": {"effort": "low"}}}}, client=client).structured(
        task="asset.describe", system="Tu décris des captures.", content="Décris.", schema=AssetAnalysis)
    assert res.data.screen == "accueil"
    kw = client.kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["output_format"] is AssetAnalysis
    assert kw["output_config"] == {"effort": "low"} and kw["fallbacks"] == "default"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert res.cost_usd == pytest.approx((2000 * 4 + 500 * 20 + 1000 * 0.2) / 1e6)


def test_anthropic_llm_refusal_and_truncation():
    with pytest.raises(llm.LLMRefusal):
        llm.AnthropicLLM({}, client=_FakeClient(_msg(None, stop="refusal"))).structured(
            task="x", system="s", content="c", schema=AssetAnalysis)
    with pytest.raises(llm.LLMError, match="tronquée"):
        llm.AnthropicLLM({}, client=_FakeClient(_msg(None, stop="max_tokens"))).structured(
            task="x", system="s", content="c", schema=AssetAnalysis)


def test_fake_llm_and_cost_record(jconn, clock):
    fake = llm.FakeLLM({"asset.describe": lambda req: _analysis()}, cost_usd=0.02)
    res = fake.structured(task="asset.describe", system="s", content="c", schema=AssetAnalysis)
    llm.record_cost(jconn, res, at=clock(), task="asset.describe", app_id="habitudo")
    assert costs.spent(jconn, costs.day_start(clock()), "habitudo") == pytest.approx(0.02)
    assert fake.calls[0].effort == "low"


def test_get_llm_without_key_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(llm, "keychain_secret", lambda service: None)
    monkeypatch.setattr(llm.Path, "home", lambda: tmp_path)
    cfg = SimpleNamespace(settings={})
    assert isinstance(llm.get_llm(cfg), llm.UnavailableLLM)
    assert isinstance(llm.get_llm(cfg, demo=True), llm.DemoLLM)
    with pytest.raises(llm.LLMUnavailable):
        llm.get_llm(cfg).structured(task="x", system="", content="", schema=AssetAnalysis)


def test_image_block_downscales(tmp_path):
    from PIL import Image

    path = tmp_path / "big.png"
    Image.new("RGB", (1290, 2796), (10, 20, 30)).save(path)
    block = llm.image_block(path)
    assert block["source"]["media_type"] == "image/jpeg"
    import base64
    import io
    img = Image.open(io.BytesIO(base64.b64decode(block["source"]["data"])))
    assert max(img.size) == 1568


# --- Formats et comptes ---------------------------------------------------------------------------------

def test_format_validation_messages():
    assert formats.validate("notes-app", {"title": "Mes 5 habitudes", "items": ["a", "b", "c"]}) == []
    errs = formats.validate("notes-app", {"title": "x" * 80, "items": ["a"]})
    assert any("60 au plus" in e for e in errs) and any("entre 3 et 7" in e for e in errs)
    assert formats.validate("inconnu", {}) == ["'format inconnu : inconnu'"]
    assert "hook-demo" in formats.catalog_for_prompt()


def test_accounts_sync(tmp_path):
    conn = db.connect(":memory:")
    cfg = Config(root=tmp_path, settings={}, farm=FarmSettings(), phones=[
        PhoneConfig("phone-1", "U1", lang="fr", apps=["habitudo"],
                    accounts={"tiktok": {"handle": "@h.fr", "created": "2026-11-01", "channel": "api_draft"},
                              "instagram": {"handle": "@h.fr", "created": "2026-11-01"}}),
        PhoneConfig("phone-2", None, lang="en", apps=[], accounts={}),
    ])
    assert accounts.sync_from_config(conn, cfg) == ["phone-1:tiktok", "phone-1:instagram"]
    accs = accounts.list_accounts(conn, app_id="habitudo")
    assert {a.platform for a in accs} == {"tiktok", "instagram"} and accs[0].lang == "fr"
    from datetime import date
    assert accs[0].age_days(date(2026, 11, 8)) == 7
    cfg.phones[0].accounts.pop("instagram")
    accounts.sync_from_config(conn, cfg)
    assert [a.id for a in accounts.list_accounts(conn)] == ["phone-1:tiktok"]


def test_unknown_kinds_never_block_known_ones(jconn, clock):
    with handlers(t_ok=(lambda ctx, p: None, {})):
        for i in range(250):
            jobs.enqueue(jconn, "module.absent", {"i": i}, clock=clock)
        jid = jobs.enqueue(jconn, "t.ok", clock=clock)
        assert jobs.run_one(jconn, None, "w", clock=clock).id == jid
        assert jconn.execute("SELECT COUNT(*) FROM jobs WHERE kind='module.absent' AND status='queued'").fetchone()[0] == 250
