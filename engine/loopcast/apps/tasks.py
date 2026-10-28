"""Les tâches du module apps (file de tâches durable, jobs.py).

    apps.ingest_source   {source_id}           clé apps.ingest_source:<source_id>[:<n>]   lit une source
    apps.describe_asset  {asset_id[, force]}   clé apps.describe_asset:<asset_id>[:<n>]   Claude regarde un fichier
    apps.analyze         {app_id}              clé apps.analyze:<app_id>:<version visée>  fiche + questions
    apps.refine          {app_id, brief_id}    clé apps.refine:<app_id>:<brief_id>        fiche + réponses du tour

Idempotentes : rejouées après un plantage, elles ne refont pas ce qui est fait (une fiche porte l'id
de la tâche qui l'a produite, une capture décrite ne l'est pas deux fois, un fichier importé deux fois
n'est gardé qu'une fois). Claude n'est appelé que via ctx.service("llm"), après costs.check_budget, et
chaque appel est inscrit au registre des coûts.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import httpx

from loopcast import costs, jobs
from loopcast import llm as llm_mod
from loopcast.apps import assets, prompts, sources, store
from loopcast.apps.settings import apps_settings
from loopcast.apps.sources import FetchError
from loopcast.schemas import AnalysisResult, AssetAnalysis, ProductBrief, Question

log = logging.getLogger(__name__)

# Coût estimé d'un appel, pour le contrôle de budget avant l'appel (le coût réel est inscrit après).
ESTIMATE_USD = {"asset.describe": 0.03, "app.analyze": 0.60, "app.refine": 0.40}
MAX_QUESTIONS = 8            # questions de l'analyse
MAX_REFINE_QUESTIONS = 3     # nouvelles questions d'un affinage (bloquantes seulement)
VIDEO_FRAMES = 4             # images extraites d'une vidéo de démo pour la décrire
MAX_PDFS, MAX_PDF_BYTES = 2, 8_000_000
MAX_IMAGE_BYTES = 20_000_000


# --- Outils communs ------------------------------------------------------------------------------------

def _app(ctx: jobs.JobContext, app_id: str) -> dict:
    try:
        return store.get_app(ctx.conn, app_id)
    except store.AppError as e:
        raise jobs.Permanent(str(e)) from e


@contextmanager
def _http(ctx: jobs.JobContext) -> Iterator[httpx.Client]:
    """Le client HTTP injecté (service « http », tests : httpx.MockTransport), sinon un client neuf."""
    injected = ctx.services.get("http")
    if injected is not None:
        yield injected
        return
    with sources.new_client(apps_settings(ctx.config).fetch_timeout_s) as client:
        yield client


def _ask(ctx: jobs.JobContext, *, task: str, content: list[dict], schema: type, app_id: str,
         ref: str) -> llm_mod.LLMResult:
    """Un appel à Claude : budget vérifié avant, coût inscrit après (même si la suite échoue)."""
    llm = ctx.service("llm")
    now = ctx.clock()
    if getattr(llm, "name", "") != "demo":
        check = costs.check_budget(ctx.conn, getattr(ctx.config, "settings", None) or {}, now,
                                   ESTIMATE_USD[task], app_id)
        if not check.ok:
            retry_at = check.retry_at or now + timedelta(hours=1)
            reason = f"budget : {check.reason}"
            raise jobs.RetryLater(max(60.0, (retry_at - now).total_seconds()), reason, result={"waiting": reason})
    try:
        res = llm.structured(task=task, system=prompts.system_prompt(task), content=content, schema=schema)
    except llm_mod.LLMUnavailable as e:
        raise jobs.Permanent(str(e)) from e
    except llm_mod.LLMRefusal as e:
        raise jobs.Permanent(f"{e} : vérifier ce qui a été envoyé (description, captures, documents)") from e
    llm_mod.record_cost(ctx.conn, res, at=ctx.clock(), task=task, app_id=app_id, job_id=ctx.job.id, ref=ref)
    return res


def _as(data: Any, model: type) -> Any:
    if isinstance(data, model):
        return data
    return model.model_validate(data if isinstance(data, dict) else data.model_dump())


# --- apps.ingest_source -------------------------------------------------------------------------------------

@jobs.handler("apps.ingest_source", max_attempts=4, backoff_s=(60, 300, 1800))
def ingest_source(ctx: jobs.JobContext, payload: dict) -> dict:
    sid = int(payload["source_id"])
    row = ctx.conn.execute("SELECT * FROM app_sources WHERE id=?", (sid,)).fetchone()
    if row is None:
        return {"skipped": "source supprimée"}
    src = store.source_dict(row)
    if src["kind"] == "text":
        return {"skipped": "texte collé : rien à lire"}
    app = _app(ctx, src["app_id"])
    s = apps_settings(ctx.config)
    lang = app["langs"][0]
    try:
        with _http(ctx) as client:
            if src["kind"] == "appstore":
                fetched = _ingest_appstore(ctx, app, src, client)
            elif src["kind"] == "playstore":
                fetched = sources.fetch_playstore(client, src["url"], lang=lang, max_bytes=s.max_page_bytes,
                                                  max_chars=s.max_source_chars)
            else:
                fetched = sources.fetch_website(client, src["url"], lang=lang, max_bytes=s.max_page_bytes,
                                                max_chars=s.max_source_chars)
    except FetchError as e:
        final = e.permanent or ctx.job.attempts >= ctx.job.max_attempts
        store.source_failed(ctx.conn, sid, str(e), final=final)
        if final:
            store.event(ctx.conn, ctx.clock(), "apps.source_error", f"{app['name']} : {e}")
        if e.permanent:
            raise jobs.Permanent(str(e)) from e
        raise
    store.source_ok(ctx.conn, sid, now=ctx.clock(), title=fetched.title, content=fetched.content, meta=fetched.meta)
    if src["kind"] == "website":
        _follow_store_links(ctx, app, fetched.meta.get("store_links") or {})
    return {"source_id": sid, "kind": src["kind"], "chars": len(fetched.content),
            "imported": fetched.meta.get("imported")}


def _ingest_appstore(ctx: jobs.JobContext, app: dict, src: dict, client: httpx.Client) -> sources.Fetched:
    track_id = sources.appstore_id(src["url"])
    if not track_id:
        raise FetchError("lien App Store sans identifiant de l'app (…/id123456789)", permanent=True)
    countries = sources.appstore_countries(src["url"], app["langs"])
    records = {}
    for country in countries:
        record = sources.appstore_lookup(client, track_id, country)
        if record:
            records[country] = record
    if not records:
        raise FetchError(f"App Store : app {track_id} introuvable (vitrines : {', '.join(countries)})", permanent=True)
    fetched = sources.appstore_source(records, max_chars=apps_settings(ctx.config).max_source_chars, now=ctx.clock())
    fetched.meta["imported"] = _import_store_media(ctx, app, src, records, client)
    return fetched


def _import_store_media(ctx: jobs.JobContext, app: dict, src: dict, records: dict[str, dict],
                        client: httpx.Client) -> dict:
    """Les captures de la fiche deviennent des assets si l'équipe n'en a fourni aucune (à la première
    lecture seulement), l'icône devient le logo s'il n'y en a pas. Une image ratée n'arrête rien."""
    conn = ctx.conn
    done = {"screenshots": 0, "failed": 0, "icon": None}
    team_shots = conn.execute(
        "SELECT COUNT(*) FROM app_assets WHERE app_id=? AND kind='screenshot' AND COALESCE(origin,'upload')!='appstore'",
        (app["id"],)).fetchone()[0]
    if not team_shots and "imported" not in (src.get("meta") or {}):
        limit = apps_settings(ctx.config).appstore_screenshots
        seen: set[str] = set()
        for country, record in records.items():
            for n, url in enumerate((record.get("screenshotUrls") or [])[:limit], 1):
                if url in seen:
                    continue
                seen.add(url)
                got = _import_image(ctx, app, client, url, f"appstore-{country}-{n}.png", kind="screenshot",
                                    caption=f"Capture App Store {country.upper()} n°{n}")
                if got is None:
                    done["failed"] += 1
                elif got[1]:
                    done["screenshots"] += 1
    has_logo = conn.execute("SELECT 1 FROM app_assets WHERE app_id=? AND kind='logo' LIMIT 1", (app["id"],)).fetchone()
    first = next(iter(records.values()))
    icon = first.get("artworkUrl512") or first.get("artworkUrl100")
    if not has_logo and icon:
        got = _import_image(ctx, app, client, icon, "appstore-icon.png", kind="logo", caption="Icône App Store")
        done["icon"] = got[0]["id"] if got else None
    return done


def _import_image(ctx: jobs.JobContext, app: dict, client: httpx.Client, url: str, filename: str, *, kind: str,
                  caption: str) -> tuple[dict, bool] | None:
    try:
        data = sources.download(client, sources.full_size(url), max_bytes=MAX_IMAGE_BYTES)
        return assets.store_asset(ctx.conn, ctx.config, app["id"], io.BytesIO(data), filename, now=ctx.clock(),
                                  kind=kind, caption=caption, origin="appstore", source_url=url, parent_id=ctx.job.id)
    except (FetchError, store.AppError) as e:
        log.warning("%s : image App Store non importée (%s) : %s", app["id"], url, e)
        return None


def _follow_store_links(ctx: jobs.JobContext, app: dict, links: dict[str, list[str]]) -> None:
    """Un site qui renvoie vers une seule fiche App Store (ou Google Play) : la fiche est lue aussi."""
    changes = {}
    for field, kind, parse in (("store_url_ios", "appstore", sources.appstore_id),
                               ("store_url_android", "playstore", sources.playstore_id)):
        urls = [u for u in links.get(kind) or [] if parse(u)]
        if not app.get(field) and len({parse(u) for u in urls}) == 1:
            changes[field] = urls[0]
    if changes:
        try:
            store.update_app(ctx.conn, app["id"], changes, now=ctx.clock())
        except store.AppError as e:     # le site est lu ; le lien trouvé ne sert simplement pas
            log.warning("%s : lien de store trouvé sur le site ignoré : %s", app["id"], e)


# --- apps.describe_asset ---------------------------------------------------------------------------------------

@jobs.handler("apps.describe_asset", max_attempts=3)
def describe_asset(ctx: jobs.JobContext, payload: dict) -> dict:
    asset_id = int(payload["asset_id"])
    row = ctx.conn.execute("SELECT * FROM app_assets WHERE id=?", (asset_id,)).fetchone()
    if row is None:
        return {"skipped": "fichier supprimé"}
    asset = assets.asset_dict(row)
    if asset["analysis"] and not payload.get("force"):
        return {"skipped": "déjà décrit"}
    if not assets.describable(asset["kind"], asset["mime"]):
        return {"skipped": "ni capture ni vidéo de démo"}
    app = _app(ctx, asset["app_id"])
    try:
        path = assets.safe_path(ctx.config, app["id"], asset["path"])
        if not path.exists():
            raise jobs.Permanent(f"fichier introuvable sur le disque : data/apps/{app['id']}/{asset['path']}")
        with tempfile.TemporaryDirectory(prefix="loopcast-frames-") as tmp:
            frame_times = None
            if (asset["mime"] or "").startswith("video/"):
                frames = assets.video_frames(ctx.config, path, asset.get("duration_s"), VIDEO_FRAMES, Path(tmp))
                if not frames:
                    raise jobs.Permanent("aucune image n'a pu être extraite de la vidéo (fichier illisible ?)")
                images = [llm_mod.image_block(p) for _t, p in frames]
                frame_times = [t for t, _p in frames]
            else:
                images = [llm_mod.image_block(path)]
    except store.AppError as e:
        raise jobs.Permanent(str(e)) from e
    except OSError as e:
        raise jobs.Permanent(f"image illisible : {e}") from e
    content = prompts.describe_content(app, asset, images, frame_times)
    res = _ask(ctx, task="asset.describe", content=content, schema=AssetAnalysis, app_id=app["id"],
               ref=f"asset:{asset_id}")
    analysis = _as(res.data, AssetAnalysis)
    ctx.conn.execute("UPDATE app_assets SET analysis=? WHERE id=?", (analysis.model_dump_json(), asset_id))
    return {"asset_id": asset_id, "screen": analysis.screen, "cost_usd": res.cost_usd}


# --- apps.analyze et apps.refine --------------------------------------------------------------------------------

@jobs.handler("apps.analyze", max_attempts=3, lease_s=900)
def analyze(ctx: jobs.JobContext, payload: dict) -> dict:
    app_id = payload["app_id"]
    done = _already_done(ctx)
    if done:
        return done
    app = _app(ctx, app_id)
    try:
        _wait_for_inputs(ctx, app_id)
        m = _material(ctx, app)
        if not ((app.get("description") or "").strip() or m.sources or any(a["kind"] != "logo" for a in m.assets)):
            raise jobs.Permanent("rien à analyser : ajoutez une description, un lien (App Store, site) ou des captures")
        s = apps_settings(ctx.config)
        content = prompts.analysis_content(m, images=_pick_images(ctx, m.assets, s.analysis_images),
                                           documents=_documents(ctx, m.assets, s.max_source_chars),
                                           max_source_chars=s.max_source_chars, max_questions=MAX_QUESTIONS)
        res = _ask(ctx, task="app.analyze", content=content, schema=AnalysisResult, app_id=app_id, ref=f"app:{app_id}")
    except Exception as e:
        _failed(ctx, app, e)
        raise
    result = _as(res.data, AnalysisResult)
    brief = _clean_brief(result.brief, app, m.asset_ids)
    # Les questions restées ouvertes sont remplacées par celles-ci : seules celles déjà traitées sont écartées.
    closed = [q for q in m.questions if q["status"] != "open"]
    questions = _clean_questions(result.questions, asked=closed, limit=MAX_QUESTIONS, blocking_only=False)
    now = ctx.clock()
    with store.tx(ctx.conn):
        row = store.insert_brief(ctx.conn, app_id, brief, now=now, origin="analyze", model=res.model, job_id=ctx.job.id)
        # Une nouvelle analyse remplace les questions restées sans réponse.
        ctx.conn.execute("UPDATE app_questions SET status='skipped', answered_at=? WHERE app_id=? AND status='open'",
                         (jobs.iso(now), app_id))
        store.insert_questions(ctx.conn, app_id, questions, round_no=1, brief_id=row["id"], now=now)
        store.set_status(ctx.conn, app_id, store.understanding_status(ctx.conn, app_id, exclude_job=ctx.job.id), now=now)
        store.event(ctx.conn, now, "apps.analyzed", f"{app['name']} : fiche v{row['version']} prête"
                    + (f", {len(questions)} question(s) pour l'équipe" if questions else ""))
    return {"brief_version": row["version"], "questions": len(questions), "model": res.model, "cost_usd": res.cost_usd}


@jobs.handler("apps.refine", max_attempts=3, lease_s=900)
def refine(ctx: jobs.JobContext, payload: dict) -> dict:
    app_id, brief_id = payload["app_id"], int(payload["brief_id"])
    done = _already_done(ctx)
    if done:
        return done
    app = _app(ctx, app_id)
    try:
        m = _material(ctx, app)
        if m.brief is None:
            raise jobs.Permanent("aucune fiche à affiner : lancer d'abord l'analyse")
        round_questions = [q for q in m.questions if q.get("brief_id") == brief_id]
        if not any(q["status"] == "answered" for q in round_questions):
            raise jobs.Permanent("aucune réponse à intégrer pour ce tour de questions")
        s = apps_settings(ctx.config)
        round_no = max(q["round"] for q in round_questions)
        max_new = MAX_REFINE_QUESTIONS if round_no < s.max_question_rounds else 0
        content = prompts.refine_content(m, base=m.brief, round_questions=round_questions, round_no=round_no,
                                         max_rounds=s.max_question_rounds, max_new=max_new,
                                         max_source_chars=s.max_source_chars)
        res = _ask(ctx, task="app.refine", content=content, schema=AnalysisResult, app_id=app_id, ref=f"app:{app_id}")
    except Exception as e:
        _failed(ctx, app, e)
        raise
    result = _as(res.data, AnalysisResult)
    brief = _clean_brief(result.brief, app, m.asset_ids)
    questions = (_clean_questions(result.questions, asked=m.questions, limit=max_new, blocking_only=True)
                 if max_new else [])
    now = ctx.clock()
    with store.tx(ctx.conn):
        row = store.insert_brief(ctx.conn, app_id, brief, now=now, origin="refine", model=res.model, job_id=ctx.job.id)
        store.insert_questions(ctx.conn, app_id, questions, round_no=round_no + 1, brief_id=row["id"], now=now)
        store.set_status(ctx.conn, app_id, store.understanding_status(ctx.conn, app_id, exclude_job=ctx.job.id), now=now)
        store.event(ctx.conn, now, "apps.refined", f"{app['name']} : fiche v{row['version']} affinée avec les réponses"
                    + (f", {len(questions)} question(s) bloquante(s) restante(s)" if questions else ""))
    return {"brief_version": row["version"], "questions": len(questions), "round": round_no, "model": res.model,
            "cost_usd": res.cost_usd}


def _already_done(ctx: jobs.JobContext) -> dict | None:
    """Tâche rejouée après un plantage survenu après l'écriture de la fiche : rien à refaire."""
    row = ctx.conn.execute("SELECT version FROM app_briefs WHERE job_id=?", (ctx.job.id,)).fetchone()
    return {"brief_version": row["version"], "already_done": True} if row else None


