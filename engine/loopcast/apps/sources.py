"""Lire ce qui existe déjà sur l'app, sans clé ni compte.

- App Store : API publique iTunes Lookup, `https://itunes.apple.com/lookup?id=<id>&country=<cc>`.
  Réponse JSON servie en `text/javascript` : `{"resultCount": n, "results": [{"wrapperType":
  "software", "trackName", "description", "averageUserRating", "userRatingCount", "price",
  "formattedPrice", "currency", "genres", "releaseNotes", "version", "screenshotUrls", "artworkUrl512",
  …}]}`, `resultCount: 0` si l'app n'est pas dans cette vitrine. Apple tolère environ 20 appels par
  minute. Description, note, prix et captures sont propres à chaque vitrine : un appel par pays visé.
- Google Play : pas d'API publique ; au mieux, les balises meta, le JSON-LD et la description de la page.
- Site web : la page, texte principal extrait avec BeautifulSoup, borné.

Fonctions pures autour d'un client httpx : les tests passent un httpx.MockTransport (aucun réseau).

Le client de new_client() refuse, avant chaque requête (redirections comprises), un hôte qui mène au Mac
lui-même ou au réseau local (bouclage, adresse privée ou de lien local, Tailscale 100.64.0.0/10…) : le lien
d'une source ne doit jamais faire lire à Loopcast son propre dashboard ni une machine du réseau.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

LOOKUP_URL = "https://itunes.apple.com/lookup"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/18.0 Safari/605.1.15 Loopcast/0.1")

# La vitrine App Store / Google Play qui correspond à chaque langue visée.
LANG_COUNTRY = {"fr": "fr", "en": "us"}
_ACCEPT_LANGUAGE = {"fr": "fr-FR,fr;q=0.9,en;q=0.5", "en": "en-US,en;q=0.9"}
_STORE_HOSTS = {"apps.apple.com": "appstore", "itunes.apple.com": "appstore", "play.google.com": "playstore"}


class FetchError(Exception):
    """Lecture impossible. `permanent` : inutile de réessayer (lien mort, app introuvable…)."""

    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


@dataclass
class Fetched:
    """Ce qu'on garde d'une source : un titre, un texte lisible (pour Claude), des données (pour le code)."""
    title: str
    content: str
    meta: dict = field(default_factory=dict)


def new_client(timeout_s: float, *, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Le client des sources : chaque requête, redirections comprises, passe d'abord par check_public_url."""
    return httpx.Client(timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
                        headers={"User-Agent": USER_AGENT}, follow_redirects=True, transport=transport,
                        event_hooks={"request": [lambda request: check_public_url(request.url)]})


def _resolve(host: str, port: int) -> list[str]:
    """Les adresses IP de `host` (résolution du système)."""
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])           # sans l'identifiant de zone IPv6
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_public_url(url: httpx.URL | str) -> None:
    """FetchError (définitive) si l'hôte mène à une adresse de bouclage, privée, de lien local, partagée
    (Tailscale 100.64.0.0/10) ou réservée ; FetchError passagère si le nom ne se résout pas."""
    url = httpx.URL(str(url))
    host = url.raw_host.decode("ascii", "replace").strip("[]")
    if not host:
        raise FetchError("lien invalide : pas d'hôte", permanent=True)
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = _resolve(host, url.port or (443 if url.scheme == "https" else 80))
        except (OSError, UnicodeError) as e:
            raise FetchError(f"{url.host} : adresse introuvable ({e})") from e
    blocked = [a for a in addresses if not _is_public(a)]
    if blocked or not addresses:
        raise FetchError(f"lien refusé : {url.host} mène à une adresse locale ou privée "
                         f"({', '.join(blocked) or 'aucune adresse'}) ; seuls les sites publics sont lus",
                         permanent=True)


def source_kind(url: str) -> str:
    """appstore | playstore | website, d'après l'adresse."""
    return _STORE_HOSTS.get((urlsplit(url).hostname or "").lower(), "website")


