"""Création d'une app, reprise de brands/<id>.json, liens et sources, pause, statut."""

import json

import pytest

from loopcast.apps import store

from .helpers import brief, job_row

IOS = "https://apps.apple.com/fr/app/habitudo/id1234567890"


def test_create_app_with_links_queues_one_reading_per_source(aconn, cfg, clock):
    app = store.create_app(aconn, cfg, now=clock(), name="Ma Super App !", store_url_ios=IOS,
                           website_url="https://exemple.fr", langs=["fr"])
    assert app["id"] == "ma-super-app" and app["status"] == "draft" and app["langs"] == ["fr"]

    sources = store.list_sources(aconn, app["id"])
    assert [(s["kind"], s["status"]) for s in sources] == [("appstore", "pending"), ("website", "pending")]
    for s in sources:
        job = job_row(aconn, f"apps.ingest_source:{s['id']}")
        assert job["kind"] == "apps.ingest_source" and job["app_id"] == "ma-super-app"
        assert json.loads(job["payload"]) == {"source_id": s["id"]}

    with pytest.raises(store.Conflict, match="existe déjà"):
        store.create_app(aconn, cfg, now=clock(), app_id="ma-super-app", name="Autre")


@pytest.mark.parametrize("kw, message", [
    ({"name": "X", "store_url_ios": "https://apps.apple.com/fr/app/sans-id"}, "identifiant de l'app"),
    ({"name": "X", "store_url_android": "https://play.google.com/store/apps/details"}, "Google Play"),
    ({"name": "X", "website_url": "exemple.fr"}, "https://"),
    ({"name": "X", "langs": ["fr", "de"]}, "fr ou en"),
    ({"app_id": "Pas Un Slug!", "name": "X"}, "identifiant invalide"),
    ({"app_id": "sans-nom"}, "nom de l'app est obligatoire"),
])
def test_create_app_rejects_invalid_data_with_a_clear_message(aconn, cfg, clock, kw, message):
    with pytest.raises(store.AppError, match=message):
        store.create_app(aconn, cfg, now=clock(), **kw)


def test_create_app_from_brand_file(aconn, cfg, clock, with_brand):
    app = store.create_app(aconn, cfg, now=clock(), app_id="habitudo")
    assert app["name"] == "Habitudo" and app["langs"] == ["fr", "en"]
    assert app["brand"]["accent"] == "#5B5BF7" and app["brand"]["handle"] == "@habitudo"
    assert app["brand"]["storeLine"]["fr"].startswith("Gratuit")
    assert "Promesse (fr) : 3 habitudes" in app["description"]
    assert "Problèmes du public (en) : quits resolutions after 3 days" in app["description"]
    # Les liens « CHANGE_ME » du fichier de démo ne deviennent pas des sources.
    assert app["store_url_ios"] is None and store.list_sources(aconn, "habitudo") == []
    assert store.brand_files(aconn, cfg) == [{"id": "habitudo", "name": "Habitudo", "imported": True}]


def test_values_given_win_over_the_brand_file(aconn, cfg, clock, with_brand):
    app = store.create_app(aconn, cfg, now=clock(), app_id="habitudo", description="Notre texte", langs="fr",
                           brand={"accent": "#000000"})
    assert app["description"] == "Notre texte" and app["langs"] == ["fr"]
    assert app["brand"]["accent"] == "#000000" and app["brand"]["handle"] == "@habitudo"


def test_update_replaces_the_source_of_a_changed_link_and_merges_brand(aconn, cfg, clock):
    store.create_app(aconn, cfg, now=clock(), app_id="app", name="App", website_url="https://a.fr",
                     brand={"accent": "#111111"})
    app = store.update_app(aconn, "app", {"website_url": "https://b.fr", "brand": {"handle": "@app", "accent": None}},
                           now=clock())
    assert [s["url"] for s in store.list_sources(aconn, "app")] == ["https://b.fr"]
    assert app["brand"] == {"handle": "@app"}
    # Des langues qui changent font relire l'App Store (une vitrine par langue).
    store.update_app(aconn, "app", {"store_url_ios": IOS}, now=clock())
    src = next(s for s in store.list_sources(aconn, "app") if s["kind"] == "appstore")
    aconn.execute("UPDATE jobs SET status='done'")
    store.update_app(aconn, "app", {"langs": ["fr", "en"]}, now=clock())          # rien ne change
    assert job_row(aconn, f"apps.ingest_source:{src['id']}:2") is None
    store.update_app(aconn, "app", {"langs": ["fr"]}, now=clock())
    assert job_row(aconn, f"apps.ingest_source:{src['id']}:2")["status"] == "queued"


