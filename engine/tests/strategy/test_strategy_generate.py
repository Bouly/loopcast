"""strategy.generate : versions, contrôles, seconde chance, approbation, idempotence, budget."""

import json

import pytest

from loopcast import costs, jobs, llm
from loopcast.schemas import AccountVoice
from loopcast.strategy import prompts, store, tasks

from .helpers import (APP, add_brief, approve_strategy, events, job_row, make_config, make_strategy, run_jobs,
                      sequence, text_of)


def _enqueue(conn, clock, brief_id, key="k1", **extra):
    return jobs.enqueue(conn, "strategy.generate", {"app_id": APP, "brief_id": brief_id, **extra}, key=key,
                        app_id=APP, clock=clock)


def test_generation_creates_a_draft_and_marks_the_app_ready(sconn, sconfig, seeded, clock):
    fake = llm.FakeLLM({"strategy.generate": lambda req: make_strategy()}, cost_usd=0.12)
    jid = _enqueue(sconn, clock, seeded["brief_id"])
    run_jobs(sconn, sconfig, clock, {"llm": fake})

    assert job_row(sconn, jid)["status"] == "done"
    rec = store.strategy_for_job(sconn, jid)
    assert (rec.version, rec.status, rec.brief_id) == (1, "draft", seeded["brief_id"])
    assert [v.phone_id for v in rec.strategy.voices] == ["phone-1", "phone-2", "phone-3"]
    assert store.get_app(sconn, APP)["status"] == "strategy_ready"
    assert "v1 prête à valider" in events(sconn, "strategy.generated")[0]
    assert costs.spent(sconn, costs.day_start(clock()), APP) == pytest.approx(0.12)
    assert sconn.execute("SELECT COUNT(*) FROM jobs WHERE kind='ideas.ensure_stock'").fetchone()[0] == 0

    req = fake.calls[0]
    body = text_of(req)
    phones = prompts.section_json(body, "telephones")
    assert [(p["phone_id"], p["lang"]) for p in phones] == [("phone-1", "fr"), ("phone-2", "en"), ("phone-3", "fr")]
    assert "phone-4" not in body                                   # téléphone d'une autre app
    assert "`hook-demo`" in prompts.section(body, "catalogue_formats")
    captures = prompts.section_json(body, "captures")
    assert {c["asset_id"] for c in captures} == {1, 2, 3}
    assert next(c for c in captures if c["asset_id"] == 2)["usable_in_video"] is False
    assert "meilleure app du monde" in body                       # do_not_say de la fiche
    assert prompts.section_json(body, "cadence_et_budget")["posts_par_jour_et_par_compte"] == 3
    assert "Ne promets rien que l'app ne fait pas" in req.system and "<playbook>" in req.system
    assert prompts.FALLBACK_PLAYBOOK.splitlines()[0] in req.system   # pas de playbook : le repli
    assert req.effort == "high"


def test_playbook_is_read_at_call_time(sconn, sconfig, seeded, clock, no_playbook):
    (no_playbook / "playbook.md").write_text("# Savoir-faire\nToujours montrer la série dès la 2e seconde.")
    fake = llm.FakeLLM({"strategy.generate": lambda req: make_strategy()})
    _enqueue(sconn, clock, seeded["brief_id"])
    run_jobs(sconn, sconfig, clock, {"llm": fake})
    system = fake.calls[0].system
    assert "Toujours montrer la série dès la 2e seconde." in system
    assert prompts.FALLBACK_PLAYBOOK.splitlines()[0] not in system


def test_regeneration_creates_v2_and_keeps_the_current_strategy(sconn, sconfig, seeded, clock):
    v1 = approve_strategy(sconn, clock())
    fake = llm.FakeLLM({"strategy.generate": lambda req: make_strategy(positioning="Nouvelle version")})
    jid = _enqueue(sconn, clock, seeded["brief_id"], key="relance", note="Plus d'humour sur le compte EN")
    run_jobs(sconn, sconfig, clock, {"llm": fake})

    v2 = store.strategy_for_job(sconn, jid)
    assert (v2.version, v2.status) == (2, "draft") and "Plus d'humour" in v2.note
    assert store.current_strategy(sconn, APP).id == v1.id             # la v1 reste en vigueur
    assert store.get_app(sconn, APP)["status"] == "active"             # on ne coupe pas la diffusion
    body = text_of(fake.calls[0])
    assert prompts.section_json(body, "strategie_en_vigueur")["positioning"] == v1.strategy.positioning
    assert prompts.section(body, "consignes_equipe") == "Plus d'humour sur le compte EN"