# --- HTTP ----------------------------------------------------------------------------------------------

def _check_status(r: httpx.Response, what: str) -> None:
    code = r.status_code
    if code < 400:
        return
    if code in (408, 425, 429) or code >= 500:
        raise FetchError(f"{what} : HTTP {code}, nouvel essai plus tard")
    if code in (404, 410):
        raise FetchError(f"{what} : page introuvable (HTTP {code}), vérifier le lien", permanent=True)
    raise FetchError(f"{what} : accès refusé (HTTP {code})", permanent=True)


def _network_error(what: str, e: Exception) -> FetchError:
    if isinstance(e, httpx.TimeoutException):
        return FetchError(f"{what} : délai dépassé")
    if isinstance(e, httpx.UnsupportedProtocol):
        return FetchError(f"{what} : lien invalide ({e})", permanent=True)
    return FetchError(f"{what} : {type(e).__name__} {e}")


def _get(client: httpx.Client, url: str, *, what: str, params: dict | None = None) -> httpx.Response:
    try:
        r = client.get(url, params=params, follow_redirects=True)
    except httpx.HTTPError as e:
        raise _network_error(what, e) from e
    _check_status(r, what)
    return r


def _read_limited(client: httpx.Client, url: str, *, what: str, max_bytes: int,
                  headers: dict | None = None) -> tuple[httpx.Response, bytes, bool]:
    """GET en flux, arrêté à `max_bytes` : (réponse, corps, tronqué ?)."""
    try:
        with client.stream("GET", url, headers=headers, follow_redirects=True) as r:
            _check_status(r, what)
            buf = bytearray()
            truncated = False
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > max_bytes:
                    del buf[max_bytes:]
                    truncated = True
                    break
            return r, bytes(buf), truncated
    except httpx.HTTPError as e:
        raise _network_error(what, e) from e


def download(client: httpx.Client, url: str, *, max_bytes: int, what: str = "image") -> bytes:
    _r, data, truncated = _read_limited(client, url, what=what, max_bytes=max_bytes)
    if truncated:
        raise FetchError(f"{what} trop lourde ({max_bytes // 1_000_000} Mo au plus)", permanent=True)
    return data


def _decode(raw: bytes, r: httpx.Response) -> str:
    charset = r.charset_encoding
    if not charset:
        m = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", raw[:4096], re.I)
        charset = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


# --- App Store -------------------------------------------------------------------------------------------

_APPSTORE_ID = re.compile(r"/id(\d{5,})")
_SIZE_SUFFIX = re.compile(r"/\d+x\d+[a-z]*\.(?:png|jpe?g|webp)$", re.I)


def appstore_id(value: str) -> str | None:
    """« https://apps.apple.com/fr/app/nom/id570060128 », « id570060128 » ou « 570060128 » → « 570060128 »."""
    value = (value or "").strip()
    if value.isdigit():
        return value
    if value.startswith("id") and value[2:].isdigit():
        return value[2:]
    parts = urlsplit(value)
    m = _APPSTORE_ID.search(parts.path)
    if m:
        return m.group(1)
    q = (parse_qs(parts.query).get("id") or [""])[0]
    return q if q.isdigit() else None


def appstore_countries(url: str, langs: list[str]) -> list[str]:
    """Le pays du lien (/fr/app/…) d'abord, puis la vitrine de chaque langue visée."""
    out: list[str] = []
    m = re.match(r"/([a-z]{2})/", urlsplit(url).path)
    if m:
        out.append(m.group(1))
    for lang in langs:
        country = LANG_COUNTRY.get(lang)
        if country and country not in out:
            out.append(country)
    return out or ["us"]


def appstore_lookup(client: httpx.Client, track_id: str, country: str) -> dict | None:
    """La fiche de l'app dans la vitrine `country`, ou None si elle n'y est pas."""
    r = _get(client, LOOKUP_URL, what=f"App Store ({country})", params={"id": track_id, "country": country})
    try:
        data = json.loads(r.text)        # servi en text/javascript : on lit le texte nous-mêmes
    except ValueError as e:
        raise FetchError(f"App Store ({country}) : réponse illisible ({e})") from e
    for item in data.get("results") or []:
        if item.get("wrapperType") == "software" or item.get("kind") == "software":
            return item
    return None


