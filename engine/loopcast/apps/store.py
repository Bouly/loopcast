"""Les apps en base : création (avec reprise de brands/<id>.json), sources, questions, fiches
versionnées et statut. Utilisé par les routes, la CLI et les tâches du module.

Chaque fonction reçoit la connexion du thread appelant et l'heure (`now`, horloge injectable). Les
erreurs de donnée lèvent AppError (message en français + code HTTP) : les routes en font une réponse
HTTP, les tâches un jobs.Permanent.

Statut de l'app : draft → analyzing → questions → brief_ready, puis strategy_ready → active (module
strategy) ; paused à la main. Ce module ne fait évoluer le statut que pendant la compréhension
(UNDERSTANDING) : une app déjà en stratégie, active ou en pause ne recule pas quand on relance une
analyse ; la nouvelle version de la fiche attend simplement d'être approuvée.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from loopcast import jobs
from loopcast.apps import sources
from loopcast.jobs import iso
from loopcast.schemas import ProductBrief, Question

LANGS = ("fr", "en")
UNDERSTANDING = ("draft", "analyzing", "questions", "brief_ready")
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
URL_FIELDS = (("store_url_ios", "appstore"), ("store_url_android", "playstore"), ("website_url", "website"))
MAX_DESCRIPTION = 20_000
MAX_TEXT_SOURCE = 20_000
_STATUS_FR = {"open": "ouverte", "answered": "répondue", "skipped": "passée"}


class AppError(Exception):
    """Donnée invalide ou action impossible : message en français, `status` = code HTTP."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class NotFound(AppError):
    def __init__(self, message: str):
        super().__init__(message, 404)


class Conflict(AppError):
    def __init__(self, message: str):
        super().__init__(message, 409)


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transaction courte. BEGIN IMMEDIATE : deux écritures concurrentes passent l'une après l'autre
    (numéros de version calculés sous verrou). Un appel imbriqué rejoint la transaction en cours."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def event(conn: sqlite3.Connection, now: datetime, kind: str, message: str) -> None:
    """Événement notable, visible dans le journal (kind préfixé « apps. »)."""
    conn.execute("INSERT INTO events(at, kind, message) VALUES (?,?,?)", (iso(now), kind, message))


# --- Apps -------------------------------------------------------------------------------------------------

def slugify(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40].strip("-")


def normalize_langs(langs: Any) -> list[str]:
    if isinstance(langs, str):
        langs = langs.split(",")
    out: list[str] = []
    for lang in langs or []:
        lang = str(lang).strip().lower()
        if lang not in LANGS:
            raise AppError(f"langue non prise en charge : « {lang} » (fr ou en)")
        if lang not in out:
            out.append(lang)
    if not out:
        raise AppError("au moins une langue visée : fr ou en")
    return out


