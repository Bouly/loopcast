"""ideas.generate : idées validées, réparation unique, anti-doublon, ids lisibles, production enfilée."""

import itertools
import json

from loopcast import costs, jobs, llm
from loopcast.strategy import prompts, store, tasks

from .helpers import (APP, approve_strategy, batch, events, job_row, make_config, make_idea, make_strategy, run_jobs,
                      text_of)


_keys = itertools.count()


def _enqueue(conn, clock, phone="phone-1", count=3, key=None):
    return jobs.enqueue(conn, "ideas.generate", {"app_id": APP, "phone_id": phone, "count": count},
                        key=key or f"gen-{next(_keys)}", app_id=APP, clock=clock)


def _ideas(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM ideas ORDER BY id")]


def test_valid_ideas_are_stored_and_sent_to_production(sconn, sconfig, seeded, clock):
    strat = approve_strategy(sconn, clock())
    fake = llm.FakeLLM({"ideas.generate": batch(
        make_idea("Arrête de compter sur ta motivation"),
        make_idea("Ta to-do déborde dès 9 h ?", fmt="notes-app"),
        make_idea("Léa a tenu 40 soirs. Moi trois.", fmt="chat-story", pillar="Le problème vécu"))}, cost_usd=0.2)
    jid = _enqueue(sconn, clock)
    run_jobs(sconn, sconfig, clock, {"llm": fake}, kinds=("ideas.generate",))

    rows = _ideas(sconn)
    assert [r["id"] for r in rows] == [f"{APP}-fr-20261102-000{n}" for n in (1, 2, 3)]
    first = rows[0]
    assert (first["status"], first["phone_id"], first["account_id"], first["lang"]) == \
        ("approved", "phone-1", "phone-1:tiktok", "fr")
    assert first["strategy_id"] == strat.id and first["job_id"] == jid and first["parent_id"] is None
    assert json.loads(first["idea"])["phone_id"] == "phone-1"
    produce = [dict(r) for r in sconn.execute("SELECT * FROM jobs WHERE kind='content.produce' ORDER BY id")]
    assert [p["key"] for p in produce] == [f"content.produce:{r['id']}" for r in rows]
    assert json.loads(produce[0]["payload"]) == {"idea_id": rows[0]["id"]} and produce[0]["app_id"] == APP
    assert "3 idée(s) sur 3" in events(sconn, "ideas.generated")[0]
    assert costs.spent(sconn, costs.day_start(clock()), APP) == 0.2
    assert json.loads(job_row(sconn, jid)["result"])["ideas"] == [r["id"] for r in rows]

    req = fake.calls[0]
    body = text_of(req)
    assert prompts.section_json(body, "voix")["phone_id"] == "phone-1"
    assert prompts.section_json(body, "compte")["lang"] == "fr"
    assert prompts.section_json(body, "commande")["nombre"] == 3
    assert {v["phone_id"] for v in prompts.section_json(body, "autres_comptes")} == {"phone-2", "phone-3"}
    assert all(h["lang"] == "fr" for h in prompts.section_json(body, "strategie")["banque_d_accroches"])
    assert prompts.section_json(body, "a_ne_jamais_dire") == ["garanti", "meilleure app du monde"]
    assert "en anglais, concrets et filmables" in req.system and req.effort == "high"


def test_manual_review_keeps_ideas_proposed(sconn, tmp_path, seeded, clock):
    approve_strategy(sconn, clock())
    config = make_config(tmp_path, {"pipeline": {"idea_review": "manual"}})
    run_ideas = {"llm": llm.FakeLLM({"ideas.generate": batch(make_idea())})}
    _enqueue(sconn, clock)
    run_jobs(sconn, config, clock, run_ideas, kinds=("ideas.generate",))
    assert [r["status"] for r in _ideas(sconn)] == ["proposed"]
    assert sconn.execute("SELECT COUNT(*) FROM jobs WHERE kind='content.produce'").fetchone()[0] == 0


def test_an_invalid_idea_gets_one_repair(sconn, sconfig, seeded, clock):
    approve_strategy(sconn, clock())
    broken = make_idea("Coche ton soir en trois secondes", props_json=json.dumps(
        {"hook": "Coche ton soir", "screens": [{"caption": "a", "asset_id": 1}] * 5}))
    fake = llm.FakeLLM({"ideas.generate": batch(make_idea(), broken),
                        "ideas.repair": batch(make_idea("Coche ton soir en trois secondes"))})
    jid = _enqueue(sconn, clock, count=2)
    run_jobs(sconn, sconfig, clock, {"llm": fake}, kinds=("ideas.generate",))

    assert [c.task for c in fake.calls] == ["ideas.generate", "ideas.repair"]
    to_fix = prompts.section_json(text_of(fake.calls[1]), "idees_a_corriger")
    assert to_fix[0]["erreurs"] == ["props_json.screens : 5 éléments, entre 2 et 4 attendus"]
    assert fake.calls[1].effort == "medium" and fake.calls[1].system == fake.calls[0].system   # même cache
    assert len(_ideas(sconn)) == 2
    result = json.loads(job_row(sconn, jid)["result"])
    assert (result["repaired"], result["abandoned"]) == (1, 0)


def test_an_idea_still_invalid_after_repair_is_abandoned(sconn, sconfig, seeded, clock):
    approve_strategy(sconn, clock())
    english = make_idea("Stop relying on motivation", lang="en")
    fake = llm.FakeLLM({"ideas.generate": batch(make_idea(), english), "ideas.repair": batch(english)})
    _enqueue(sconn, clock, count=2)
    run_jobs(sconn, sconfig, clock, {"llm": fake}, kinds=("ideas.generate",))

    assert [r["hook"] for r in _ideas(sconn)] == ["Arrête de compter sur ta motivation"]
    abandoned = events(sconn, "ideas.abandoned")
    assert len(abandoned) == 1 and "Stop relying on motivation" in abandoned[0] and "publie en « fr »" in abandoned[0]


def test_repair_that_cannot_run_keeps_the_good_ideas(sconn, sconfig, seeded, clock):
    approve_strategy(sconn, clock())

    def refuse(req):
        raise llm.LLMRefusal("Claude a décliné")

    fake = llm.FakeLLM({"ideas.generate": batch(make_idea(), make_idea("Hook trop long " * 10)),
                        "ideas.repair": refuse})
    jid = _enqueue(sconn, clock, count=2)
    run_jobs(sconn, sconfig, clock, {"llm": fake}, kinds=("ideas.generate",))
    assert job_row(sconn, jid)["status"] == "done" and len(_ideas(sconn)) == 1
    assert "réparation impossible" in events(sconn, "ideas.abandoned")[0]


def test_duplicate_hooks_are_dropped(sconn, sconfig, seeded, clock):
    approve_strategy(sconn, clock())
    _enqueue(sconn, clock, count=1)
    run_jobs(sconn, sconfig, clock, {"llm": llm.FakeLLM({"ideas.generate": batch(make_idea())})},
             kinds=("ideas.generate",))
    clock.advance(hours=1)
    fake = llm.FakeLLM({"ideas.generate": batch(
        make_idea("arrête de compter sur ta motivation !! 🙃"),           # déjà utilisée (une autre tâche)
        make_idea("Personne ne parle de la coche du soir", fmt="notes-app"),
        make_idea("Personne ne parle de la coche du soir…", fmt="slideshow"))})   # doublon dans le lot
    jid = _enqueue(sconn, clock, count=3)
    run_jobs(sconn, sconfig, clock, {"llm": fake}, kinds=("ideas.generate",))

    hooks = [r["hook"] for r in _ideas(sconn)]
    assert hooks == ["Arrête de compter sur ta motivation", "Personne ne parle de la coche du soir"]
    assert [c.task for c in fake.calls] == ["ideas.generate"]           # un doublon ne se répare pas
    dup = events(sconn, "ideas.duplicate")
    assert len(dup) == 2 and "trop proche de « Arrête de compter sur ta motivation »" in dup[0]
    assert json.loads(job_row(sconn, jid)["result"])["duplicates"] == 2
    used = prompts.section_json(text_of(fake.calls[0]), "accroches_deja_utilisees")
    assert used == ["Arrête de compter sur ta motivation"]


def test_duplicates_are_judged_within_the_account_language(sconn, sconfig, seeded, clock):
    approve_strategy(sconn, clock())
    _enqueue(sconn, clock, count=1)
    run_jobs(sconn, sconfig, clock, {"llm": llm.FakeLLM({"ideas.generate": batch(make_idea("POV : habitudes"))})},
             kinds=("ideas.generate",))
    english = llm.FakeLLM({"ideas.generate": batch(make_idea("POV: habits", lang="en", phone="phone-2",
                                                             fmt="slideshow"))})
    _enqueue(sconn, clock, phone="phone-2", count=1)
    run_jobs(sconn, sconfig, clock, {"llm": english}, kinds=("ideas.generate",))
    assert [r["hook"] for r in _ideas(sconn)] == ["POV: habits", "POV : habitudes"]   # mots voisins, pas un doublon
    assert prompts.section(text_of(english.calls[0]), "accroches_deja_utilisees") == "Aucune pour l'instant."


def test_ids_follow_the_day_and_language(sconn, sconfig, seeded, clock):
    approve_strategy(sconn, clock())
    hooks = iter(["Ta motivation lâche le mercredi ?", "POV : la coche du soir te sauve",
                  "Personne ne t'a dit ça sur les routines"])
    fake = llm.FakeLLM({"ideas.generate": lambda req: batch(make_idea(next(hooks)))(req)})
    english = llm.FakeLLM({"ideas.generate": batch(make_idea("Stop relying on motivation", lang="en",
                                                             phone="phone-2", fmt="slideshow"))})
    for phone, service in (("phone-1", fake), ("phone-1", fake), ("phone-2", english)):
        _enqueue(sconn, clock, phone=phone, count=1)
        run_jobs(sconn, sconfig, clock, {"llm": service}, kinds=("ideas.generate",))
    clock.advance(days=1)
    _enqueue(sconn, clock, count=1)
    run_jobs(sconn, sconfig, clock, {"llm": fake}, kinds=("ideas.generate",))
    assert [r["id"] for r in _ideas(sconn)] == [f"{APP}-en-20261102-0001", f"{APP}-fr-20261102-0001",
                                                f"{APP}-fr-20261102-0002", f"{APP}-fr-20261103-0001"]


def test_replayed_job_does_not_duplicate_ideas(sconn, sconfig, seeded, clock):
    approve_strategy(sconn, clock())
    fake = llm.FakeLLM({"ideas.generate": batch(make_idea())})
    _enqueue(sconn, clock, count=1)
    job = jobs.claim(sconn, "w", clock=clock)
    ctx = jobs.JobContext(sconn, sconfig, job, clock, {"llm": fake})
    first = tasks.generate_ideas(ctx, job.payload)
    again = tasks.generate_ideas(ctx, job.payload)
    assert again == {"ideas": first["ideas"], "reused": True}
    assert len(fake.calls) == 1 and len(_ideas(sconn)) == 1


def test_missing_prerequisites_fail_permanently(sconn, sconfig, seeded, clock):
    fake = llm.FakeLLM({"ideas.generate": batch(make_idea())})
    no_strategy = _enqueue(sconn, clock, key="a")
    run_jobs(sconn, sconfig, clock, {"llm": fake})
    assert "aucune stratégie approuvée" in job_row(sconn, no_strategy)["last_error"]

    approve_strategy(sconn, clock(), strategy=None)
    unknown = _enqueue(sconn, clock, phone="phone-9", key="b")
    other_app = _enqueue(sconn, clock, phone="phone-4", key="c")
    run_jobs(sconn, sconfig, clock, {"llm": fake})
    assert "phone-9" in job_row(sconn, unknown)["last_error"]
    assert "ne promeut pas habitudo" in job_row(sconn, other_app)["last_error"]
    assert fake.calls == []


def test_phone_without_voice_is_reported(sconn, sconfig, seeded, clock):
    approve_strategy(sconn, clock(), make_strategy(phones=(("phone-1", "fr"), ("phone-2", "en"))))
    jid = _enqueue(sconn, clock, phone="phone-3")
    run_jobs(sconn, sconfig, clock, {"llm": llm.FakeLLM({})})
    assert "n'a pas de voix pour phone-3" in job_row(sconn, jid)["last_error"]


def test_team_rejections_feed_the_next_batch(sconn, sconfig, seeded, clock):
    approve_strategy(sconn, clock())
    _enqueue(sconn, clock, count=1)
    run_jobs(sconn, sconfig, clock, {"llm": llm.FakeLLM({"ideas.generate": batch(make_idea())})},
             kinds=("ideas.generate",))
    (idea_id,) = [r["id"] for r in _ideas(sconn)]
    store.reject_idea(sconn, idea_id, "Ton trop moralisateur", clock())
    fake = llm.FakeLLM({"ideas.generate": batch(make_idea("POV : la coche du soir"))})
    _enqueue(sconn, clock, count=1)
    run_jobs(sconn, sconfig, clock, {"llm": fake}, kinds=("ideas.generate",))
    history = prompts.section_json(text_of(fake.calls[0]), "historique_du_compte")
    assert history["refusees_par_l_equipe"] == [
        {"hook": "Arrête de compter sur ta motivation", "format": "hook-demo", "raison": "Ton trop moralisateur"}]


def test_count_is_bounded(sconn, sconfig, seeded, clock):
    approve_strategy(sconn, clock())
    fake = llm.FakeLLM({"ideas.generate": batch(make_idea())})
    _enqueue(sconn, clock, count=50)
    run_jobs(sconn, sconfig, clock, {"llm": fake}, kinds=("ideas.generate",))
    assert prompts.section_json(text_of(fake.calls[0]), "commande")["nombre"] == store.MAX_BATCH