def _failed(ctx: jobs.JobContext, app: dict, error: Exception) -> None:
    """Échec définitif (Permanent ou dernier essai) : le statut quitte « analyzing », l'échec est journalisé."""
    if isinstance(error, jobs.RetryLater):
        return
    if not isinstance(error, jobs.Permanent) and ctx.job.attempts < ctx.job.max_attempts:
        return
    conn, now = ctx.conn, ctx.clock()
    if conn.in_transaction:
        conn.execute("ROLLBACK")
    store.set_status(conn, app["id"], store.understanding_status(conn, app["id"], exclude_job=ctx.job.id), now=now)
    what = "analyse" if ctx.job.kind == "apps.analyze" else "affinage de la fiche"
    store.event(conn, now, "apps.analysis_failed", f"{app['name']} : {what} en échec : {error}")


def _wait_for_inputs(ctx: jobs.JobContext, app_id: str) -> None:
    """L'analyse attend que les sources soient lues et les fichiers décrits, au plus
    `apps.wait_inputs_minutes` depuis sa création (ensuite elle part avec ce qu'elle a)."""
    rows = ctx.conn.execute(
        """SELECT kind, COUNT(*) n FROM jobs WHERE app_id=? AND kind IN ('apps.ingest_source','apps.describe_asset')
           AND status IN ('queued','running') AND id != ? GROUP BY kind""", (app_id, ctx.job.id)).fetchall()
    pending = {r["kind"]: r["n"] for r in rows}
    if not pending:
        return
    created = ctx.conn.execute("SELECT created_at FROM jobs WHERE id=?", (ctx.job.id,)).fetchone()["created_at"]
    if ctx.clock() - datetime.fromisoformat(created) > timedelta(minutes=apps_settings(ctx.config).wait_inputs_minutes):
        log.warning("%s : analyse lancée sans attendre %s", app_id, pending)
        return
    waiting = []
    if pending.get("apps.ingest_source"):
        waiting.append(f"{pending['apps.ingest_source']} source(s) à lire")
    if pending.get("apps.describe_asset"):
        waiting.append(f"{pending['apps.describe_asset']} fichier(s) à décrire")
    reason = "en attente : " + " et ".join(waiting)
    raise jobs.RetryLater(15, reason, result={"waiting": reason})       # visible dans /api/jobs


