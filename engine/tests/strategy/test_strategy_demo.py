"""Mode démo (serve --demo, sans clé) : tout le parcours stratégie → idées → variations, réponses valides."""

import json

from loopcast import jobs, llm
from loopcast.schemas import IdeaBatch, Strategy
from loopcast.strategy import prompts, store, validate

from .helpers import APP, events, make_idea, run_jobs


def _ideas(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM ideas ORDER BY id")]


def test_demo_runs_the_whole_flow(sconn, sconfig, seeded, clock):
    demo = {"llm": llm.DemoLLM()}
    jobs.enqueue(sconn, "strategy.generate", {"app_id": APP, "brief_id": seeded["brief_id"]}, key="s", clock=clock)
    run_jobs(sconn, sconfig, clock, demo)

    rec = store.latest_draft(sconn, APP)
    _, blocking, warnings = validate.check_strategy(rec.strategy, [p for p in sconfig.phones if APP in p.apps])
    assert rec.version == 1 and blocking == [] and warnings == []
    assert sconn.execute("SELECT COUNT(*) FROM cost_ledger").fetchone()[0] == 0          # la démo ne coûte rien

    store.approve_strategy(sconn, rec.id, clock())
    for round_ in range(3):                                         # trois journées de stock
        run_jobs(sconn, sconfig, clock, demo)
        sconn.execute("UPDATE ideas SET status='produced'")          # la production a tout pris
        clock.advance(hours=1)
        jobs.enqueue(sconn, "ideas.ensure_stock", {"app_id": APP}, key=f"stock-{round_}", clock=clock)
    ideas = _ideas(sconn)
    assert len(ideas) == 3 * 3 * 6                                   # 3 tours × 3 téléphones × 6 idées
    assert events(sconn, "ideas.duplicate") == [] and events(sconn, "ideas.abandoned") == []
    assert {(i["phone_id"], i["lang"]) for i in ideas} == {("phone-1", "fr"), ("phone-2", "en"), ("phone-3", "fr")}
    assert len({validate.fold(i["hook"]) for i in ideas}) == len(ideas)
    used_assets = {s.get("asset_id") for i in ideas if i["format"] == "hook-demo"
                   for s in json.loads(json.loads(i["idea"])["props_json"])["screens"]}
    assert 1 in used_assets and not used_assets & {2, 3}              # jamais la capture privée ni la vidéo
    assert sconn.execute("SELECT COUNT(*) FROM jobs WHERE kind='content.produce'").fetchone()[0] == len(ideas)


def test_demo_repair_and_variations_are_valid(sconn, sconfig, seeded, clock):
    demo = llm.DemoLLM()
    strategy = demo.structured(task="strategy.generate", system="", schema=Strategy, content=prompts.tag(
        "telephones", [{"phone_id": "phone-1", "lang": "fr"}])).data
    with store.transaction(sconn):
        rec = store.insert_strategy(sconn, app_id=APP, brief_id=1, strategy=strategy, model="démo", now=clock())
    store.approve_strategy(sconn, rec.id, clock())
    phone = sconfig.phone_by_id("phone-1")
    brief = store.approved_brief(sconn, APP)
    assets = store.app_assets(sconn, APP)
    check = store.idea_context(brief.brief, strategy, phone, assets)
    context = prompts.idea_context(phone=phone, voice=strategy.voices[0], strategy=strategy, brief=brief.brief,
                                   assets=assets, used_hooks=[], history={})

    broken = make_idea(fmt="slideshow", props_json="{}")
    repaired = demo.structured(task="ideas.repair", system="", schema=IdeaBatch,
                               content=context + prompts.repair_order([(broken, ["props_json : vide"])])).data
    assert len(repaired.ideas) == 1 and repaired.ideas[0].format == "slideshow"
    assert validate.validate_idea(validate.normalize_idea(repaired.ideas[0], check), check) == []

    with store.transaction(sconn):
        (idea_id,) = store.insert_ideas(sconn, app_id=APP, strategy_id=rec.id, phone=phone, ideas=[make_idea()],
                                        status="produced", now=clock(), job_id=None)
    sconn.execute("""INSERT INTO content(id, app_id, idea_id, account_id, format, lang, status)
                     VALUES ('c1', ?, ?, 'phone-1:tiktok', 'hook-demo', 'fr', 'approved')""", (APP, idea_id))
    jobs.enqueue(sconn, "ideas.variations", {"content_id": "c1"}, key="v", clock=clock)
    run_jobs(sconn, sconfig, clock, {"llm": demo}, kinds=("ideas.variations",))
    variations = [i for i in _ideas(sconn) if i["parent_id"] == "c1"]
    formats_ = [v["format"] for v in variations]
    assert formats_[:2] == ["hook-demo", "hook-demo"] and formats_[2] != "hook-demo"
    assert events(sconn, "ideas.abandoned") == []
