"""Mode démo (serve --demo, sans clé) : tout le parcours tourne, avec des réponses tirées de l'app demandée."""

import io

import pytest

from loopcast import llm
from loopcast.apps import assets, sources, store

from .helpers import IOS, png, record


@pytest.fixture
def demo(services):
    services["llm"] = llm.DemoLLM()
    return services["llm"]


def test_demo_flow_for_habitudo(aconn, cfg, clock, demo, run, with_brand):
    store.create_app(aconn, cfg, now=clock(), app_id="habitudo")
    shots = [assets.store_asset(aconn, cfg, "habitudo", io.BytesIO(png(300, 650, (i, 0, 0))), f"{i}.png",
                                now=clock())[0] for i in range(3)]
    store.request_analysis(aconn, "habitudo", now=clock())
    run()
    clock.advance(seconds=16)
    run()

    described = [assets.get_asset(aconn, "habitudo", s["id"])["analysis"] for s in shots]
    assert all(d and d["usable_in_video"] for d in described)
    assert {d["screen"] for d in described} <= {"aujourd'hui : les 3 habitudes du jour", "série de jours",
                                                "rappel du soir", "ajout d'une habitude", "statistiques du mois"}
    v1 = store.latest_brief(aconn, "habitudo")
    b = v1["brief"]
    assert b["app_name"] == "Habitudo" and b["one_liner"]["fr"] and b["one_liner"]["en"]
    assert b["features"][0]["asset_ids"] == [shots[0]["id"]] and b["proof_points"] == []
    questions = store.list_questions(aconn, "habitudo", "open")
    assert len(questions) == 4 and questions[0]["priority"] == "bloquante"
    assert "offre payante" in questions[0]["question"]
    assert store.get_app(aconn, "habitudo")["status"] == "questions"

    answers = {q["id"]: a for q, a in zip(questions, ["Gratuit, premium à 2,99 €/mois", "Étudiants (18-24 ans)",
                                                      "Pas encore", "Les statistiques, encore en bêta"])}
    assert store.answer_questions(aconn, "habitudo", now=clock(), answers=answers)["refine_job"]
    run()
    v2 = store.latest_brief(aconn, "habitudo")["brief"]
    assert v2["pricing"] == "Gratuit, premium à 2,99 €/mois (réponse de l'équipe)"
    assert "Montrer : Les statistiques, encore en bêta" in v2["do_not_say"]
    assert "Étudiants (18-24 ans)" in v2["personas"][0]["description"]
    assert v2["confidence"] > b["confidence"]
    assert store.get_app(aconn, "habitudo")["status"] == "brief_ready"
    assert store.approve_brief(aconn, "habitudo", now=clock())["strategy_job"]
    assert aconn.execute("SELECT COUNT(*) FROM cost_ledger").fetchone()[0] == 0    # la démo ne coûte rien


def test_demo_answers_follow_the_app_given(aconn, cfg, clock, demo, run):
    store.create_app(aconn, cfg, now=clock(), app_id="frigo", name="Frigo Malin", langs=["fr"],
                     description="Des recettes de 15 minutes avec ce qu'il reste dans le frigo. Fini le gaspillage "
                                 "et les soirs sans idée. Trois recettes à partir de tes ingrédients, en un geste.")
    src, _ = store.add_source(aconn, "frigo", now=clock(), url=IOS)
    fetched = sources.appstore_source({"fr": record("fr", trackName="Frigo Malin", genres=["Cuisine et boissons"],
                                                    averageUserRating=4.62, userRatingCount=2345)},
                                      max_chars=20_000, now=clock())
    store.source_ok(aconn, src["id"], now=clock(), title=fetched.title, content=fetched.content, meta=fetched.meta)
    aconn.execute("UPDATE jobs SET status='done' WHERE kind='apps.ingest_source'")
    shot, _ = assets.store_asset(aconn, cfg, "frigo", io.BytesIO(png(300, 650)), "visuel.png", now=clock(),
                                 origin="appstore")
    store.request_analysis(aconn, "frigo", now=clock())
    run()
    clock.advance(seconds=16)
    run()

    seen = assets.get_asset(aconn, "frigo", shot["id"])["analysis"]
    assert seen["screen"].startswith("visuel App Store : ") and not seen["usable_in_video"]
    b = store.latest_brief(aconn, "frigo")["brief"]
    assert b["app_name"] == "Frigo Malin" and b["category"] == "Cuisine et boissons"
    assert b["one_liner"] == {"fr": "Des recettes de 15 minutes avec ce qu'il reste dans le frigo.", "en": ""}
    assert b["proof_points"] == ["Note de 4,6/5 sur 2 345 notes (App Store FR, relevée le 02/11/2026)"]
    assert b["pricing"].startswith("Gratuit (App Store)")
    assert "frigo malin" in b["keywords"]["fr"] and b["keywords"]["en"] == ""
    assert b["features"] and b["features"][0]["asset_ids"] == [shot["id"]]
    questions = store.list_questions(aconn, "frigo", "open")
    assert questions[0]["question"].startswith("Frigo Malin a-t-il une offre payante")