def _material(ctx: jobs.JobContext, app: dict) -> prompts.Material:
    conn, app_id = ctx.conn, app["id"]
    return prompts.Material(
        app=app,
        sources=[store.source_dict(r) for r in conn.execute(
            "SELECT * FROM app_sources WHERE app_id=? AND COALESCE(content, '') != '' ORDER BY id", (app_id,))],
        assets=[assets.asset_dict(r) for r in conn.execute(
            "SELECT * FROM app_assets WHERE app_id=? ORDER BY kind='logo', id", (app_id,))],
        questions=[store.question_dict(r) for r in conn.execute(
            "SELECT * FROM app_questions WHERE app_id=? ORDER BY id", (app_id,))],
        brief=store.latest_brief(conn, app_id),
    )


def _pick_images(ctx: jobs.JobContext, files: list[dict], limit: int) -> list[tuple[dict, dict]]:
    """Les captures montrées à Claude : celles de l'équipe avant les visuels App Store, les montrables
    d'abord, un écran différent à chaque fois ; on complète ensuite jusqu'à `limit`."""
    shots = [a for a in files if a["kind"] in ("screenshot", "other") and (a["mime"] or "").startswith("image/")]
    shots.sort(key=lambda a: ((a.get("origin") or "upload") == "appstore",
                              not (a.get("analysis") or {}).get("usable_in_video", True), a["id"]))
    chosen: list[dict] = []
    screens: set[str] = set()
    for a in shots:
        screen = ((a.get("analysis") or {}).get("screen") or "").strip().lower()
        if screen and screen in screens:
            continue
        screens.add(screen)
        chosen.append(a)
    chosen += [a for a in shots if a not in chosen]
    out = []
    for a in chosen[:limit]:
        try:
            out.append((a, llm_mod.image_block(assets.safe_path(ctx.config, a["app_id"], a["path"]))))
        except (OSError, store.AppError) as e:
            log.warning("capture #%s non montrée à Claude : %s", a["id"], e)
    return out