def test_wrong_language_and_unknown_format_get_a_second_chance(sconn, sconfig, seeded, clock):
    bad = make_strategy()
    bad.voices[1] = bad.voices[1].model_copy(update={"lang": "fr"})
    bad.formats[0] = bad.formats[0].model_copy(update={"format": "faux-format"})
    fake = llm.FakeLLM({"strategy.generate": sequence(bad, make_strategy())})
    jid = _enqueue(sconn, clock, seeded["brief_id"])
    run_jobs(sconn, sconfig, clock, {"llm": fake})

    assert job_row(sconn, jid)["status"] == "done" and len(fake.calls) == 2
    problems = prompts.section_json(text_of(fake.calls[1]), "problemes")
    assert any("phone-2 publie en « en »" in p for p in problems)
    assert any("faux-format" in p for p in problems)
    assert store.strategy_for_job(sconn, jid).strategy.voices[1].lang == "en"


def test_strategy_still_missing_a_voice_fails_with_a_clear_message(sconn, sconfig, seeded, clock):
    incomplete = make_strategy(phones=(("phone-1", "fr"), ("phone-2", "en")))
    fake = llm.FakeLLM({"strategy.generate": lambda req: incomplete})
    jid = _enqueue(sconn, clock, seeded["brief_id"])
    run_jobs(sconn, sconfig, clock, {"llm": fake})

    row = job_row(sconn, jid)
    assert row["status"] == "dead" and "il manque la voix de phone-3" in row["last_error"]
    assert len(fake.calls) == 2
    assert sconn.execute("SELECT COUNT(*) FROM strategies").fetchone()[0] == 0


def test_reserves_are_noted_and_block_auto_approval(sconn, tmp_path, seeded, clock):
    config = make_config(tmp_path, {"pipeline": {"auto_approve_strategy": True}})
    twins = make_strategy()
    twins.voices[2] = twins.voices[0].model_copy(update={"phone_id": "phone-3", "bio": "Autre bio"})
    fake = llm.FakeLLM({"strategy.generate": lambda req: twins})
    jid = _enqueue(sconn, clock, seeded["brief_id"])
    run_jobs(sconn, config, clock, {"llm": fake})

    rec = store.strategy_for_job(sconn, jid)
    assert rec.status == "draft" and "à vérifier" in rec.note and "se ressemblent trop" in rec.note
    assert json.loads(job_row(sconn, jid)["result"])["approved"] is False


def test_a_worse_correction_does_not_replace_a_usable_proposal(sconn, sconfig, seeded, clock):
    few_hooks = make_strategy(positioning="Première", hooks=make_strategy().hooks[:7])     # 1 accroche en « en »
    broken = make_strategy(phones=(("phone-1", "fr"),))
    fake = llm.FakeLLM({"strategy.generate": sequence(few_hooks, broken)})
    jid = _enqueue(sconn, clock, seeded["brief_id"])
    run_jobs(sconn, sconfig, clock, {"llm": fake})
    rec = store.strategy_for_job(sconn, jid)
    assert rec.strategy.positioning == "Première" and "1 accroche(s) en « en »" in rec.note


def test_auto_approval_activates_the_app_and_asks_for_stock(sconn, tmp_path, seeded, clock):
    config = make_config(tmp_path, {"pipeline": {"auto_approve_strategy": True}})
    fake = llm.FakeLLM({"strategy.generate": lambda req: make_strategy()})
    jid = _enqueue(sconn, clock, seeded["brief_id"])
    run_jobs(sconn, config, clock, {"llm": fake}, kinds=("strategy.",))

    rec = store.strategy_for_job(sconn, jid)
    assert rec.status == "approved" and store.get_app(sconn, APP)["status"] == "active"
    stock = sconn.execute("SELECT * FROM jobs WHERE kind='ideas.ensure_stock'").fetchone()
    assert stock["key"] == f"ideas.ensure_stock:{APP}:strategy-{rec.id}"


def test_job_for_an_outdated_brief_is_skipped(sconn, sconfig, seeded, clock):
    add_brief(sconn, clock(), version=2)
    fake = llm.FakeLLM({"strategy.generate": lambda req: make_strategy()})
    jid = _enqueue(sconn, clock, seeded["brief_id"])
    run_jobs(sconn, sconfig, clock, {"llm": fake})
    assert "remplacée par la v2" in json.loads(job_row(sconn, jid)["result"])["skipped"]
    assert fake.calls == []


def test_unapproved_brief_and_unassigned_app_fail_permanently(sconn, tmp_path, seeded, clock):
    draft_brief = add_brief(sconn, clock(), version=2, approved=False)
    fake = llm.FakeLLM({"strategy.generate": lambda req: make_strategy()})
    j1 = _enqueue(sconn, clock, draft_brief, key="a")
    j2 = _enqueue(sconn, clock, seeded["brief_id"], key="b")
    run_jobs(sconn, make_config(tmp_path, phones=[]), clock, {"llm": fake})
    assert "non approuvée" in job_row(sconn, j1)["last_error"]
    assert "aucun téléphone" in job_row(sconn, j2)["last_error"]
    assert job_row(sconn, j2)["status"] == "dead" and fake.calls == []


