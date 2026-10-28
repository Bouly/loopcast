"""Données et faux services pour les tests du module apps."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Callable

import httpx
from PIL import Image

from loopcast.schemas import AssetAnalysis, Feature, Localized, Objection, Persona, ProductBrief, Question

REPO = Path(__file__).resolve().parents[3]


# --- Données -----------------------------------------------------------------------------------------

def png(width: int = 1290, height: int = 2796, color: tuple = (91, 91, 247)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


def brief(**over) -> ProductBrief:
    data = dict(
        app_name="Habitudo",
        one_liner=Localized(fr="3 habitudes, une coche par soir", en="3 habits, one check a night"),
        category="suivi d'habitudes", problem="On lâche ses résolutions.", solution="Une coche par soir.",
        value_props=["Tenir ses habitudes", "Une série qui motive", "Rien à gérer"],
        features=[Feature(name="Coche du soir", benefit="Valider sa journée", proof="Filmer la coche",
                          asset_ids=[1, 999])],
        personas=[Persona(name="Étudiante", description="20 ans", pains=["lâche vite"], desires=["régularité"],
                          triggers=["le soir"], langs=["fr", "en"])],
        differentiators=["3 habitudes seulement"], competitors=["Streaks"],
        objections=[Objection(objection="Encore une app", answer="10 secondes par soir")],
        proof_points=[], pricing="Gratuit", tone="direct", do_not_say=["résultat garanti"],
        cta=Localized(fr="Télécharge Habitudo", en="Get Habitudo"),
        keywords=Localized(fr="habitudes, routine", en="habit tracker"),
        unknowns=["Prix de l'offre premium"], confidence=0.6,
    )
    data.update(over)
    return ProductBrief(**data)


def question(text: str, priority: str = "bloquante", kind: str = "text", options: list[str] | None = None) -> Question:
    return Question(question=text, why="ça change les vidéos", kind=kind, options=options or [], priority=priority)


def analysis(**over) -> AssetAnalysis:
    data = dict(screen="accueil", shows="trois cartes d'habitudes", feature="cocher ses habitudes",
                on_screen_text=["Aujourd'hui"], usable_in_video=True, caution="")
    data.update(over)
    return AssetAnalysis(**data)


def texts(req) -> str:
    """Tout le texte d'une requête envoyée à (faux) Claude."""
    return "\n".join(b["text"] for b in req.content if b.get("type") == "text")


def images(req) -> list[dict]:
    return [b for b in req.content if b.get("type") == "image"]


class FakeWeb:
    """Faux internet pour httpx.MockTransport : on déclare des réponses par hôte, les requêtes sont gardées."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: list[tuple[str, str | None, Callable[[httpx.Request], httpx.Response]]] = []

    def on(self, host: str, path: str | None = None, *, fn: Callable[[httpx.Request], httpx.Response] | None = None,
           status: int = 200, text: str | None = None, content: bytes | None = None, json_body=None,
           headers: dict | None = None) -> None:
        def respond(_request: httpx.Request) -> httpx.Response:
            if json_body is not None:
                return httpx.Response(status, text=json.dumps(json_body), headers=headers)
            return httpx.Response(status, text=text, content=content, headers=headers)

        self.routes.append((host, path, fn or respond))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for host, path, fn in self.routes:
            if request.url.host == host and (path is None or request.url.path == path):
                return fn(request)
        return httpx.Response(404, text="introuvable")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def hits(self, host: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == host]


class Bus:
    """Remplace le bus SSE : garde ce que les routes publient."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, kind: str, data: dict) -> None:
        self.events.append((kind, data))


# --- Fausse fiche App Store ---------------------------------------------------------------------------

IOS = "https://apps.apple.com/fr/app/habitudo/id1234567890"
SHOT = "https://is1-ssl.mzstatic.com/image/thumb/PurpleSource/v4/{country}_{n}.png/392x696bb.png"


def record(country: str, n_shots: int = 2, **over) -> dict:
    """Une fiche telle que la renvoie https://itunes.apple.com/lookup (champs vérifiés sur l'API réelle)."""
    data = {
        "wrapperType": "software", "kind": "software", "trackId": 1234567890, "trackName": "Habitudo",
        "bundleId": "com.exemple.habitudo", "sellerName": "Exemple SAS", "artistName": "Exemple",
        "description": f"Description {country} : trois habitudes, une coche par soir.",
        "averageUserRating": 4.71234, "userRatingCount": 1234, "price": 0.0, "formattedPrice": "Gratuit",
        "currency": "EUR", "genres": ["Forme et santé", "Productivité"], "releaseNotes": "Corrections de bugs.",
        "version": "2.3.1", "currentVersionReleaseDate": "2026-10-20T10:00:00Z", "releaseDate": "2025-01-10T08:00:00Z",
        "screenshotUrls": [SHOT.format(country=country, n=i) for i in range(1, n_shots + 1)],
        "ipadScreenshotUrls": [], "contentAdvisoryRating": "4+", "minimumOsVersion": "17.0",
        "artworkUrl512": "https://is1-ssl.mzstatic.com/image/thumb/Purple/v4/icon.png/512x512bb.jpg",
        "languageCodesISO2A": ["FR", "EN"], "trackViewUrl": f"https://apps.apple.com/{country}/app/habitudo/id1234567890",
    }
    data.update(over)
    return data


def serve_appstore(web, records: dict[str, dict]) -> None:
    def lookup(request: httpx.Request) -> httpx.Response:
        rec = records.get(request.url.params.get("country"))
        body = {"resultCount": int(rec is not None), "results": [rec] if rec else []}
        return httpx.Response(200, text=json.dumps(body), headers={"content-type": "text/javascript; charset=utf-8"})

    def image(request: httpx.Request) -> httpx.Response:
        shade = sum(request.url.path.encode()) % 250       # une image différente par URL
        return httpx.Response(200, content=png(300, 650, (shade, 40, 90)), headers={"content-type": "image/png"})

    web.on("itunes.apple.com", "/lookup", fn=lookup)
    web.on("is1-ssl.mzstatic.com", fn=image)


def job_row(conn, key: str):
    return conn.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