def test_text_source_is_ready_at_once_and_links_are_not_duplicated(aconn, cfg, clock):
    store.create_app(aconn, cfg, now=clock(), app_id="app", name="App")
    text, created = store.add_source(aconn, "app", now=clock(), text="  Notre pitch : des recettes en 15 min.  ")
    assert created and text["kind"] == "text" and text["status"] == "ok"
    assert text["content"] == "Notre pitch : des recettes en 15 min." and text["title"] == "Texte collé"
    first, created = store.add_source(aconn, "app", now=clock(), url="https://exemple.fr")
    again, created_again = store.add_source(aconn, "app", now=clock(), url="https://exemple.fr")
    assert created and not created_again and again["id"] == first["id"]
    assert aconn.execute("SELECT COUNT(*) FROM jobs WHERE kind='apps.ingest_source'").fetchone()[0] == 1


def test_refresh_reuses_a_waiting_reading_then_uses_a_new_key(aconn, cfg, clock):
    store.create_app(aconn, cfg, now=clock(), app_id="app", name="App", website_url="https://a.fr")
    sid = store.list_sources(aconn, "app")[0]["id"]
    first = job_row(aconn, f"apps.ingest_source:{sid}")["id"]
    assert store.refresh_source(aconn, "app", sid, now=clock()) == first      # déjà en attente
    aconn.execute("UPDATE jobs SET status='done' WHERE id=?", (first,))
    again = store.refresh_source(aconn, "app", sid, now=clock())
    assert again != first and job_row(aconn, f"apps.ingest_source:{sid}:2")["id"] == again


def test_deleting_a_link_source_removes_the_link(aconn, cfg, clock):
    store.create_app(aconn, cfg, now=clock(), app_id="app", name="App", website_url="https://a.fr")
    sid = store.list_sources(aconn, "app")[0]["id"]
    store.delete_source(aconn, "app", sid, now=clock())
    assert store.get_app(aconn, "app")["website_url"] is None and store.list_sources(aconn, "app") == []
    # Sa lecture en attente est annulée : l'analyse n'attend pas une source disparue.
    assert job_row(aconn, f"apps.ingest_source:{sid}")["status"] == "cancelled"


def test_pause_and_resume(aconn, cfg, clock):
    store.create_app(aconn, cfg, now=clock(), app_id="app", name="App")
    store.save_brief(aconn, "app", brief(), now=clock())
    assert store.get_app(aconn, "app")["status"] == "brief_ready"
    paused = store.pause_app(aconn, "app", now=clock())
    assert paused["status"] == "paused" and paused["paused_from"] == "brief_ready"
    assert store.resume_app(aconn, "app", now=clock())["status"] == "brief_ready"

    # Une app active (module strategy) le redevient ; le module apps ne la fait pas reculer.
    aconn.execute("UPDATE apps SET status='active' WHERE id='app'")
    store.pause_app(aconn, "app", now=clock())
    assert store.resume_app(aconn, "app", now=clock())["status"] == "active"
    assert not store.set_status(aconn, "app", "analyzing", now=clock())
    assert store.get_app(aconn, "app")["status"] == "active"


def test_analysis_needs_something_to_read(aconn, cfg, clock):
    store.create_app(aconn, cfg, now=clock(), app_id="vide", name="Vide")
    with pytest.raises(store.Conflict, match="rien à analyser"):
        store.request_analysis(aconn, "vide", now=clock())
    store.update_app(aconn, "vide", {"description": "Une app de recettes."}, now=clock())
    first = store.request_analysis(aconn, "vide", now=clock())
    assert store.request_analysis(aconn, "vide", now=clock()) == first          # même clé : une seule tâche
    assert job_row(aconn, "apps.analyze:vide:1")["id"] == first
    assert store.get_app(aconn, "vide")["status"] == "analyzing"
    # Une fiche éditée à la main entre-temps ne crée pas une seconde analyse : celle en attente suffit.
    store.save_brief(aconn, "vide", brief(), now=clock())
    assert store.request_analysis(aconn, "vide", now=clock()) == first
    # Une analyse abandonnée est relancée par la même demande.
    aconn.execute("DELETE FROM app_briefs")
    aconn.execute("UPDATE jobs SET status='dead' WHERE id=?", (first,))
    assert store.request_analysis(aconn, "vide", now=clock()) == first
    assert job_row(aconn, "apps.analyze:vide:1")["status"] == "queued"
