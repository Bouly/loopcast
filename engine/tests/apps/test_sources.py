"""Lecture des sources (tâche apps.ingest_source) avec un faux internet : App Store, site, Google Play."""

import io

import httpx
import pytest

from loopcast.apps import assets, sources, store

from .helpers import IOS, SHOT, job_row, png, record, serve_appstore


def test_appstore_reads_each_storefront_and_imports_screenshots(aconn, cfg, clock, web, run):
    serve_appstore(web, {"fr": record("fr"), "us": record("us", description="Three habits, one check a night.")})
    store.create_app(aconn, cfg, now=clock(), app_id="habitudo", name="Habitudo", store_url_ios=IOS)
    run(kinds=["apps.ingest_source"])

    lookups = [(r.url.params["id"], r.url.params["country"]) for r in web.hits("itunes.apple.com")]
    assert lookups == [("1234567890", "fr"), ("1234567890", "us")]       # pays du lien, puis langue « en »
    src = store.list_sources(aconn, "habitudo")[0]
    assert src["status"] == "ok" and src["title"] == "Habitudo" and src["error"] is None
    assert "Fiche App Store FR (relevée le 02/11/2026) : Habitudo" in src["content"]
    assert "Note : 4,7/5 sur 1 234 notes" in src["content"] and "Three habits, one check a night." in src["content"]
    assert "prix à l'achat : Gratuit" in src["content"] and "Nouveautés de cette version" in src["content"]
    meta = src["meta"]
    assert meta["track_id"] == 1234567890 and meta["bundle_id"] == "com.exemple.habitudo"
    assert meta["countries"]["fr"]["rating_count"] == 1234 and meta["countries"]["us"]["version"] == "2.3.1"

    shots = assets.list_assets(aconn, "habitudo", "screenshot")
    logo = assets.list_assets(aconn, "habitudo", "logo")
    assert len(shots) == 4 and {a["origin"] for a in shots} == {"appstore"}
    assert shots[0]["caption"] == "Capture App Store FR n°1" and shots[0]["source_url"] == SHOT.format(country="fr", n=1)
    assert len(logo) == 1 and store.get_app(aconn, "habitudo")["brand"]["icon"] == logo[0]["id"]
    assert meta["imported"] == {"screenshots": 4, "failed": 0, "icon": logo[0]["id"]}
    # Les captures sont demandées en taille originale, puis décrites par Claude (pas le logo).
    assert all(r.url.path.endswith("/3000x3000bb.png") for r in web.hits("is1-ssl.mzstatic.com"))
    for a in shots:
        assert job_row(aconn, f"apps.describe_asset:{a['id']}") is not None
    assert job_row(aconn, f"apps.describe_asset:{logo[0]['id']}") is None

    # Relire la fiche ne réimporte rien.
    downloads = len(web.hits("is1-ssl.mzstatic.com"))
    store.refresh_source(aconn, "habitudo", src["id"], now=clock())
    run(kinds=["apps.ingest_source"])
    assert len(web.hits("is1-ssl.mzstatic.com")) == downloads
    assert len(assets.list_assets(aconn, "habitudo")) == 5


def test_appstore_screenshots_are_not_imported_when_the_team_gave_some(aconn, cfg, clock, web, run):
    serve_appstore(web, {"fr": record("fr")})
    store.create_app(aconn, cfg, now=clock(), app_id="habitudo", name="Habitudo", store_url_ios=IOS, langs=["fr"])
    assets.store_asset(aconn, cfg, "habitudo", io.BytesIO(png(100, 200)), "a.png", now=clock())
    run(kinds=["apps.ingest_source"])
    kinds = [(a["kind"], a["origin"]) for a in assets.list_assets(aconn, "habitudo")]
    assert sorted(kinds) == [("logo", "appstore"), ("screenshot", "upload")]


def test_unknown_app_is_a_permanent_error(aconn, cfg, clock, web, run):
    serve_appstore(web, {})
    store.create_app(aconn, cfg, now=clock(), app_id="habitudo", name="Habitudo", store_url_ios=IOS)
    run(kinds=["apps.ingest_source"])
    src = store.list_sources(aconn, "habitudo")[0]
    assert src["status"] == "error" and "app 1234567890 introuvable (vitrines : fr, us)" in src["error"]
    assert job_row(aconn, f"apps.ingest_source:{src['id']}")["status"] == "dead"
    event = aconn.execute("SELECT message FROM events WHERE kind='apps.source_error'").fetchone()
    assert event["message"].startswith("Habitudo : App Store")