def full_size(url: str) -> str:
    """Les images de l'App Store sont servies à la taille écrite en fin d'URL (/392x696bb.png) ;
    une boîte de 3000 px renvoie l'original, sans l'agrandir."""
    return _SIZE_SUFFIX.sub("/3000x3000bb.png", url)


def _fr_decimal(x: float | None) -> str:
    return f"{x:.1f}".replace(".", ",") if isinstance(x, (int, float)) else "?"


def _fr_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _fr_date(iso_date: str | None) -> str:
    """« 2026-10-20T10:00:00Z » → « 20/10/2026 » (les dates lues par Claude sont à la française)."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso_date or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else ""


def _appstore_text(country: str, rec: dict, day: str) -> str:
    lines = [f"Fiche App Store {country.upper()} (relevée le {_fr_date(day)}) : {rec.get('trackName', '')}"]
    facts = []
    if rec.get("sellerName") or rec.get("artistName"):
        facts.append(f"éditeur : {rec.get('sellerName') or rec.get('artistName')}")
    if rec.get("genres"):
        facts.append(f"catégories : {', '.join(rec['genres'])}")
    if rec.get("formattedPrice") or rec.get("price") is not None:
        facts.append(f"prix à l'achat : {rec.get('formattedPrice') or rec.get('price')}")
    if rec.get("contentAdvisoryRating"):
        facts.append(f"âge : {rec['contentAdvisoryRating']}")
    if facts:
        lines.append(" · ".join(facts))
    count = rec.get("userRatingCount") or 0
    if count:
        lines.append(f"Note : {_fr_decimal(rec.get('averageUserRating'))}/5 sur {_fr_int(count)} notes")
    else:
        lines.append("Note : pas encore de notes dans cette vitrine")
    if rec.get("version"):
        lines.append(f"Version {rec['version']} du {_fr_date(rec.get('currentVersionReleaseDate'))}")
    if (rec.get("releaseNotes") or "").strip():
        lines.append(f"Nouveautés de cette version :\n{rec['releaseNotes'].strip()}")
    if (rec.get("description") or "").strip():
        lines.append(f"Description :\n{rec['description'].strip()}")
    return "\n".join(lines)


def appstore_source(records: dict[str, dict], *, max_chars: int, now: datetime) -> Fetched:
    """Les fiches par pays → titre, texte (borné, partagé entre les pays) et meta."""
    first = next(iter(records.values()))
    day = now.date().isoformat()
    share = max_chars // max(1, len(records))
    countries = {}
    texts = []
    for country, rec in records.items():
        countries[country] = {
            "name": rec.get("trackName"),
            "rating": rec.get("averageUserRating"),
            "rating_count": rec.get("userRatingCount") or 0,
            "price": rec.get("price"),
            "formatted_price": rec.get("formattedPrice"),
            "currency": rec.get("currency"),
            "genres": rec.get("genres") or [],
            "version": rec.get("version"),
            "version_date": (rec.get("currentVersionReleaseDate") or "")[:10] or None,
            "release_notes": (rec.get("releaseNotes") or "")[:2000],
            "screenshot_urls": rec.get("screenshotUrls") or [],
            "ipad_screenshot_count": len(rec.get("ipadScreenshotUrls") or []),
            "url": rec.get("trackViewUrl"),
        }
        texts.append(_cut(_appstore_text(country, rec, day), share))
    meta = {
        "track_id": first.get("trackId"),
        "bundle_id": first.get("bundleId"),
        "seller": first.get("sellerName") or first.get("artistName"),
        "seller_url": first.get("sellerUrl"),
        "artwork_url": first.get("artworkUrl512") or first.get("artworkUrl100"),
        "content_rating": first.get("contentAdvisoryRating") or first.get("trackContentRating"),
        "minimum_os": first.get("minimumOsVersion"),
        "languages": first.get("languageCodesISO2A") or [],
        "release_date": (first.get("releaseDate") or "")[:10] or None,
        "countries": countries,
        "fetched_on": day,
    }
    return Fetched(title=first.get("trackName") or "", content="\n\n".join(texts), meta=meta)


# --- Google Play ------------------------------------------------------------------------------------------

def playstore_id(url: str) -> str | None:
    """« https://play.google.com/store/apps/details?id=com.exemple.app » → « com.exemple.app »."""
    parts = urlsplit((url or "").strip())
    if (parts.hostname or "").lower() != "play.google.com":
        return None
    pkg = (parse_qs(parts.query).get("id") or [""])[0]
    return pkg if re.fullmatch(r"[A-Za-z][\w]*(\.[\w]+)+", pkg) else None