def clean_url(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        raise AppError(f"lien invalide : « {value} » (il doit commencer par https://)")
    return value


def _check_store_urls(app: dict) -> None:
    if app.get("store_url_ios") and not sources.appstore_id(app["store_url_ios"]):
        raise AppError("lien App Store sans identifiant de l'app (…/id123456789)")
    if app.get("store_url_android") and not sources.playstore_id(app["store_url_android"]):
        raise AppError("lien Google Play sans identifiant de l'app (…/details?id=com.exemple.app)")


def app_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["langs"] = loads(d.get("langs"), list(LANGS))
    d["brand"] = loads(d.get("brand"), {})
    return d


def get_app(conn: sqlite3.Connection, app_id: str) -> dict:
    r = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
    if r is None:
        raise NotFound(f"app inconnue : « {app_id} »")
    return app_dict(r)


def list_apps(conn: sqlite3.Connection) -> list[dict]:
    ids = [r["id"] for r in conn.execute("SELECT id FROM apps ORDER BY status='paused', name COLLATE NOCASE")]
    return [app_overview(conn, i) for i in ids]


def create_app(conn: sqlite3.Connection, config: Any, *, now: datetime, app_id: str | None = None,
               name: str | None = None, description: str | None = None, store_url_ios: str | None = None,
               store_url_android: str | None = None, website_url: str | None = None,
               langs: Any = None, brand: dict | None = None) -> dict:
    """Crée l'app. Si brands/<id>.json existe, il sert de valeur initiale (ce qui est fourni prime)."""
    app_id = (app_id or "").strip().lower() or slugify(name or "")
    if not SLUG_RE.fullmatch(app_id):
        raise AppError("identifiant invalide : minuscules, chiffres et tirets, 40 caractères au plus "
                       "(ex. « habitudo »)")
    brand_data = read_brand(config, app_id)
    base = brand_defaults(brand_data) if brand_data else {}
    name = (name or base.get("name") or "").strip()
    if not name:
        raise AppError("le nom de l'app est obligatoire")
    app = {
        "id": app_id,
        "name": name[:120],
        "description": (description if description is not None else base.get("description") or "").strip(),
        "store_url_ios": clean_url(store_url_ios) or base.get("store_url_ios"),
        "store_url_android": clean_url(store_url_android) or base.get("store_url_android"),
        "website_url": clean_url(website_url) or base.get("website_url"),
        "langs": normalize_langs(langs or base.get("langs") or list(LANGS)),
        "brand": {**base.get("brand", {}), **{k: v for k, v in (brand or {}).items() if v is not None}},
    }
    if len(app["description"]) > MAX_DESCRIPTION:
        raise AppError(f"description trop longue ({MAX_DESCRIPTION} caractères au plus) : "
                       "ajouter le reste comme texte collé")
    _check_store_urls(app)
    with tx(conn):
        if conn.execute("SELECT 1 FROM apps WHERE id=?", (app_id,)).fetchone():
            raise Conflict(f"l'app « {app_id} » existe déjà")
        conn.execute(
            """INSERT INTO apps(id, name, description, store_url_ios, store_url_android, website_url, langs, brand,
                                status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,'draft',?,?)""",
            (app_id, app["name"], app["description"], app["store_url_ios"], app["store_url_android"],
             app["website_url"], dumps(app["langs"]), dumps(app["brand"]), iso(now), iso(now)),
        )
        sync_url_sources(conn, app, now=now)
        event(conn, now, "apps.created", f"{app['name']} : app ajoutée")
    if brand_data:
        from loopcast.apps import assets   # import local : assets dépend de ce module

        assets.import_brand_files(conn, config, app_id, brand_data, now=now)
    return get_app(conn, app_id)


EDITABLE = ("name", "description", "store_url_ios", "store_url_android", "website_url", "langs", "brand")


def update_app(conn: sqlite3.Connection, app_id: str, changes: dict, *, now: datetime) -> dict:
    """Modifie l'app. `brand` est fusionné (une clé à None la retire). Un lien qui change remplace sa
    source ; des langues qui changent font relire l'App Store et Google Play (vitrines différentes)."""
    with tx(conn):
        app = get_app(conn, app_id)
        new = dict(app)
        if "name" in changes:
            new["name"] = (changes["name"] or "").strip()[:120]
            if not new["name"]:
                raise AppError("le nom de l'app est obligatoire")
        if "description" in changes:
            new["description"] = (changes["description"] or "").strip()
            if len(new["description"]) > MAX_DESCRIPTION:
                raise AppError(f"description trop longue ({MAX_DESCRIPTION} caractères au plus)")
        for field, _kind in URL_FIELDS:
            if field in changes:
                new[field] = clean_url(changes[field])
        if changes.get("langs") is not None:
            new["langs"] = normalize_langs(changes["langs"])
        if changes.get("brand") is not None:
            merged = {**app["brand"], **changes["brand"]}
            new["brand"] = {k: v for k, v in merged.items() if v is not None}
        _check_store_urls(new)
        conn.execute(
            """UPDATE apps SET name=?, description=?, store_url_ios=?, store_url_android=?, website_url=?, langs=?,
                               brand=?, updated_at=? WHERE id=?""",
            (new["name"], new["description"], new["store_url_ios"], new["store_url_android"], new["website_url"],
             dumps(new["langs"]), dumps(new["brand"]), iso(now), app_id),
        )
        for field, kind in URL_FIELDS:
            if app.get(field) and app[field] != new.get(field):
                conn.execute("DELETE FROM app_sources WHERE app_id=? AND kind=? AND url=?", (app_id, kind, app[field]))
        created = sync_url_sources(conn, new, now=now)
        if new["langs"] != app["langs"]:
            for r in conn.execute("SELECT id FROM app_sources WHERE app_id=? AND kind IN ('appstore','playstore')",
                                  (app_id,)).fetchall():
                if r["id"] not in created:
                    refresh_source(conn, app_id, r["id"], now=now)
    return get_app(conn, app_id)


def pause_app(conn: sqlite3.Connection, app_id: str, *, now: datetime) -> dict:
    with tx(conn):
        app = get_app(conn, app_id)
        if app["status"] != "paused":
            conn.execute("UPDATE apps SET paused_from=status, status='paused', updated_at=? WHERE id=?",
                         (iso(now), app_id))
            event(conn, now, "apps.paused", f"{app['name']} : mise en pause")
    return get_app(conn, app_id)


def resume_app(conn: sqlite3.Connection, app_id: str, *, now: datetime) -> dict:
    """Retrouve le statut d'avant la pause (recalculé s'il était en phase de compréhension : une analyse
    a pu se terminer entre-temps)."""
    with tx(conn):
        app = get_app(conn, app_id)
        if app["status"] == "paused":
            status = app.get("paused_from") or "draft"
            if status in UNDERSTANDING:
                status = understanding_status(conn, app_id)
            conn.execute("UPDATE apps SET status=?, paused_from=NULL, updated_at=? WHERE id=?",
                         (status, iso(now), app_id))
            event(conn, now, "apps.resumed", f"{app['name']} : reprise")
    return get_app(conn, app_id)


def set_status(conn: sqlite3.Connection, app_id: str, status: str, *, now: datetime) -> bool:
    """Change le statut si l'app est encore en phase de compréhension (voir l'en-tête du module)."""
    marks = ",".join("?" * len(UNDERSTANDING))
    cur = conn.execute(f"UPDATE apps SET status=?, updated_at=? WHERE id=? AND status IN ({marks})",
                       (status, iso(now), app_id, *UNDERSTANDING))
    return cur.rowcount == 1


def understanding_status(conn: sqlite3.Connection, app_id: str, *, exclude_job: int | None = None) -> str:
    """Le statut que l'état des données justifie : analyse en cours, questions ouvertes, fiche, rien."""
    busy = conn.execute(
        """SELECT 1 FROM jobs WHERE app_id=? AND kind IN ('apps.analyze','apps.refine')
           AND status IN ('queued','running') AND id != ? LIMIT 1""", (app_id, exclude_job or -1)).fetchone()
    if busy:
        return "analyzing"
    if conn.execute("SELECT 1 FROM app_questions WHERE app_id=? AND status='open' LIMIT 1", (app_id,)).fetchone():
        return "questions"
    if conn.execute("SELECT 1 FROM app_briefs WHERE app_id=? LIMIT 1", (app_id,)).fetchone():
        return "brief_ready"
    return "draft"


def app_overview(conn: sqlite3.Connection, app_id: str) -> dict:
    """L'app et son avancement : compteurs, dernière fiche, tâches en cours ou en échec."""
    app = get_app(conn, app_id)

    def count(sql: str) -> int:
        return conn.execute(sql, (app_id,)).fetchone()[0]

    app["counts"] = {
        "assets": count("SELECT COUNT(*) FROM app_assets WHERE app_id=?"),
        "screenshots": count("SELECT COUNT(*) FROM app_assets WHERE app_id=? AND kind='screenshot'"),
        "described": count("SELECT COUNT(*) FROM app_assets WHERE app_id=? AND analysis IS NOT NULL"),
        "sources": count("SELECT COUNT(*) FROM app_sources WHERE app_id=?"),
        "sources_pending": count("SELECT COUNT(*) FROM app_sources WHERE app_id=? AND status='pending'"),
        "sources_error": count("SELECT COUNT(*) FROM app_sources WHERE app_id=? AND status='error'"),
        "questions_open": count("SELECT COUNT(*) FROM app_questions WHERE app_id=? AND status='open'"),
        # Ce qui attend l'équipe plus loin dans le parcours : idées à relire, vidéos à valider.
        "ideas_proposed": count("SELECT COUNT(*) FROM ideas WHERE app_id=? AND status='proposed'"),
        "to_review": count("SELECT COUNT(*) FROM content WHERE app_id=? AND status='rendered' "
                           "AND json_extract(qa, '$.ok') = 1"),
    }
    latest = latest_brief(conn, app_id)
    approved = latest_brief(conn, app_id, approved=True)
    app["brief"] = None if latest is None else {
        k: latest[k] for k in ("id", "version", "origin", "created_at", "approved_at")
    } | {"one_liner": latest["brief"].get("one_liner"), "confidence": latest["brief"].get("confidence")}
    app["approved_version"] = approved["version"] if approved else None
    app["jobs"] = app_jobs(conn, app_id)
    return app


def app_jobs(conn: sqlite3.Connection, app_id: str) -> dict:
    """Tâches du module pour cette app : en cours et en échec (une tâche annulée disparaît)."""
    rows = conn.execute(
        """SELECT id, kind, status, attempts, max_attempts, last_error, run_after FROM jobs
           WHERE app_id=? AND kind LIKE 'apps.%' AND status IN ('queued','running','dead') ORDER BY id""",
        (app_id,)).fetchall()
    pending = [{"id": r["id"], "kind": r["kind"], "status": r["status"], "run_after": r["run_after"]}
               for r in rows if r["status"] != "dead"]
    failed = [{"id": r["id"], "kind": r["kind"],
               "error": next((ln for ln in (r["last_error"] or "").splitlines() if ln.strip()), "")[:300]}
              for r in rows if r["status"] == "dead"]
    return {"pending": pending, "failed": failed}


def has_material(conn: sqlite3.Connection, app: dict) -> bool:
    """Y a-t-il de quoi analyser : une description, une source lisible, une capture ou un document ?"""
    if (app.get("description") or "").strip():
        return True
    if conn.execute("SELECT 1 FROM app_sources WHERE app_id=? AND status!='error' LIMIT 1", (app["id"],)).fetchone():
        return True
    return bool(conn.execute("SELECT 1 FROM app_assets WHERE app_id=? AND kind!='logo' LIMIT 1",
                             (app["id"],)).fetchone())


def request_analysis(conn: sqlite3.Connection, app_id: str, *, now: datetime) -> int:
    """Enfile apps.analyze (clé apps.analyze:<app_id>:<version visée>) ; relance celle qui avait échoué.
    Une analyse déjà en attente ou en cours pour l'app est réutilisée (une en attente lira tout ce qui a été
    ajouté entre-temps ; pour tenir compte d'un ajout fait pendant une analyse en cours, relancer après)."""
    with tx(conn):
        app = get_app(conn, app_id)
        if not has_material(conn, app):
            raise Conflict("rien à analyser : ajoutez une description, un lien (App Store, site) ou des captures")
        waiting = conn.execute("SELECT id FROM jobs WHERE app_id=? AND kind='apps.analyze' AND status IN "
                               "('queued','running') ORDER BY id LIMIT 1", (app_id,)).fetchone()
        if waiting is not None:
            set_status(conn, app_id, "analyzing", now=now)
            return waiting["id"]
        key = f"apps.analyze:{app_id}:{next_version(conn, app_id)}"
        job_id = jobs.enqueue(conn, "apps.analyze", {"app_id": app_id}, key=key, app_id=app_id, clock=lambda: now)
        if conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()["status"] in ("dead", "cancelled"):
            jobs.retry(conn, job_id, clock=lambda: now)
        set_status(conn, app_id, "analyzing", now=now)
    return job_id


# --- Fichiers de marque (brands/<id>.json) --------------------------------------------------------------------

_BRAND_TEXT = (("promise", "Promesse"), ("audience", "Public visé"), ("pains", "Problèmes du public"),
               ("tone", "Ton de la marque"))


def brand_path(config: Any, app_id: str) -> Path:
    return Path(config.root) / "brands" / f"{app_id}.json"


def read_brand(config: Any, app_id: str) -> dict | None:
    path = brand_path(config, app_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except ValueError as e:
        raise AppError(f"brands/{path.name} n'est pas un JSON valide : {e}") from e
    return data if isinstance(data, dict) else None


def brand_defaults(data: dict) -> dict:
    """Ce qu'un fichier de marque apporte à la création (les liens « CHANGE_ME » sont ignorés)."""

    def url(value: Any) -> str | None:
        ok = isinstance(value, str) and value.startswith("http") and "change_me" not in value.lower()
        return value if ok else None

    stores = data.get("stores") or {}
    store_line = data.get("storeLine") or {}
    return {
        "name": data.get("name"),
        "description": brand_description(data),
        "store_url_ios": url(stores.get("ios")),
        "store_url_android": url(stores.get("android")),
        "website_url": url(data.get("website")),
        "langs": [lang for lang in LANGS if lang in store_line] or list(LANGS),
        "brand": {k: data[k] for k in ("accent", "accentInk", "handle", "storeLine") if data.get(k)},
    }


def brand_description(data: dict) -> str:
    """Promesse, public, problèmes et ton du fichier de marque, mis en clair (dans chaque langue)."""
    lines = [f"Catégorie : {data['category']}"] if data.get("category") else []
    for key, label in _BRAND_TEXT:
        value = data.get(key)
        for lang, text in (value.items() if isinstance(value, dict) else [("", value)]):
            if text:
                text = " ; ".join(text) if isinstance(text, list) else str(text)
                lines.append(f"{label}{f' ({lang})' if lang else ''} : {text}")
    return "\n".join(lines)


def brand_files(conn: sqlite3.Connection, config: Any) -> list[dict]:
    """Les fichiers brands/*.json, et s'ils ont déjà donné une app."""
    out = []
    for path in sorted((Path(config.root) / "brands").glob("*.json")):
        if not SLUG_RE.fullmatch(path.stem):
            continue
        try:
            name = json.loads(path.read_text()).get("name") or path.stem
        except (ValueError, AttributeError):
            continue
        imported = conn.execute("SELECT 1 FROM apps WHERE id=?", (path.stem,)).fetchone() is not None
        out.append({"id": path.stem, "name": name, "imported": imported})
    return out


# --- Sources ----------------------------------------------------------------------------------------------------

def source_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["meta"] = loads(d.get("meta"), {})
    return d


def list_sources(conn: sqlite3.Connection, app_id: str) -> list[dict]:
    get_app(conn, app_id)
    return [source_dict(r) for r in conn.execute("SELECT * FROM app_sources WHERE app_id=? ORDER BY id", (app_id,))]


def get_source(conn: sqlite3.Connection, app_id: str, source_id: int) -> dict:
    r = conn.execute("SELECT * FROM app_sources WHERE id=? AND app_id=?", (source_id, app_id)).fetchone()
    if r is None:
        raise NotFound(f"source {source_id} inconnue pour cette app")
    return source_dict(r)


def add_source(conn: sqlite3.Connection, app_id: str, *, now: datetime, url: str | None = None,
               text: str | None = None, title: str | None = None, kind: str | None = None,
               parent_id: int | None = None) -> tuple[dict, bool]:
    """Ajoute un lien (lu par la tâche apps.ingest_source) ou un texte collé (prêt tout de suite).
    Renvoie (source, créée ?) : un lien déjà connu n'est pas ajouté deux fois."""
    with tx(conn):
        get_app(conn, app_id)
        if text is not None:
            text = text.strip()
            if not text:
                raise AppError("texte vide")
            meta = {"chars": len(text), "truncated": len(text) > MAX_TEXT_SOURCE}
            cur = conn.execute(
                """INSERT INTO app_sources(app_id, kind, title, content, meta, status, fetched_at, created_at)
                   VALUES (?, 'text', ?, ?, ?, 'ok', ?, ?)""",
                (app_id, (title or "").strip()[:200] or "Texte collé", text[:MAX_TEXT_SOURCE], dumps(meta),
                 iso(now), iso(now)))
            return get_source(conn, app_id, cur.lastrowid), True
        url = clean_url(url)
        if url is None:
            raise AppError("un lien ou un texte est obligatoire")
        kind = kind or sources.source_kind(url)
        if kind not in ("appstore", "playstore", "website"):
            raise AppError(f"type de source inconnu : « {kind} » (appstore, playstore, website ou un texte)")
        if kind == "appstore" and not sources.appstore_id(url):
            raise AppError("lien App Store sans identifiant de l'app (…/id123456789)")
        if kind == "playstore" and not sources.playstore_id(url):
            raise AppError("lien Google Play sans identifiant de l'app (…/details?id=com.exemple.app)")
        row = conn.execute("SELECT * FROM app_sources WHERE app_id=? AND kind=? AND url=?", (app_id, kind, url)).fetchone()
        if row is not None:
            return source_dict(row), False
        cur = conn.execute(
            "INSERT INTO app_sources(app_id, kind, url, title, status, created_at) VALUES (?,?,?,?,'pending',?)",
            (app_id, kind, url, (title or "").strip()[:200] or None, iso(now)))
        sid = cur.lastrowid
        jobs.enqueue(conn, "apps.ingest_source", {"source_id": sid}, key=f"apps.ingest_source:{sid}",
                     app_id=app_id, parent_id=parent_id, clock=lambda: now)
        return get_source(conn, app_id, sid), True


def sync_url_sources(conn: sqlite3.Connection, app: dict, *, now: datetime, parent_id: int | None = None) -> list[int]:
    """Chaque lien de l'app (App Store, Google Play, site) a sa source. Renvoie les sources créées."""
    created = []
    for field, kind in URL_FIELDS:
        if app.get(field):
            src, new = add_source(conn, app["id"], kind=kind, url=app[field], now=now, parent_id=parent_id)
            if new:
                created.append(src["id"])
    return created


def refresh_source(conn: sqlite3.Connection, app_id: str, source_id: int, *, now: datetime) -> int:
    """Relit une source (nouvelle version sur l'App Store, site modifié). Renvoie l'id de la tâche ;
    une lecture déjà en attente est réutilisée."""
    with tx(conn):
        src = get_source(conn, app_id, source_id)
        if src["kind"] == "text":
            raise Conflict("un texte collé n'a rien à relire")
        keys = conn.execute("SELECT id, status FROM jobs WHERE key=? OR key LIKE ?",
                            (f"apps.ingest_source:{source_id}", f"apps.ingest_source:{source_id}:%")).fetchall()
        waiting = next((r["id"] for r in keys if r["status"] in ("queued", "running")), None)
        if waiting is not None:
            return waiting
        conn.execute("UPDATE app_sources SET status='pending', error=NULL WHERE id=?", (source_id,))
        return jobs.enqueue(conn, "apps.ingest_source", {"source_id": source_id},
                            key=f"apps.ingest_source:{source_id}:{len(keys) + 1}", app_id=app_id,
                            clock=lambda: now)


def delete_source(conn: sqlite3.Connection, app_id: str, source_id: int, *, now: datetime) -> None:
    """Retire une source ; si c'était un lien de l'app, le lien est retiré aussi (sinon il reviendrait)."""
    with tx(conn):
        src = get_source(conn, app_id, source_id)
        conn.execute("DELETE FROM app_sources WHERE id=?", (source_id,))
        # Sa lecture encore en attente n'a plus d'objet : sinon l'analyse attendrait une source disparue.
        conn.execute("""UPDATE jobs SET status='cancelled', updated_at=?, finished_at=?
                        WHERE kind='apps.ingest_source' AND status='queued' AND (key=? OR key LIKE ?)""",
                     (iso(now), iso(now), f"apps.ingest_source:{source_id}", f"apps.ingest_source:{source_id}:%"))
        for field, kind in URL_FIELDS:
            if src["kind"] == kind and src.get("url"):
                conn.execute(f"UPDATE apps SET {field}=NULL, updated_at=? WHERE id=? AND {field}=?",
                             (iso(now), app_id, src["url"]))


def source_ok(conn: sqlite3.Connection, source_id: int, *, now: datetime, title: str, content: str, meta: dict) -> None:
    conn.execute("UPDATE app_sources SET status='ok', title=?, content=?, meta=?, error=NULL, fetched_at=? WHERE id=?",
                 (title[:200] or None, content, dumps(meta), iso(now), source_id))


def source_failed(conn: sqlite3.Connection, source_id: int, error: str, *, final: bool) -> None:
    """L'erreur est visible tout de suite ; la source ne passe en « error » qu'au dernier essai."""
    conn.execute("UPDATE app_sources SET status=?, error=? WHERE id=?",
                 ("error" if final else "pending", error[:1000], source_id))


# --- Questions --------------------------------------------------------------------------------------------------

def question_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["options"] = loads(d.get("options"), [])
    return d


def list_questions(conn: sqlite3.Connection, app_id: str, status: str | None = None) -> list[dict]:
    get_app(conn, app_id)
    sql, args = "SELECT * FROM app_questions WHERE app_id=?", [app_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY round, priority='utile', id"
    return [question_dict(r) for r in conn.execute(sql, args)]


def insert_questions(conn: sqlite3.Connection, app_id: str, questions: list[Question], *, round_no: int,
                     brief_id: int, now: datetime) -> int:
    for q in questions:
        conn.execute(
            """INSERT INTO app_questions(app_id, round, question, why, kind, options, priority, status, created_at, brief_id)
               VALUES (?,?,?,?,?,?,?,'open',?,?)""",
            (app_id, round_no, q.question, q.why, q.kind, dumps(q.options), q.priority, iso(now), brief_id))
    return len(questions)


def answer_questions(conn: sqlite3.Connection, app_id: str, *, now: datetime, answers: dict[int, str] | None = None,
                     skip: list[int] | None = None, skip_rest: bool = False) -> dict:
    """Enregistre des réponses (ou des questions passées). Quand plus aucune question n'est ouverte, la
    fiche est affinée avec les réponses du tour (tâche apps.refine) ; si tout a été passé, elle est prête."""
    answers = {int(k): v for k, v in (answers or {}).items()}
    skip = [int(q) for q in (skip or [])]
    with tx(conn):
        app = get_app(conn, app_id)
        open_ids = {r["id"] for r in conn.execute("SELECT id FROM app_questions WHERE app_id=? AND status='open'",
                                                  (app_id,))}
        for qid in [*answers, *skip]:
            if qid not in open_ids:
                row = conn.execute("SELECT status FROM app_questions WHERE id=? AND app_id=?", (qid, app_id)).fetchone()
                if row is None:
                    raise NotFound(f"question {qid} inconnue pour cette app")
                raise Conflict(f"la question {qid} est déjà {_STATUS_FR.get(row['status'], row['status'])}")
        for qid, text in answers.items():
            text = text if isinstance(text, str) else ", ".join(str(t) for t in text or [])
            text = text.strip()
            if not text:
                raise AppError(f"réponse vide pour la question {qid} (la passer si on ne sait pas)")
            conn.execute("UPDATE app_questions SET status='answered', answer=?, answered_at=? WHERE id=?",
                         (text[:4000], iso(now), qid))
        for qid in skip:
            conn.execute("UPDATE app_questions SET status='skipped', answered_at=? WHERE id=?", (iso(now), qid))
        if skip_rest:
            conn.execute("UPDATE app_questions SET status='skipped', answered_at=? WHERE app_id=? AND status='open'",
                         (iso(now), app_id))
        refine_job = _close_round(conn, app, now=now)
    return {"answered": len(answers), "skipped": len(skip), "refine_job": refine_job,
            "status": get_app(conn, app_id)["status"]}


def _close_round(conn: sqlite3.Connection, app: dict, *, now: datetime) -> int | None:
    if conn.execute("SELECT 1 FROM app_questions WHERE app_id=? AND status='open' LIMIT 1", (app["id"],)).fetchone():
        return None
    last = conn.execute("SELECT brief_id FROM app_questions WHERE app_id=? AND brief_id IS NOT NULL ORDER BY id DESC "
                        "LIMIT 1", (app["id"],)).fetchone()
    if last is None:
        return None
    answered = conn.execute("SELECT COUNT(*) FROM app_questions WHERE brief_id=? AND status='answered'",
                            (last["brief_id"],)).fetchone()[0]
    if not answered:
        set_status(conn, app["id"], understanding_status(conn, app["id"]), now=now)
        return None
    job_id = jobs.enqueue(conn, "apps.refine", {"app_id": app["id"], "brief_id": last["brief_id"]},
                          key=f"apps.refine:{app['id']}:{last['brief_id']}", app_id=app["id"], clock=lambda: now)
    set_status(conn, app["id"], "analyzing", now=now)
    return job_id


# --- Fiches produit (versions) ----------------------------------------------------------------------------------

def brief_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["brief"] = loads(d.get("brief"), {})
    return d


def latest_brief(conn: sqlite3.Connection, app_id: str, *, approved: bool = False) -> dict | None:
    sql = "SELECT * FROM app_briefs WHERE app_id=?" + (" AND approved_at IS NOT NULL" if approved else "")
    r = conn.execute(sql + " ORDER BY version DESC LIMIT 1", (app_id,)).fetchone()
    return brief_dict(r) if r else None


def list_briefs(conn: sqlite3.Connection, app_id: str) -> list[dict]:
    get_app(conn, app_id)
    return [brief_dict(r) for r in conn.execute("SELECT * FROM app_briefs WHERE app_id=? ORDER BY version DESC",
                                                (app_id,))]


def get_brief(conn: sqlite3.Connection, app_id: str, version: int) -> dict:
    r = conn.execute("SELECT * FROM app_briefs WHERE app_id=? AND version=?", (app_id, version)).fetchone()
    if r is None:
        raise NotFound(f"pas de version {version} de la fiche")
    return brief_dict(r)


def next_version(conn: sqlite3.Connection, app_id: str) -> int:
    return conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM app_briefs WHERE app_id=?", (app_id,)).fetchone()[0]


def insert_brief(conn: sqlite3.Connection, app_id: str, brief: ProductBrief, *, now: datetime, origin: str,
                 model: str | None = None, job_id: int | None = None) -> dict:
    """Nouvelle version. À appeler dans une transaction : le numéro est calculé sous verrou."""
    cur = conn.execute(
        "INSERT INTO app_briefs(app_id, version, brief, model, created_at, origin, job_id) VALUES (?,?,?,?,?,?,?)",
        (app_id, next_version(conn, app_id), brief.model_dump_json(), model, iso(now), origin, job_id))
    return brief_dict(conn.execute("SELECT * FROM app_briefs WHERE id=?", (cur.lastrowid,)).fetchone())


def save_brief(conn: sqlite3.Connection, app_id: str, brief: ProductBrief, *, now: datetime) -> dict:
    """Édition à la main : une nouvelle version, à approuver comme les autres."""
    with tx(conn):
        app = get_app(conn, app_id)
        row = insert_brief(conn, app_id, brief, now=now, origin="edit")
        set_status(conn, app_id, understanding_status(conn, app_id), now=now)
        event(conn, now, "apps.brief_edited", f"{app['name']} : fiche v{row['version']} modifiée à la main")
    return row


def approve_brief(conn: sqlite3.Connection, app_id: str, *, now: datetime, version: int | None = None) -> dict:
    """Un humain approuve la dernière version : statut brief_ready, questions encore ouvertes passées,
    et la stratégie est demandée (strategy.generate, traitée par le module strategy)."""
    with tx(conn):
        app = get_app(conn, app_id)
        latest = latest_brief(conn, app_id)
        if latest is None:
            raise Conflict("aucune fiche à approuver : lancer d'abord l'analyse")
        if version is not None and version != latest["version"]:
            raise Conflict(f"seule la dernière version (v{latest['version']}) peut être approuvée")
        if not latest["approved_at"]:
            latest["approved_at"] = iso(now)
            conn.execute("UPDATE app_briefs SET approved_at=? WHERE id=?", (latest["approved_at"], latest["id"]))
            event(conn, now, "apps.brief_approved",
                  f"{app['name']} : fiche v{latest['version']} approuvée, stratégie demandée")
        conn.execute("UPDATE app_questions SET status='skipped', answered_at=? WHERE app_id=? AND status='open'",
                     (iso(now), app_id))
        set_status(conn, app_id, "brief_ready", now=now)
        job_id = jobs.enqueue(conn, "strategy.generate", {"app_id": app_id, "brief_id": latest["id"]},
                              key=f"strategy.generate:{app_id}:{latest['id']}", app_id=app_id, clock=lambda: now)
    return {"brief": latest, "strategy_job": job_id}