PAGE = """<html><head><title>Habitudo – tes habitudes</title>
<meta name="description" content="3 habitudes, une coche par soir.">
<meta property="og:title" content="Habitudo">
<script>var tracking = "SCRIPT_SECRET";</script><style>.x{color:red}</style></head>
<body class="has-cookie-banner">
<nav><a href="/">Accueil</a><a href="/blog">NAV_BLOG</a></nav>
<div id="cookie-consent">Nous utilisons des COOKIES_TEXT</div>
<main>
<h1>Tiens tes habitudes</h1>
<p>Une coche par soir, <b>trois</b> habitudes&nbsp;au plus.</p>
<ul><li>Rappel le soir</li><li>Série de jours</li></ul>
</main>
<footer><a href="https://apps.apple.com/fr/app/habitudo/id1234567890?pt=1">App Store</a> FOOTER_TEXT</footer>
</body></html>"""


def test_website_main_text_and_store_link(aconn, cfg, clock, web, run):
    web.on("habitudo.fr", text=PAGE, headers={"content-type": "text/html; charset=utf-8"})
    store.create_app(aconn, cfg, now=clock(), app_id="habitudo", name="Habitudo", website_url="https://habitudo.fr")
    run(kinds=["apps.ingest_source"], limit=1)

    site = store.list_sources(aconn, "habitudo")[0]
    assert site["status"] == "ok" and site["title"] == "Habitudo"
    assert site["content"].startswith("Titre : Habitudo\nDescription : 3 habitudes, une coche par soir.")
    assert "# Tiens tes habitudes\nUne coche par soir, trois habitudes au plus.\n- Rappel le soir\n- Série de jours" \
        in site["content"]
    for noise in ("SCRIPT_SECRET", "NAV_BLOG", "COOKIES_TEXT", "FOOTER_TEXT", "color:red"):
        assert noise not in site["content"]
    request = web.hits("habitudo.fr")[0]
    assert request.headers["accept-language"].startswith("fr")
    # Le site renvoie vers une seule fiche App Store : elle devient le lien de l'app et sera lue aussi.
    app = store.get_app(aconn, "habitudo")
    assert app["store_url_ios"] == "https://apps.apple.com/fr/app/habitudo/id1234567890?pt=1"
    appstore = [s for s in store.list_sources(aconn, "habitudo") if s["kind"] == "appstore"]
    assert len(appstore) == 1 and job_row(aconn, f"apps.ingest_source:{appstore[0]['id']}")["status"] == "queued"


def test_website_is_bounded(aconn, cfg, clock, web, run):
    cfg.settings["apps"] = {"max_page_bytes": 3_000, "max_source_chars": 400}
    body = "".join(f"<p>Paragraphe numéro {i} : une phrase de remplissage assez longue.</p>" for i in range(500))
    web.on("long.fr", text=f"<html><body><main>{body}</main></body></html>", headers={"content-type": "text/html"})
    store.create_app(aconn, cfg, now=clock(), app_id="long", name="Long", website_url="https://long.fr")
    run(kinds=["apps.ingest_source"])
    site = store.list_sources(aconn, "long")[0]
    assert site["status"] == "ok" and site["meta"]["truncated"] is True
    assert len(site["content"]) <= 400 + len("\n[…]") and site["content"].endswith("[…]")


def test_network_errors_are_retried_then_reported(aconn, cfg, clock, web, run):
    def refused(request):
        raise httpx.ConnectError("connexion refusée", request=request)

    web.on("panne.fr", fn=refused)
    store.create_app(aconn, cfg, now=clock(), app_id="panne", name="Panne", website_url="https://panne.fr")
    sid = store.list_sources(aconn, "panne")[0]["id"]
    run()
    job = job_row(aconn, f"apps.ingest_source:{sid}")
    src = store.get_source(aconn, "panne", sid)
    assert job["status"] == "queued" and job["attempts"] == 1
    assert src["status"] == "pending" and "connexion refusée" in src["error"]
    for wait in (75, 365, 2165):                         # attentes croissantes (60, 300, 1800 s ± 20 %)
        clock.advance(seconds=wait)
        run()
    assert job_row(aconn, f"apps.ingest_source:{sid}")["status"] == "dead"
    assert store.get_source(aconn, "panne", sid)["status"] == "error"


@pytest.mark.parametrize("status, kind, message", [
    (404, "text/html", "page introuvable (HTTP 404)"),
    (200, "application/pdf", "ne mène pas à une page web"),
])
def test_dead_links_fail_at_once(aconn, cfg, clock, web, run, status, kind, message):
    web.on("mort.fr", status=status, text="x", headers={"content-type": kind})
    store.create_app(aconn, cfg, now=clock(), app_id="mort", name="Mort", website_url="https://mort.fr")
    run()
    src = store.list_sources(aconn, "mort")[0]
    assert src["status"] == "error" and message in src["error"]
    assert job_row(aconn, f"apps.ingest_source:{src['id']}")["status"] == "dead"