def playstore_page(pkg: str, lang: str) -> str:
    country = LANG_COUNTRY.get(lang, "us").upper()
    return f"https://play.google.com/store/apps/details?id={pkg}&hl={lang}&gl={country}"


def fetch_playstore(client: httpx.Client, url: str, *, lang: str, max_bytes: int, max_chars: int) -> Fetched:
    pkg = playstore_id(url)
    if not pkg:
        raise FetchError("lien Google Play sans identifiant (…/details?id=com.exemple.app)", permanent=True)
    r, raw, _ = _read_limited(client, playstore_page(pkg, lang), what="Google Play", max_bytes=max_bytes,
                              headers={"Accept-Language": _ACCEPT_LANGUAGE.get(lang, "en")})
    return parse_playstore(_decode(raw, r), pkg=pkg, lang=lang, max_chars=max_chars)


def parse_playstore(html: str, *, pkg: str, lang: str, max_chars: int) -> Fetched:
    soup = BeautifulSoup(html, "html.parser")
    ld = next((d for d in _ld_json(soup) if d.get("@type") == "SoftwareApplication"), {})
    name = ld.get("name") or re.sub(r"\s+[–-]\s+(Applications sur|Apps on) Google Play$", "",
                                    _meta(soup, "og:title"))
    if not name:
        raise FetchError("Google Play : page illisible (format inattendu)", permanent=True)
    short = ld.get("description") or _meta(soup, "description") or _meta(soup, "og:description")
    long_el = soup.select_one('[data-g-id="description"]')
    long = _block_text(long_el) if long_el else ""
    rating = ld.get("aggregateRating") or {}
    offers = ld.get("offers") or []
    offer = offers[0] if isinstance(offers, list) and offers else (offers if isinstance(offers, dict) else {})
    author = ld.get("author") or {}
    meta = {
        "package": pkg, "lang": lang, "name": name,
        "category": ld.get("applicationCategory"),
        "content_rating": ld.get("contentRating"),
        "rating": _float(rating.get("ratingValue")),
        "rating_count": int(_float(rating.get("ratingCount")) or 0),
        "price": offer.get("price"), "currency": offer.get("priceCurrency"),
        "developer": author.get("name") if isinstance(author, dict) else None,
        "icon_url": ld.get("image") or _meta(soup, "og:image"),
    }
    lines = [f"Fiche Google Play ({lang}) : {name}"]
    facts = [f"{k} : {v}" for k, v in (("catégorie", meta["category"]), ("éditeur", meta["developer"]),
                                        ("classification", meta["content_rating"])) if v]
    if meta["price"] is not None:
        facts.append(f"prix à l'achat : {meta['price']} {meta['currency'] or ''}".strip())
    if facts:
        lines.append(" · ".join(facts))
    if meta["rating_count"]:
        lines.append(f"Note : {_fr_decimal(meta['rating'])}/5 sur {_fr_int(meta['rating_count'])} notes")
    if short:
        lines.append(f"Description courte : {short}")
    if long:
        lines.append(f"Description :\n{long}")
    return Fetched(title=name, content=_cut("\n".join(lines), max_chars), meta=meta)


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --- Site web -----------------------------------------------------------------------------------------------