def _documents(ctx: jobs.JobContext, files: list[dict], max_chars: int) -> list[tuple[dict, dict | str]]:
    """Documents de l'équipe : texte lu tel quel (borné), PDF transmis à Claude (2 au plus, 8 Mo chacun)."""
    out: list[tuple[dict, dict | str]] = []
    pdfs = 0
    for a in files:
        if a["kind"] != "document":
            continue
        try:
            path = assets.safe_path(ctx.config, a["app_id"], a["path"])
            if a["mime"] in assets.TEXT_MIMES:
                out.append((a, prompts.cut(path.read_text(errors="replace"), max_chars)))
            elif a["mime"] == "application/pdf" and pdfs < MAX_PDFS and (a["bytes"] or 0) <= MAX_PDF_BYTES:
                data = base64.standard_b64encode(path.read_bytes()).decode()
                out.append((a, {"type": "document", "title": a["filename"] or f"document {a['id']}",
                                "source": {"type": "base64", "media_type": "application/pdf", "data": data}}))
                pdfs += 1
        except (OSError, store.AppError) as e:
            log.warning("document #%s non transmis : %s", a["id"], e)
    return out


# --- Garde-fous sur les réponses de Claude ----------------------------------------------------------------------

def _clean_brief(brief: ProductBrief, app: dict, asset_ids: list[int]) -> ProductBrief:
    """Ids de fichiers existants seulement, rien pour un marché non visé, confiance entre 0 et 1."""
    valid = set(asset_ids)
    for feature in brief.features:
        feature.asset_ids = [i for i in feature.asset_ids if i in valid]
    langs = app["langs"]
    for localized in (brief.one_liner, brief.cta, brief.keywords):
        for lang in ("fr", "en"):
            if lang not in langs:
                setattr(localized, lang, "")
    for persona in brief.personas:
        persona.langs = [lang for lang in persona.langs if lang in langs] or list(langs)
    brief.confidence = min(1.0, max(0.0, brief.confidence))
    return brief


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _clean_questions(questions: list[Question], *, asked: list[dict], limit: int, blocking_only: bool) -> list[Question]:
    """Bloquantes d'abord, pas de doublon ni de question déjà posée, au plus `limit`."""
    seen = {_norm(q["question"]) for q in asked}
    out: list[Question] = []
    for q in sorted(questions, key=lambda q: q.priority != "bloquante"):
        key = _norm(q.question)
        if not key or key in seen or (blocking_only and q.priority != "bloquante"):
            continue
        if q.kind == "text" or len(q.options) < 2:       # un choix sans options est une question libre
            q.kind, q.options = "text", []
        seen.add(key)
        out.append(q)
    return out[:limit]
