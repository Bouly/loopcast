"""Compréhension par Claude (FakeLLM) : description des fichiers, analyse, questions, affinage, approbation."""

import io
import json
import re
import shutil
import subprocess

import pytest

from loopcast import jobs, llm
from loopcast.apps import assets, prompts, store
from loopcast.schemas import AnalysisResult, Feature, ProductBrief

from .helpers import analysis, brief, images, job_row, png, question, texts

HAS_FFMPEG = bool(assets.find_tool("ffmpeg") and assets.find_tool("ffprobe"))


def make_app(aconn, cfg, clock, **kw):
    kw.setdefault("description", "Habitudo : 3 habitudes, une coche par soir. Pour les 18-30 ans.")
    return store.create_app(aconn, cfg, now=clock(), app_id="habitudo", name="Habitudo", **kw)


def add_file(aconn, cfg, clock, name="shot.png", data=None, **kw):
    asset, _created = assets.store_asset(aconn, cfg, "habitudo", io.BytesIO(data or png(300, 650)), name, now=clock(),
                                         **kw)
    return asset


def calls(fake_llm, task):
    return [c for c in fake_llm.calls if c.task == task]


# --- Description des fichiers --------------------------------------------------------------------------------

def test_describe_asset_stores_the_analysis_and_its_cost(aconn, cfg, clock, fake_llm, run):
    make_app(aconn, cfg, clock)
    shot = add_file(aconn, cfg, clock, caption="La liste du jour")
    run()
    assert assets.get_asset(aconn, "habitudo", shot["id"])["analysis"] == analysis().model_dump()
    req = calls(fake_llm, "asset.describe")[0]
    assert req.system == prompts.DESCRIBE_SYSTEM and req.effort == "low" and len(images(req)) == 1
    assert f"Fichier : asset #{shot['id']}, capture, fournie par l'équipe, 300×650" in texts(req)
    assert "Légende : La liste du jour" in texts(req) and "Ce que l'équipe dit de l'app : Habitudo" in texts(req)
    cost = aconn.execute("SELECT * FROM cost_ledger").fetchone()
    assert (cost["provider"], cost["kind"], cost["app_id"], cost["note"], cost["ref"]) == (
        "anthropic", "llm", "habitudo", "asset.describe", f"asset:{shot['id']}")
    assert cost["cost_usd"] == pytest.approx(0.05)

    # Déjà décrite : une autre tâche sur le même fichier ne rappelle pas Claude.
    jobs.enqueue(aconn, "apps.describe_asset", {"asset_id": shot["id"]}, key="encore", clock=clock)
    run()
    assert len(fake_llm.calls) == 1 and json.loads(job_row(aconn, "encore")["result"]) == {"skipped": "déjà décrit"}


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe absents")
def test_a_demo_video_is_described_from_frames(aconn, cfg, clock, fake_llm, run, tmp_path):
    video = tmp_path / "demo.mp4"
    subprocess.run([shutil.which("ffmpeg") or assets.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=duration=4:size=360x640:rate=10", "-pix_fmt", "yuv420p", str(video)], check=True)
    make_app(aconn, cfg, clock)
    asset = add_file(aconn, cfg, clock, "demo.mp4", video.read_bytes())
    run()
    req = calls(fake_llm, "asset.describe")[0]
    assert len(images(req)) == 4
    assert "Ces 4 images sont extraites, dans l'ordre, d'une vidéo de démo de 4 s (à 0,5, 1,5, 2,5, 3,5 s)" in texts(req)
    assert assets.get_asset(aconn, "habitudo", asset["id"])["analysis"]["screen"] == "accueil"


# --- Analyse -----------------------------------------------------------------------------------------------------

def test_analysis_waits_for_inputs_then_writes_the_brief_and_questions(aconn, cfg, clock, fake_llm, run):
    make_app(aconn, cfg, clock)
    shots = [add_file(aconn, cfg, clock, f"{i}.png", png(300, 650, (i, 9, 9))) for i in range(2)]
    store.add_source(aconn, "habitudo", now=clock(), text="Prix : gratuit, premium à 2,99 €/mois.", title="Notes")
    fake_llm.responders["app.analyze"] = lambda req: AnalysisResult(
        brief=brief(features=[Feature(name="Coche", benefit="b", proof="p", asset_ids=[shots[0]["id"], 999])]),
        questions=[question("Quel est le public prioritaire ?", "utile", "choice", ["Étudiants", "Actifs"]),
                   question("Y a-t-il une offre payante ?"),
                   question("Un choix sans options ?", "utile", "choice")])
    job_id = store.request_analysis(aconn, "habitudo", now=clock())

    run(kinds=["apps.analyze"])                                  # les captures ne sont pas encore décrites
    row = aconn.execute("SELECT status, result FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "queued" and json.loads(row["result"]) == {"waiting": "en attente : 2 fichier(s) à décrire"}
    assert calls(fake_llm, "app.analyze") == [] and store.get_app(aconn, "habitudo")["status"] == "analyzing"
    run()
    clock.advance(seconds=16)
    run()

    v1 = store.latest_brief(aconn, "habitudo")
    assert (v1["version"], v1["origin"], v1["job_id"], v1["model"]) == (1, "analyze", job_id, "claude-opus-5-5")
    assert v1["brief"]["features"][0]["asset_ids"] == [shots[0]["id"]]          # l'id inventé est retiré
    questions = store.list_questions(aconn, "habitudo")
    assert [q["question"] for q in questions] == ["Y a-t-il une offre payante ?", "Quel est le public prioritaire ?",
                                                  "Un choix sans options ?"]
    assert questions[1]["kind"] == "choice" and questions[1]["options"] == ["Étudiants", "Actifs"]
    assert questions[2]["kind"] == "text" and questions[2]["options"] == []
    assert {(q["round"], q["brief_id"], q["status"]) for q in questions} == {(1, v1["id"], "open")}
    assert store.get_app(aconn, "habitudo")["status"] == "questions"

    req = calls(fake_llm, "app.analyze")[0]
    body = texts(req)
    assert req.effort == "high" and len(images(req)) == 2
    assert "<team_description>\nHabitudo : 3 habitudes, une coche par soir." in body
    assert 'type="texte fourni par l\'équipe"' in body and "premium à 2,99 €/mois" in body
    assert f"#{shots[0]['id']} · capture · fournie par l'équipe · 300×650" in body
    assert "  écran : accueil — trois cartes d'habitudes" in body
    assert "écrits nativement en français et en anglais" in body
    assert f"`asset_ids` : uniquement parmi #{shots[0]['id']}, #{shots[1]['id']}." in body
    assert "Règle d'or : des faits sourcés, jamais inventés" in req.system
    event = aconn.execute("SELECT message FROM events WHERE kind='apps.analyzed'").fetchone()["message"]
    assert event == "Habitudo : fiche v1 prête, 3 question(s) pour l'équipe"
    assert aconn.execute("SELECT COUNT(*) FROM cost_ledger WHERE note='app.analyze'").fetchone()[0] == 1


def test_analysis_shows_eight_screenshots_at_most_team_first_one_per_screen(aconn, cfg, clock, fake_llm, run):
    def describe(req):
        asset_id = int(re.search(r"asset #(\d+)", texts(req)).group(1))
        return analysis(screen=f"écran {asset_id % 3}")

    fake_llm.responders["asset.describe"] = describe
    make_app(aconn, cfg, clock)
    store_shots = [add_file(aconn, cfg, clock, f"s{i}.png", png(300, 650, (200, i, 0)), origin="appstore")
                   for i in range(2)]
    team = [add_file(aconn, cfg, clock, f"t{i}.png", png(300, 650, (0, i, 200))) for i in range(10)]
    store.request_analysis(aconn, "habitudo", now=clock())
    run()
    clock.advance(seconds=16)
    run()
    req = calls(fake_llm, "app.analyze")[0]
    shown = [int(i) for i in re.findall(r"^Capture #(\d+)", texts(req), re.M)]
    assert len(images(req)) == 8 and len(shown) == 8
    assert not set(shown) & {a["id"] for a in store_shots}                       # celles de l'équipe d'abord
    assert len({team_id % 3 for team_id in shown[:3]}) == 3                        # trois écrans différents d'abord


def test_documents_are_given_to_the_analysis(aconn, cfg, clock, fake_llm, run):
    make_app(aconn, cfg, clock)
    add_file(aconn, cfg, clock, "pitch.md", b"# Pitch\nNos utilisateurs gardent leur serie 21 jours en moyenne.")
    add_file(aconn, cfg, clock, "deck.pdf", b"%PDF-1.4 faux pdf de test")
    store.request_analysis(aconn, "habitudo", now=clock())
    run()
    req = calls(fake_llm, "app.analyze")[0]
    assert re.search(r'<document id="\d+" nom="pitch.md">\n# Pitch\nNos utilisateurs', texts(req))
    pdf = [b for b in req.content if b.get("type") == "document"]
    assert len(pdf) == 1 and pdf[0]["source"]["media_type"] == "application/pdf" and pdf[0]["title"] == "deck.pdf"


def test_french_only_app_and_no_question(aconn, cfg, clock, fake_llm, run):
    make_app(aconn, cfg, clock, langs=["fr"])
    store.request_analysis(aconn, "habitudo", now=clock())
    run()
    b = store.latest_brief(aconn, "habitudo")["brief"]
    assert b["one_liner"] == {"fr": "3 habitudes, une coche par soir", "en": ""}
    assert b["cta"]["en"] == "" and b["keywords"]["en"] == "" and b["personas"][0]["langs"] == ["fr"]
    assert store.get_app(aconn, "habitudo")["status"] == "brief_ready"
    assert "leur champ `en` reste vide (marché non visé)" in texts(calls(fake_llm, "app.analyze")[0])


def test_analysis_is_idempotent(aconn, cfg, clock, fake_llm, run):
    make_app(aconn, cfg, clock)
    job_id = store.request_analysis(aconn, "habitudo", now=clock())
    assert store.request_analysis(aconn, "habitudo", now=clock()) == job_id
    run()
    # Le processus serait mort après l'écriture de la fiche, avant de marquer la tâche faite : elle repart.
    aconn.execute("UPDATE jobs SET status='queued' WHERE id=?", (job_id,))
    run()
    assert len(calls(fake_llm, "app.analyze")) == 1 and len(store.list_briefs(aconn, "habitudo")) == 1
    assert json.loads(job_row(aconn, "apps.analyze:habitudo:1")["result"]) == {"brief_version": 1, "already_done": True}
    # Une nouvelle demande vise la version suivante : nouvelle clé, nouvelle tâche.
    assert store.request_analysis(aconn, "habitudo", now=clock()) == job_row(aconn, "apps.analyze:habitudo:2")["id"]


def test_a_new_analysis_replaces_open_questions_and_never_asks_again_what_was_answered(aconn, cfg, clock, fake_llm,
                                                                                        run):
    make_app(aconn, cfg, clock)
    fake_llm.responders["app.analyze"] = lambda req: AnalysisResult(
        brief=brief(), questions=[question("Prix ?"), question("Public ?", "utile")])
    store.request_analysis(aconn, "habitudo", now=clock())
    run()
    first = {q["question"]: q for q in store.list_questions(aconn, "habitudo", "open")}
    store.answer_questions(aconn, "habitudo", now=clock(), answers={first["Prix ?"]["id"]: "Gratuit"})
    store.request_analysis(aconn, "habitudo", now=clock())          # « Public ? » est encore ouverte
    run(kinds=["apps.analyze"])

    questions = store.list_questions(aconn, "habitudo")
    by_status = {(q["question"], q["status"]) for q in questions}
    assert by_status == {("Prix ?", "answered"), ("Public ?", "skipped"), ("Public ?", "open")}
    reopened = next(q for q in questions if q["status"] == "open")
    assert reopened["brief_id"] == store.latest_brief(aconn, "habitudo")["id"] and reopened["round"] == 1
    body = texts(calls(fake_llm, "app.analyze")[1])
    assert "R : Gratuit" in body and "Public ?" not in body                 # une question ouverte n'est pas un acquis


def test_budget_cap_postpones_the_analysis_without_calling_claude(aconn, cfg, clock, fake_llm, run):
    cfg.settings["budget"] = {"daily_usd": 0.10}
    make_app(aconn, cfg, clock)
    job_id = store.request_analysis(aconn, "habitudo", now=clock())
    run()
    row = aconn.execute("SELECT status, run_after, result FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "queued" and row["run_after"] == "2026-11-03T00:00:00+00:00"   # demain, minuit UTC
    assert "plafond du jour atteint" in json.loads(row["result"])["waiting"]
    assert fake_llm.calls == []


def test_without_claude_the_analysis_fails_clearly_and_can_be_relaunched(aconn, cfg, clock, fake_llm, services, run):
    services["llm"] = llm.UnavailableLLM()
    make_app(aconn, cfg, clock)
    job_id = store.request_analysis(aconn, "habitudo", now=clock())
    run()
    row = aconn.execute("SELECT status, last_error FROM jobs WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "dead" and "aucune clé Claude configurée" in row["last_error"]
    assert store.get_app(aconn, "habitudo")["status"] == "draft"                 # n'est plus « en analyse »
    event = aconn.execute("SELECT message FROM events WHERE kind='apps.analysis_failed'").fetchone()["message"]
    assert event.startswith("Habitudo : analyse en échec : aucune clé Claude configurée")
    assert store.app_overview(aconn, "habitudo")["jobs"]["failed"][0]["kind"] == "apps.analyze"

    services["llm"] = fake_llm
    assert store.request_analysis(aconn, "habitudo", now=clock()) == job_id      # la même tâche repart
    run()
    assert store.latest_brief(aconn, "habitudo")["version"] == 1


# --- Questions, affinage, approbation ---------------------------------------------------------------------------------

def test_answers_refine_the_brief_round_by_round_three_rounds_at_most(aconn, cfg, clock, fake_llm, run):
    make_app(aconn, cfg, clock)
    fake_llm.responders["app.analyze"] = lambda req: AnalysisResult(
        brief=brief(), questions=[question("Prix ?"), question("Public ?", "utile")])
    rounds = {"n": 0}

    def refine(req):
        rounds["n"] += 1
        return AnalysisResult(brief=brief(confidence=0.6 + rounds["n"] / 10), questions=[
            question("Prix ?"),                                     # déjà posée : écartée
            question(f"Bloquante {rounds['n']} ?"),
            question(f"Utile {rounds['n']} ?", "utile"),             # un affinage ne pose que du bloquant
        ])

    fake_llm.responders["app.refine"] = refine
    store.request_analysis(aconn, "habitudo", now=clock())
    run()
    first = {q["question"]: q for q in store.list_questions(aconn, "habitudo", "open")}
    res = store.answer_questions(aconn, "habitudo", now=clock(), answers={first["Prix ?"]["id"]: "2,99 €/mois"})
    assert res["refine_job"] is None and res["status"] == "questions"
    res = store.answer_questions(aconn, "habitudo", now=clock(), answers={first["Public ?"]["id"]: ["Étudiants", "Actifs"]})
    brief_id = first["Prix ?"]["brief_id"]
    assert res["refine_job"] == job_row(aconn, f"apps.refine:habitudo:{brief_id}")["id"]
    assert res["status"] == "analyzing"
    run()

    v2 = store.latest_brief(aconn, "habitudo")
    assert (v2["version"], v2["origin"], v2["brief"]["confidence"]) == (2, "refine", 0.7)
    second = store.list_questions(aconn, "habitudo", "open")
    assert [(q["question"], q["round"], q["brief_id"]) for q in second] == [("Bloquante 1 ?", 2, v2["id"])]
    body = texts(calls(fake_llm, "app.refine")[0])
    assert "<new_answers>" in body and "R : 2,99 €/mois" in body and "R : Étudiants, Actifs" in body
    assert '<current_brief version="1" origine="rédigée par l\'analyse" approuvee="non">' in body
    assert "Tour 1 sur 3 : au plus 3 nouvelles questions, uniquement bloquantes" in body

    store.answer_questions(aconn, "habitudo", now=clock(), answers={second[0]["id"]: "Oui"})
    run()
    third = store.list_questions(aconn, "habitudo", "open")
    assert [(q["question"], q["round"]) for q in third] == [("Bloquante 2 ?", 3)]
    assert "<earlier_answers>" in texts(calls(fake_llm, "app.refine")[1])

    store.answer_questions(aconn, "habitudo", now=clock(), answers={third[0]["id"]: "Non"})
    run()
    assert store.list_questions(aconn, "habitudo", "open") == []                 # plus de 4e tour
    assert store.latest_brief(aconn, "habitudo")["version"] == 4
    assert store.get_app(aconn, "habitudo")["status"] == "brief_ready"
    assert "C'était le dernier tour (3 sur 3)" in texts(calls(fake_llm, "app.refine")[-1])


def test_skipping_every_question_needs_no_refine(aconn, cfg, clock, fake_llm, run):
    make_app(aconn, cfg, clock)
    fake_llm.responders["app.analyze"] = lambda req: AnalysisResult(
        brief=brief(), questions=[question("Prix ?"), question("Public ?", "utile")])
    store.request_analysis(aconn, "habitudo", now=clock())
    run()
    first = store.list_questions(aconn, "habitudo", "open")[0]
    res = store.answer_questions(aconn, "habitudo", now=clock(), skip=[first["id"]], skip_rest=True)
    assert res == {"answered": 0, "skipped": 1, "refine_job": None, "status": "brief_ready"}
    assert aconn.execute("SELECT COUNT(*) FROM jobs WHERE kind='apps.refine'").fetchone()[0] == 0
    with pytest.raises(store.Conflict, match="déjà passée"):
        store.answer_questions(aconn, "habitudo", now=clock(), answers={first["id"]: "trop tard"})


def test_approval_asks_for_the_strategy_once(aconn, cfg, clock, fake_llm, run):
    make_app(aconn, cfg, clock)
    with pytest.raises(store.Conflict, match="aucune fiche à approuver"):
        store.approve_brief(aconn, "habitudo", now=clock())
    fake_llm.responders["app.analyze"] = lambda req: AnalysisResult(brief=brief(), questions=[question("Prix ?")])
    store.request_analysis(aconn, "habitudo", now=clock())
    run()

    res = store.approve_brief(aconn, "habitudo", now=clock())
    b = res["brief"]
    assert b["version"] == 1 and b["approved_at"] == jobs.iso(clock())
    job = job_row(aconn, f"strategy.generate:habitudo:{b['id']}")
    assert job["id"] == res["strategy_job"] and job["status"] == "queued" and job["app_id"] == "habitudo"
    assert json.loads(job["payload"]) == {"app_id": "habitudo", "brief_id": b["id"]}
    assert store.get_app(aconn, "habitudo")["status"] == "brief_ready"
    assert store.list_questions(aconn, "habitudo", "open") == []                 # la question restante est passée
    assert store.approve_brief(aconn, "habitudo", now=clock())["strategy_job"] == res["strategy_job"]
    assert aconn.execute("SELECT COUNT(*) FROM jobs WHERE kind='strategy.generate'").fetchone()[0] == 1
    with pytest.raises(store.Conflict, match=r"seule la dernière version \(v1\)"):
        store.approve_brief(aconn, "habitudo", now=clock(), version=2)

    # Le contrat lu par le module strategy (docs/architecture-pipeline.md).
    row = aconn.execute("SELECT brief FROM app_briefs WHERE app_id=? AND approved_at IS NOT NULL "
                        "ORDER BY version DESC LIMIT 1", ("habitudo",)).fetchone()
    assert ProductBrief.model_validate_json(row["brief"]).app_name == "Habitudo"


def test_reanalysis_of_an_active_app_keeps_it_active(aconn, cfg, clock, fake_llm, run):
    make_app(aconn, cfg, clock)
    store.request_analysis(aconn, "habitudo", now=clock())
    run()
    store.approve_brief(aconn, "habitudo", now=clock())
    aconn.execute("UPDATE apps SET status='active'")
    store.request_analysis(aconn, "habitudo", now=clock())
    assert store.get_app(aconn, "habitudo")["status"] == "active"
    run()
    assert store.get_app(aconn, "habitudo")["status"] == "active"
    assert store.latest_brief(aconn, "habitudo")["version"] == 2
    assert store.latest_brief(aconn, "habitudo", approved=True)["version"] == 1   # v2 attend son approbation
    body = texts(calls(fake_llm, "app.analyze")[1])
    assert '<current_brief version="1" origine="rédigée par l\'analyse" approuvee="oui">' in body
