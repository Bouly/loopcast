"""Routes /api/apps : le parcours complet, les erreurs en français, le branchement dans l'API principale."""

from fastapi.testclient import TestClient

from loopcast.api.app import create_app
from loopcast.farm.backend import FakeBackend
from loopcast.schemas import AnalysisResult

from .helpers import brief, job_row, png, question


def test_full_flow_through_the_api(api, aconn, fake_llm, run):
    fake_llm.responders["app.analyze"] = lambda req: AnalysisResult(
        brief=brief(), questions=[question("Prix ?"), question("Public ?", "utile", "choice", ["A", "B"])])
    r = api.post("/api/apps", json={"name": "Habitudo", "description": "3 habitudes, une coche par soir.",
                                    "langs": ["fr", "en"]})
    assert r.status_code == 201 and r.json()["id"] == "habitudo" and r.json()["status"] == "draft"
    api.post("/api/apps/habitudo/assets", files=[("files", ("a.png", png(300, 650)))])
    assert api.post("/api/apps/habitudo/sources", json={"text": "Notre pitch"}).json()["created"] is True

    r = api.post("/api/apps/habitudo/analyze")
    assert r.status_code == 200 and r.json()["app"]["status"] == "analyzing"
    assert [j["kind"] for j in r.json()["app"]["jobs"]["pending"]] == ["apps.describe_asset", "apps.analyze"]
    run()
    detail = api.get("/api/apps/habitudo").json()
    assert detail["status"] == "questions" and detail["counts"]["questions_open"] == 2
    assert detail["brief"]["version"] == 1 and detail["approved_version"] is None and detail["counts"]["described"] == 1

    questions = api.get("/api/apps/habitudo/questions", params={"status": "open"}).json()
    r = api.post("/api/apps/habitudo/questions/answers",
                 json={"answers": [{"id": questions[0]["id"], "answer": "Gratuit"}], "skip": [questions[1]["id"]]})
    assert r.json()["refine_job"] is not None and r.json()["status"] == "analyzing"
    run()
    latest = api.get("/api/apps/habitudo/brief").json()
    assert latest["version"] == 2 and latest["origin"] == "refine" and latest["approved_version"] is None
    assert [v["version"] for v in api.get("/api/apps/habitudo/brief/versions").json()] == [2, 1]
    assert api.get("/api/apps/habitudo/brief/versions/1").json()["origin"] == "analyze"

    edited = brief(pricing="Gratuit, sans publicité").model_dump()
    r = api.put("/api/apps/habitudo/brief", json=edited)
    assert r.status_code == 200 and r.json()["version"] == 3 and r.json()["origin"] == "edit"
    r = api.post("/api/apps/habitudo/brief/approve", json={"version": 3})
    assert r.status_code == 200 and r.json()["brief"]["version"] == 3
    job = job_row(aconn, f"strategy.generate:habitudo:{r.json()['brief']['id']}")
    assert job["id"] == r.json()["strategy_job"]
    assert api.get("/api/apps").json()[0]["approved_version"] == 3
    kinds = {data["change"] for kind, data in api.bus.events if kind == "apps"}
    assert {"created", "assets", "sources", "analysis", "questions", "brief"} <= kinds


def test_errors_are_explicit(api):
    assert api.get("/api/apps/inconnue").json() == {"detail": "app inconnue : « inconnue »"}
    assert api.get("/api/apps/inconnue").status_code == 404
    api.post("/api/apps", json={"id": "app", "name": "App"})
    r = api.post("/api/apps", json={"id": "app", "name": "App"})
    assert r.status_code == 409 and r.json()["detail"] == "l'app « app » existe déjà"
    r = api.post("/api/apps/app/analyze")
    assert r.status_code == 409 and r.json()["detail"].startswith("rien à analyser")
    assert api.get("/api/apps/app/brief").status_code == 404
    r = api.post("/api/apps/app/brief/approve")
    assert r.status_code == 409 and "aucune fiche" in r.json()["detail"]
    assert api.put("/api/apps/app/brief", json={"app_name": "App"}).status_code == 422     # fiche incomplète
    r = api.patch("/api/apps/app", json={"langs": ["de"]})
    assert r.status_code == 400 and "fr ou en" in r.json()["detail"]
    assert api.post("/api/apps/app/questions/42/skip").status_code == 404
    r = api.post("/api/apps/app/sources", json={"url": "https://apps.apple.com/fr/app/sans-id"})
    assert r.status_code == 400 and "identifiant de l'app" in r.json()["detail"]


def test_pause_resume_and_brand_files(api, with_brand):
    assert api.get("/api/apps/brands").json() == [{"id": "habitudo", "name": "Habitudo", "imported": False}]
    r = api.post("/api/apps", json={"id": "habitudo"})
    assert r.status_code == 201 and r.json()["name"] == "Habitudo" and r.json()["brand"]["accent"] == "#5B5BF7"
    assert api.post("/api/apps/habitudo/pause").json()["status"] == "paused"
    assert api.post("/api/apps/habitudo/resume").json()["status"] == "draft"
    r = api.patch("/api/apps/habitudo", json={"website_url": "https://habitudo.fr"})
    assert r.json()["counts"]["sources"] == 1 and r.json()["counts"]["sources_pending"] == 1
    sources = api.get("/api/apps/habitudo/sources").json()
    assert sources[0]["kind"] == "website" and sources[0]["preview"] == "" and "content" not in sources[0]


def test_uploaded_documents_are_downloaded_never_rendered(api):
    """Un .html ou un .svg téléversé n'est jamais affiché sur l'origine du dashboard (son script y agirait à la
    place de l'équipe) : téléchargement (attachment), et nosniff partout. Images et vidéos restent affichées."""
    api.post("/api/apps", json={"id": "app", "name": "App"})
    files = [("files", ("page.html", b"<script>fetch('/api/jobs/1/retry', {method: 'POST'})</script>")),
             ("files", ("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>')),
             ("files", ("notes.txt", b"<html><script>alert(1)</script></html>")),
             ("files", ("a.png", png(300, 650)))]
    r = api.post("/api/apps/app/assets", files=files)
    assert r.status_code == 201 and r.json()["errors"] == []
    stored = {a["filename"]: a for a in r.json()["assets"]}
    for name in ("page.html", "logo.svg", "notes.txt"):
        got = api.get(stored[name]["url"])
        assert got.status_code == 200 and got.headers["content-disposition"].startswith("attachment"), name
        assert got.headers["x-content-type-options"] == "nosniff"
    image = api.get(stored["a.png"]["url"])
    assert image.headers["content-disposition"].startswith("inline") and image.headers["content-type"] == "image/png"
    assert image.headers["x-content-type-options"] == "nosniff"


def test_router_is_mounted_in_the_main_api(cfg, dbpath, aconn, services):
    app = create_app(cfg, aconn, FakeBackend([]), web_dist=None, services=services, db_path=dbpath)
    with TestClient(app) as client:
        assert client.post("/api/apps", json={"id": "app", "name": "App"}).status_code == 201
        assert [a["id"] for a in client.get("/api/apps").json()] == ["app"]
        assert client.get("/api/jobs").status_code == 200