_DROP = ("script", "style", "noscript", "svg", "template", "iframe", "form", "nav", "footer", "button",
         "select", "dialog", "canvas", "video", "audio")
_NOISE = re.compile(r"cookie|consent|gdpr|rgpd|newsletter|popup|modal", re.I)
_BLOCKS = ("p", "div", "section", "article", "main", "header", "aside", "blockquote", "pre", "ul", "ol", "li",
           "dl", "dt", "dd", "table", "tr", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr")


def fetch_website(client: httpx.Client, url: str, *, lang: str, max_bytes: int, max_chars: int) -> Fetched:
    r, raw, truncated = _read_limited(
        client, url, what="site", max_bytes=max_bytes,
        headers={"Accept": "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.8",
                 "Accept-Language": _ACCEPT_LANGUAGE.get(lang, "en")})
    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype and ctype not in ("text/html", "application/xhtml+xml", "text/plain"):
        raise FetchError(f"site : le lien ne mène pas à une page web ({ctype})", permanent=True)
    text = _decode(raw, r)
    if ctype == "text/plain":
        content = _clean_lines(text)
        return Fetched(title=url, content=_cut(content, max_chars),
                       meta={"url": str(r.url), "truncated": truncated or len(content) > max_chars})
    return parse_website(text, str(r.url), max_chars=max_chars, truncated=truncated)


def parse_website(html: str, base_url: str, *, max_chars: int, truncated: bool = False) -> Fetched:
    soup = BeautifulSoup(html, "html.parser")
    title = _meta(soup, "og:title") or (soup.title.get_text(" ", strip=True) if soup.title else "")
    description = _meta(soup, "description") or _meta(soup, "og:description")
    links = _store_links(soup, base_url)           # avant le nettoyage : les badges sont souvent en pied de page
    body = _main_text(soup)
    head = "\n".join(x for x in (f"Titre : {title}" if title else "",
                                 f"Description : {description}" if description else "") if x)
    content = f"{head}\n\n{body}".strip()
    meta = {"url": base_url, "description": description, "store_links": links,
            "truncated": truncated or len(content) > max_chars}
    return Fetched(title=title or base_url, content=_cut(content, max_chars), meta=meta)


def _meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return (tag.get("content") or "").strip() if tag else ""


def _ld_json(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except ValueError:
            continue
        items = data if isinstance(data, list) else (data.get("@graph") or [data]) if isinstance(data, dict) else []
        out.extend(d for d in items if isinstance(d, dict))
    return out


def _store_links(soup: BeautifulSoup, base_url: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"appstore": [], "playstore": []}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        kind = _STORE_HOSTS.get((urlsplit(href).hostname or "").lower())
        if kind and href not in out[kind]:
            out[kind].append(href)
    return out


def _main_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(_DROP):
        tag.decompose()
    for tag in soup.find_all(True, attrs={"id": _NOISE}) + soup.find_all(True, class_=_NOISE):
        if not tag.decomposed and tag.name not in ("html", "body", "main", "article"):
            tag.decompose()
    root = soup.find("main") or soup.find("article")
    if root is None or len(root.get_text(strip=True)) < 300:
        root = soup.body or soup
    return _block_text(root)


def _block_text(root) -> str:
    """Le texte d'un élément, une ligne par bloc (titres marqués #, listes marquées -)."""
    for level in range(1, 4):
        for h in root.find_all(f"h{level}"):
            h.insert(0, "#" * level + " ")
    for li in root.find_all("li"):
        li.insert(0, "- ")
    for tag in root.find_all(_BLOCKS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    return _clean_lines(root.get_text())


def _clean_lines(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line in ("", "-", "#", "##", "###") or (out and out[-1] == line):
            continue
        out.append(line)
    return "\n".join(out)


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    return text[: cut if cut > limit * 0.8 else limit].rstrip() + "\n[…]"