PLAY = """<html><head>
<meta property="og:title" content="Habitudo – Applications sur Google Play">
<meta name="description" content="3 habitudes, une coche par soir.">
<script type="application/ld+json">{"@context": "https://schema.org", "@type": "SoftwareApplication",
 "name": "Habitudo", "description": "3 habitudes, une coche par soir.", "applicationCategory": "HEALTH_AND_FITNESS",
 "contentRating": "PEGI 3", "author": {"@type": "Person", "name": "Exemple SAS"},
 "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.5123", "ratingCount": "321"},
 "offers": [{"@type": "Offer", "price": "0", "priceCurrency": "EUR"}]}</script>
</head><body><div data-g-id="description">Coche tes habitudes chaque soir.<br>Garde ta série.</div></body></html>"""


def test_playstore_best_effort(aconn, cfg, clock, web, run):
    web.on("play.google.com", "/store/apps/details", text=PLAY, headers={"content-type": "text/html; charset=utf-8"})
    store.create_app(aconn, cfg, now=clock(), app_id="habitudo", name="Habitudo", langs=["fr"],
                     store_url_android="https://play.google.com/store/apps/details?id=com.exemple.habitudo")
    run()
    params = web.hits("play.google.com")[0].url.params
    assert (params["id"], params["hl"], params["gl"]) == ("com.exemple.habitudo", "fr", "FR")
    src = store.list_sources(aconn, "habitudo")[0]
    assert src["status"] == "ok" and src["title"] == "Habitudo"
    assert "Note : 4,5/5 sur 321 notes" in src["content"]
    assert "Description :\nCoche tes habitudes chaque soir.\nGarde ta série." in src["content"]
    assert src["meta"]["category"] == "HEALTH_AND_FITNESS" and src["meta"]["rating_count"] == 321


@pytest.mark.parametrize("value, expected", [
    ("https://apps.apple.com/fr/app/duolingo-langues-et-%C3%A9checs/id570060128", "570060128"),
    ("https://apps.apple.com/app/id570060128?mt=8", "570060128"),
    ("https://itunes.apple.com/us/app/name/id570060128?uo=4", "570060128"),
    ("id570060128", "570060128"),
    ("570060128", "570060128"),
    ("https://apps.apple.com/fr/app/sans-identifiant", None),
])
def test_appstore_id(value, expected):
    assert sources.appstore_id(value) == expected


def test_full_size_screenshot_url():
    url = "https://is1-ssl.mzstatic.com/image/thumb/PurpleSource211/v4/73/af/06/x_fr_iphone6.5_screen_1.png/320x480bb.jpg"
    assert sources.full_size(url) == url.removesuffix("320x480bb.jpg") + "3000x3000bb.png"


def test_local_addresses_are_refused_even_after_a_redirect(monkeypatch):
    """Le lien d'une source (ou sa redirection) qui mène au Mac lui-même ou au réseau local est refusé avant la
    requête : un site ne doit pas faire lire à Loopcast son propre dashboard (127.0.0.1:8787) ni le réseau.
    Avant : les redirections étaient suivies jusqu'à 127.0.0.1."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:8787/api/jobs"})
        return httpx.Response(200, text="<html><title>ok</title><p>Bonjour</p></html>",
                              headers={"content-type": "text/html"})

    addresses = {"public.example": ["93.184.216.34"], "fine.example": ["93.184.216.34"],
                 "lan.example": ["192.168.1.20"], "tailnet.example": ["100.101.102.103"],
                 "mixed.example": ["93.184.216.34", "127.0.0.1"], "localhost": ["127.0.0.1", "::1"]}
    monkeypatch.setattr(sources, "_resolve", lambda host, port: addresses[host])
    read = dict(lang="fr", max_bytes=100_000, max_chars=2000)
    with sources.new_client(5, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(sources.FetchError, match="adresse locale ou privée") as refused:
            sources.fetch_website(client, "http://public.example/", **read)
        assert refused.value.permanent and seen == ["http://public.example/"]      # 127.0.0.1 jamais contacté
        for url in ("http://127.0.0.1:8787/", "http://[::1]:8787/", "http://169.254.169.254/latest/",
                    "http://lan.example/", "http://tailnet.example/", "http://mixed.example/"):
            with pytest.raises(sources.FetchError, match="adresse locale ou privée"):
                sources.fetch_website(client, url, **read)
        with pytest.raises(sources.FetchError, match="locale ou privée"):
            sources.download(client, "http://localhost:8787/api/apps", max_bytes=1000)  # images aussi
        assert seen == ["http://public.example/"]
        assert sources.fetch_website(client, "http://fine.example/", **read).title == "ok"