def test_replayed_job_reuses_what_it_wrote(sconn, sconfig, seeded, clock):
    fake = llm.FakeLLM({"strategy.generate": lambda req: make_strategy()})
    jid = _enqueue(sconn, clock, seeded["brief_id"])
    job = jobs.claim(sconn, "w", clock=clock)
    ctx = jobs.JobContext(sconn, sconfig, job, clock, {"llm": fake})
    first = tasks.generate_strategy(ctx, job.payload)
    again = tasks.generate_strategy(ctx, job.payload)        # bail expiré : la tâche repart
    assert again == {"strategy_id": first["strategy_id"], "version": 1, "reused": True}
    assert len(fake.calls) == 1 and sconn.execute("SELECT COUNT(*) FROM strategies").fetchone()[0] == 1
    assert jid == job.id


def test_budget_exhausted_waits_without_using_an_attempt(sconn, tmp_path, seeded, clock):
    config = make_config(tmp_path, {"budget": {"daily_usd_per_app": 0.1}})
    fake = llm.FakeLLM({"strategy.generate": lambda req: make_strategy()})
    jid = _enqueue(sconn, clock, seeded["brief_id"])
    run_jobs(sconn, config, clock, {"llm": fake})
    row = job_row(sconn, jid)
    assert row["status"] == "queued" and row["attempts"] == 0 and row["run_after"] > jobs.iso(clock())
    assert fake.calls == [] and "plafond du jour pour habitudo" in events(sconn, "strategy.budget")[0]


def test_llm_refusal_is_permanent(sconn, sconfig, seeded, clock):
    def refuse(req):
        raise llm.LLMRefusal("Claude a décliné (cyber)")

    jid = _enqueue(sconn, clock, seeded["brief_id"])
    run_jobs(sconn, sconfig, clock, {"llm": llm.FakeLLM({"strategy.generate": refuse})})
    row = job_row(sconn, jid)
    assert row["status"] == "dead" and "décliné" in row["last_error"]


# --- Approbation ---------------------------------------------------------------------------------------------

def _insert(conn, clock, **over):
    with store.transaction(conn):
        return store.insert_strategy(conn, app_id=APP, brief_id=1, strategy=make_strategy(**over), model="m",
                                     now=clock())


def test_approval_archives_the_previous_version_and_asks_for_stock(sconn, seeded, clock):
    v1, v2, v3 = (_insert(sconn, clock) for _ in range(3))
    store.approve_strategy(sconn, v1.id, clock())
    result = store.approve_strategy(sconn, v2.id, clock())

    statuses = {r.version: r.status for r in store.strategy_versions(sconn, APP)}
    assert statuses == {1: "archived", 2: "approved", 3: "draft"}
    assert store.get_app(sconn, APP)["status"] == "active"
    assert store.latest_draft(sconn, APP).id == v3.id
    assert job_row(sconn, result["ensure_stock_job"])["key"] == f"ideas.ensure_stock:{APP}:strategy-{v2.id}"
    assert "v2 approuvée" in events(sconn, "strategy.approved")[-1]

    again = store.approve_strategy(sconn, v2.id, clock())          # idempotent
    assert again["already"] and again["ensure_stock_job"] == result["ensure_stock_job"]
    with pytest.raises(store.Conflict, match="archivée"):
        store.approve_strategy(sconn, v1.id, clock())


def test_approval_keeps_a_paused_app_paused(sconn, seeded, clock):
    sconn.execute("UPDATE apps SET status='paused'")
    store.approve_strategy(sconn, _insert(sconn, clock).id, clock())
    assert store.get_app(sconn, APP)["status"] == "paused"


def test_editing_an_approved_version_creates_a_new_draft(sconn, seeded, clock):
    v1 = _insert(sconn, clock)
    store.approve_strategy(sconn, v1.id, clock())
    edited = make_strategy(positioning="Édité à la main")
    v2 = store.save_edit(sconn, store.strategy_by_id(sconn, v1.id), edited, clock(), "édition manuelle")
    assert (v2.version, v2.status) == (2, "draft")
    assert store.current_strategy(sconn, APP).strategy.positioning != "Édité à la main"
    v2b = store.save_edit(sconn, v2, make_strategy(positioning="Retouché"), clock(), None)
    assert (v2b.id, v2b.strategy.positioning) == (v2.id, "Retouché")


def test_voice_lookup():
    s = make_strategy()
    assert isinstance(store.voice_for(s, "phone-2"), AccountVoice)
    assert store.voice_for(s, "phone-9") is None
