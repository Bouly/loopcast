"""ideas.variations : un gagnant → nouvelle accroche, nouvel angle, autre format, rattachés au gagnant."""

import itertools
import json

import pytest

from loopcast import jobs, llm
from loopcast.strategy import prompts, store

from .helpers import APP, approve_strategy, batch, events, job_row, make_idea, run_jobs, text_of

WIN_HOOK = "Arrête de compter sur ta motivation"
_keys = itertools.count()


@pytest.fixture
def winner(sconn, seeded, clock):
    strat = approve_strategy(sconn, clock())
    phone = type("P", (), {"id": "phone-1", "accounts": {"tiktok": {}}})()
    with store.transaction(sconn):
        (idea_id,) = store.insert_ideas(sconn, app_id=APP, strategy_id=strat.id, phone=phone,
                                        ideas=[make_idea(WIN_HOOK)], status="produced", now=clock(), job_id=None)
    sconn.execute("""INSERT INTO content(id, app_id, idea_id, account_id, format, lang, status, caption)
                     VALUES ('c-win', ?, ?, 'phone-1:tiktok', 'hook-demo', 'fr', 'approved', 'Légende')""",
                  (APP, idea_id))
    for content_id, platform, views in (("c-win", "tiktok", 12000), ("c-win", "instagram", 3000)):
        sconn.execute("""INSERT INTO posts(content_id, account_id, platform, status, views, likes, posted_at)
                         VALUES (?,?,?,'posted',?,?,?)""",
                      (content_id, f"phone-1:{platform}", platform, views, views // 10, jobs.iso(clock())))
    return idea_id


def _run(sconn, sconfig, clock, fake, content_id="c-win"):
    jid = jobs.enqueue(sconn, "ideas.variations", {"content_id": content_id}, key=f"var-{next(_keys)}", clock=clock)
    run_jobs(sconn, sconfig, clock, {"llm": fake}, kinds=("ideas.variations",))
    return job_row(sconn, jid)


def _variations(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM ideas WHERE parent_id='c-win' ORDER BY id")]


GOOD = (make_idea("Ta motivation ne tiendra pas jusqu'à jeudi"),
        make_idea("Le soir où j'ai lâché mes quinze habitudes", pillar="Le problème vécu"),
        make_idea(WIN_HOOK, fmt="notes-app"))                   # autre format : l'accroche gagnante peut rester


def test_three_variations_are_linked_to_the_winner(sconn, sconfig, winner, clock):
    fake = llm.FakeLLM({"ideas.variations": batch(*GOOD)})
    row = _run(sconn, sconfig, clock, fake)

    assert row["status"] == "done"
    ideas = _variations(sconn)
    assert [i["format"] for i in ideas] == ["hook-demo", "hook-demo", "notes-app"]
    titles = [json.loads(i["idea"])["title"] for i in ideas]
    assert [t.split(" · ")[0] for t in titles] == ["Variation (accroche)", "Variation (angle)", "Variation (format)"]
    assert all(i["status"] == "approved" and i["phone_id"] == "phone-1" for i in ideas)
    keys = {r["key"] for r in sconn.execute("SELECT key FROM jobs WHERE kind='content.produce'")}
    assert keys == {f"content.produce:{i['id']}" for i in ideas}
    assert "3 variation(s) du gagnant c-win" in events(sconn, "ideas.generated")[-1]

    call = fake.calls[0]
    winner_section = prompts.section_json(text_of(call), "gagnant")
    assert (winner_section["vues"], winner_section["hook"], winner_section["format"]) == (12000, WIN_HOOK, "hook-demo")
    assert winner_section["idee"]["hook"] == WIN_HOOK
    assert call.effort == "high" and call.system == prompts.ideas_system()


def test_variations_are_made_once_per_winner(sconn, sconfig, winner, clock):
    fake = llm.FakeLLM({"ideas.variations": batch(*GOOD)})
    _run(sconn, sconfig, clock, fake)
    again = _run(sconn, sconfig, clock, fake)
    assert json.loads(again["result"])["reused"] is True and len(fake.calls) == 1
    assert len(_variations(sconn)) == 3


def test_variation_rules_are_enforced_through_one_repair(sconn, sconfig, winner, clock):
    same_format = make_idea("Une coche, un soir, une série", fmt="hook-demo")
    kept_hook = make_idea(WIN_HOOK + " !")                           # « nouvelle accroche » qui n'en est pas une
    fake = llm.FakeLLM({"ideas.variations": batch(kept_hook, GOOD[1], same_format),
                        "ideas.repair": batch(make_idea("Trois soirs sans coche : et alors ?"),
                                              make_idea("Une coche, un soir, une série", fmt="slideshow"))})
    row = _run(sconn, sconfig, clock, fake)

    assert row["status"] == "done" and [c.task for c in fake.calls] == ["ideas.variations", "ideas.repair"]
    errors = [e for item in prompts.section_json(text_of(fake.calls[1]), "idees_a_corriger") for e in item["erreurs"]]
    assert any("l'accroche doit être nouvelle" in e for e in errors)
    assert any("changer de format" in e for e in errors)
    ideas = _variations(sconn)
    labels = {json.loads(i["idea"])["title"].split(" · ")[0]: i["format"] for i in ideas}
    assert labels == {"Variation (accroche)": "hook-demo", "Variation (angle)": "hook-demo",
                      "Variation (format)": "slideshow"}


def test_unknown_content_fails_permanently(sconn, sconfig, winner, clock):
    row = _run(sconn, sconfig, clock, llm.FakeLLM({}), content_id="nope")
    assert row["status"] == "dead" and "« nope » introuvable" in row["last_error"]
