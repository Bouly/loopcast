"""Tâches du module production (file de tâches : jobs.py).

    content.produce  {idea_id[, run, regenerate]}   enfilée par le module strategy
    content.render   {content_id, run}              format Remotion à props
    content.compose  {content_id, run, clips}       format à plans (composition `story`)
    content.qa       {content_id, run}              contrôle qualité

Chaque production porte un numéro (`content.run`) : une relance l'incrémente, et une tâche d'une
production précédente se reconnaît et s'arrête sans rien toucher. Toutes les tâches sont idempotentes.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from loopcast import formats, jobs
from loopcast.jobs import JobContext, Permanent, RetryLater, iso
from loopcast.production import assets, formats_extra, options, plan, qa, renderer, store
from loopcast.production.formats_extra import AI_KINDS
from loopcast.production.store import loads, tx
from loopcast.schemas import Idea

BUSY_RETRY_S = 20                 # un autre rendu occupe la machine : on repasse dans 20 s


class RenderFailed(RuntimeError):
    """Le moteur a échoué : la file réessaie (backoff), puis le contenu passe en échec."""


# --- Outils communs ----------------------------------------------------------------------------------------

@contextmanager
def _failing(ctx: JobContext, content: sqlite3.Row) -> Iterator[None]:
    """Une erreur définitive (ou le dernier essai raté) fait passer le contenu et son idée en échec."""
    try:
        yield
    except RetryLater:
        raise
    except Permanent as e:
        store.fail_content(ctx.conn, content, ctx.clock(), str(e))
        raise
    except Exception as e:
        if ctx.job.attempts >= ctx.job.max_attempts:
            store.fail_content(ctx.conn, content, ctx.clock(), f"{e} (abandon après {ctx.job.attempts} essais)")
        else:
            store.set_content(ctx.conn, content["id"], ctx.clock(),
                              error=f"essai {ctx.job.attempts}/{ctx.job.max_attempts} raté, nouvel essai prévu : {e}")
        raise


def _current(ctx: JobContext, payload: dict) -> sqlite3.Row | None:
    """Le contenu visé, s'il est toujours dans la production que sert cette tâche (sinon None)."""
    content = store.get_content(ctx.conn, str(payload.get("content_id") or ""))
    if content is None or (content["run"] or 0) != int(payload.get("run") or 0):
        return None
    return content


def _own_result(ctx: JobContext) -> dict:
    row = ctx.conn.execute("SELECT result FROM jobs WHERE id=?", (ctx.job.id,)).fetchone()
    return loads(row["result"] if row else None, {}) or {}


def _skip(reason: str) -> dict:
    return {"skipped": reason}


# --- content.produce ---------------------------------------------------------------------------------------

@jobs.handler("content.produce", max_attempts=3, lease_s=300)
def produce(ctx: JobContext, payload: dict) -> dict:
    conn, now = ctx.conn, ctx.clock()
    idea_id = str(payload.get("idea_id") or "")
    idea_row = store.get_idea(conn, idea_id)
    if idea_row is None:
        raise Permanent(f"idée introuvable : {idea_id or '(payload sans idea_id)'}")
    content = store.get_content(conn, idea_id)
    run, reason = _resolve_run(ctx, payload, content)
    if run is None:
        return _skip(reason)
    if content is None or (content["run"] or 0) != run or content["status"] in store.FAILED:
        _start_run(conn, now, idea_row, run, content)
    content = store.get_content(conn, idea_id)
    if content["status"] != "draft":
        return _skip(f"production {run} déjà au statut {content['status']}")
    with _failing(ctx, content):
        idea = _parse_idea(idea_row)
        spec = _spec(idea_row["format"])
        if formats_extra.uses_shots(spec):
            return _produce_shots(ctx, content, idea_row, idea, spec, run, payload)
        return _produce_remotion(ctx, content, idea_row, idea, spec, run)


def _resolve_run(ctx: JobContext, payload: dict, content: sqlite3.Row | None) -> tuple[int | None, str]:
    """Le numéro de production que sert cette tâche, ou (None, pourquoi elle n'a plus rien à faire)."""
    current = (content["run"] or 0) if content is not None else None
    replaced = "production remplacée par une relance"
    if "run" in payload:
        run = int(payload["run"])
        return (None, replaced) if current is not None and current != run else (run, "")
    adopted = _own_result(ctx).get("run")           # posé par un passage précédent (attente des générations)
    if adopted is not None:
        return (None, replaced) if current is not None and current != adopted else (int(adopted), "")
    if content is None:
        return 0, ""
    if content["status"] in store.ACTIVE:
        return current, ""
    if content["status"] in store.FAILED:
        return current + 1, ""                      # nouvelle demande après un échec : nouvelle production
    return None, f"contenu déjà {content['status']}"   # rendu, validé ou rejeté : déjà produit


def _start_run(conn: sqlite3.Connection, now: datetime, idea_row: sqlite3.Row, run: int,
               content: sqlite3.Row | None) -> None:
    """Crée la ligne `content` (id = id de l'idée) ou la remet à zéro pour une nouvelle production."""
    idea_json = loads(idea_row["idea"], {})
    if not isinstance(idea_json, dict):
        idea_json = {}                    # illisible : _parse_idea le dira juste après, avec le contenu en échec
    account = idea_row["account_id"]
    if not account or not str(account).endswith(":tiktok"):
        phone = idea_json.get("phone_id") or (str(account).split(":")[0] if account else "")
        account = f"{phone}:tiktok" if phone else None
    try:
        spec = formats.get(idea_row["format"])
        kind, label = spec.kind, spec.ai_label_required
    except KeyError:
        kind, label = "video", False
    shots = [s for s in idea_json.get("shots") or [] if isinstance(s, dict)]
    # Label IA dès qu'un plan est généré (visages, voix ou scènes réalistes), même si l'idée l'oublie.
    ai_label = bool(idea_json.get("ai_label") or label or any(s.get("kind") in AI_KINDS for s in shots))
    fields = dict(app_id=idea_row["app_id"], idea_id=idea_row["id"], account_id=account, brand=idea_row["app_id"],
                  format=idea_row["format"], lang=idea_row["lang"], kind=kind,
                  caption=idea_json.get("caption") or "", hashtags=_hashtags(idea_json.get("hashtags") or []),
                  ai_label=int(ai_label), parent_id=idea_row["parent_id"])
    with tx(conn):
        if content is None:
            cols = ["id", *fields, "status", "run", "auto_retries", "cost_usd", "created_at", "updated_at"]
            values = [idea_row["id"], *(store.dumps(v) if isinstance(v, list) else v for v in fields.values()),
                      "draft", run, 0, 0, iso(now), iso(now)]
            conn.execute(f"INSERT INTO content({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", values)
        else:
            # Une relance garde la légende éditée par l'équipe ; le reste repart de l'idée.
            for keep in ("caption", "hashtags"):
                fields.pop(keep)
            store.set_content(conn, idea_row["id"], now, **fields, status="draft", run=run, error=None, qa=None,
                              files=None, duration_s=None, approved_at=None)
        store.set_idea(conn, idea_row["id"], now, "producing")
        store.event(conn, now, "content.started", f"{idea_row['id']} : production {run} ({idea_row['format']})",
                    account)


def _hashtags(tags: list) -> list[str]:
    """« #MotClé » sans espace, sans doublon, 30 au plus (limite Instagram)."""
    out: list[str] = []
    for tag in tags:
        clean = "".join(str(tag).split()).lstrip("#")
        if clean and clean.lower() not in {t[1:].lower() for t in out}:
            out.append(f"#{clean}")
    return out[:30]


def _parse_idea(row: sqlite3.Row) -> Idea:
    try:
        return Idea.model_validate_json(row["idea"])
    except ValueError as e:
        raise Permanent(f"idée illisible ({row['id']}) : {str(e).splitlines()[0]}") from e


def _spec(format_id: str) -> formats.FormatSpec:
    try:
        return formats.get(format_id)
    except KeyError as e:
        raise Permanent(f"format inconnu : {format_id}") from e


def _produce_remotion(ctx: JobContext, content: sqlite3.Row, idea_row: sqlite3.Row, idea: Idea,
                      spec: formats.FormatSpec, run: int) -> dict:
    props, notes = plan.remotion_props(ctx.conn, ctx.config, idea_row["app_id"], idea, spec, idea_row["lang"])
    envelope = {"composition": spec.composition, "props": props, "stills": plan.stills_count(spec, props),
                "expect_audio": bool(props.get("music")), "notes": notes}
    store.set_content(ctx.conn, content["id"], ctx.clock(), props=envelope)
    ctx.enqueue("content.render", {"content_id": content["id"], "run": run},
                key=f"content.render:{content['id']}:r{run}", app_id=idea_row["app_id"])
    return {"content_id": content["id"], "run": run, "next": "content.render"}


def _produce_shots(ctx: JobContext, content: sqlite3.Row, idea_row: sqlite3.Row, idea: Idea,
                   spec: formats.FormatSpec, run: int, payload: dict) -> dict:
    conn, now, cid, app_id = ctx.conn, ctx.clock(), content["id"], idea_row["app_id"]
    plan.validated_props(idea, spec)
    shots = [s.model_dump() for s in idea.shots]
    plan.prepare_shots(conn, ctx.config, app_id, shots)        # assets vérifiés AVANT de payer des générations

    regenerate = {int(i) for i in payload.get("regenerate") or []}
    children: dict[int, int] = {}
    for i, s in enumerate(shots):
        if s["kind"] not in AI_KINDS:
            continue
        image = None
        if s.get("asset_id") is not None:
            row = assets.asset(conn, app_id, int(s["asset_id"]))
            image = str(assets.app_dir(ctx.config, app_id) / row["path"])
        request = plan.video_request(s, ctx.config.settings or {}, idea_row["lang"], image)
        children[i] = ctx.enqueue("video.generate", {"content_id": cid, "shot_index": i, "request": request},
                                  key=_generation_key(conn, cid, i, run, regenerate), app_id=app_id)

    rows = {i: conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone() for i, jid in children.items()}
    lost = [(i, r) for i, r in rows.items() if r["status"] in ("dead", "cancelled")]
    if lost:
        i, r = lost[0]
        why = (r["last_error"] or "annulée").strip().splitlines()[-1][:300]
        store.fail_content(conn, content, now, f"génération du plan {i + 1} abandonnée : {why}")
        return {"content_id": cid, "run": run, "failed": [i for i, _ in lost]}
    pending = [i for i, r in rows.items() if r["status"] != "done"]
    if pending:
        oldest = min(datetime.fromisoformat(rows[i]["created_at"]) for i in pending)
        limit_h = options.generation_timeout_h(ctx.config.settings or {})
        if now - oldest > timedelta(hours=limit_h):
            for i in pending:
                jobs.cancel(conn, rows[i]["id"], clock=ctx.clock)
            store.fail_content(conn, content, now, f"générations vidéo toujours pas terminées après {limit_h:g} h "
                                                   f"(plans {', '.join(str(i + 1) for i in pending)})")
            return {"content_id": cid, "run": run, "failed": pending}
        raise RetryLater(options.poll_s(ctx.config.settings or {}),
                         f"{len(pending)} génération(s) vidéo en cours", result={"run": run, "waiting": pending})

    cost = _generation_cost(conn, cid)
    store.set_content(conn, cid, now, cost_usd=cost)
    ctx.enqueue("content.compose", {"content_id": cid, "run": run, "clips": {str(i): j for i, j in children.items()}},
                key=f"content.compose:{cid}:r{run}", app_id=app_id)
    return {"content_id": cid, "run": run, "next": "content.compose", "cost_usd": cost}


def _generation_cost(conn: sqlite3.Connection, cid: str) -> float:
    """Ce que ce contenu a coûté : toutes ses générations terminées, régénérations comprises."""
    rows = conn.execute("SELECT result FROM jobs WHERE kind='video.generate' AND status='done' "
                        "AND json_extract(payload, '$.content_id') = ?", (cid,)).fetchall()
    return round(sum(float((loads(r["result"], {}) or {}).get("cost_usd") or 0) for r in rows), 4)


def _generation_key(conn: sqlite3.Connection, cid: str, index: int, run: int, regenerate: set[int]) -> str:
    """Clé du contrat `video.generate:<content_id>:<i>` ; un plan à régénérer prend `…:r<run>`, les autres
    réutilisent leur dernière génération (pas de nouvelle dépense)."""
    base = f"video.generate:{cid}:{index}"
    if index in regenerate:
        return f"{base}:r{run}"
    prefix = f"{base}:r"
    row = conn.execute("SELECT key FROM jobs WHERE kind='video.generate' AND (key=? OR substr(key, 1, ?)=?) "
                       "ORDER BY id DESC LIMIT 1", (base, len(prefix), prefix)).fetchone()
    return row["key"] if row else base


# --- content.render / content.compose ------------------------------------------------------------------------

@jobs.handler("content.render", max_attempts=2, lease_s=1800, backoff_s=(60, 300))
def render(ctx: JobContext, payload: dict) -> dict:
    content = _current(ctx, payload)
    if content is None or content["status"] not in store.ACTIVE:
        return _skip("production remplacée ou déjà rendue")
    envelope = loads(content["props"], {}) or {}
    with _failing(ctx, content):
        if not envelope.get("composition"):
            raise Permanent("props du rendu absentes : relancer la production")
        return _render(ctx, content, envelope)


@jobs.handler("content.compose", max_attempts=2, lease_s=1800, backoff_s=(60, 300))
def compose(ctx: JobContext, payload: dict) -> dict:
    content = _current(ctx, payload)
    if content is None or content["status"] not in store.ACTIVE:
        return _skip("production remplacée ou déjà rendue")
    conn, config, cid = ctx.conn, ctx.config, content["id"]
    staging = assets.public_dir(config) / "content" / cid
    with _failing(ctx, content):
        idea_row = store.get_idea(conn, content["idea_id"])
        if idea_row is None:
            raise Permanent(f"idée introuvable : {content['idea_id']}")
        idea = _parse_idea(idea_row)
        shots = [s.model_dump() for s in idea.shots]
        trims = plan.trims(plan.validated_props(idea, _spec(content["format"])))
        prepared = plan.prepare_shots(conn, config, content["app_id"], shots)
        try:
            clips = _stage_clips(ctx, payload.get("clips") or {}, shots, staging)
            brand, notes = assets.brand(conn, config, content["app_id"], content["lang"])
            end_text = shots[-1].get("on_screen_text") if shots and shots[-1]["kind"] == "end_card" else None
            cta = assets.cta(conn, content["app_id"], content["lang"], brand["name"], end_text)
            props, timeline, more = plan.story_props(shots=shots, prepared=prepared, clips=clips, trims=trims,
                                                     hook=idea.hook, brand=brand, cta=cta, lang=content["lang"])
            envelope = {"composition": formats_extra.STORY, "props": props, "timeline": timeline,
                        "expect_audio": any(s.get("audio") for s in props["shots"]), "notes": notes + more}
            store.set_content(conn, cid, ctx.clock(), props=envelope)
            return _render(ctx, content, envelope)
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def _stage_clips(ctx: JobContext, clips: dict, shots: list[dict], staging: Path) -> dict[int, dict]:
    """Les clips générés (résultat des tâches video.generate) copiés sous render/public/content/<id>/."""
    settings = ctx.config.settings or {}
    ffmpeg, ffprobe = options.ffmpeg_bin(settings), options.ffprobe_bin(settings)
    out: dict[int, dict] = {}
    for i, s in enumerate(shots):
        if s["kind"] not in AI_KINDS:
            continue
        job_id = clips.get(str(i))
        row = ctx.conn.execute("SELECT status, result FROM jobs WHERE id=?", (job_id,)).fetchone() if job_id else None
        result = loads(row["result"], {}) if row else {}
        src = Path(str((result or {}).get("path") or ""))
        if row is None or row["status"] != "done" or not src.is_file():
            raise Permanent(f"plan {i + 1} : clip généré introuvable ({src or 'aucun résultat'}) : relancer la production")
        rel = f"content/{staging.name}/clip-{i}{src.suffix.lower() or '.mp4'}"
        assets.publish_file(src, assets.public_dir(ctx.config) / rel)
        try:
            info = qa.probe(src, ffprobe)
            duration = qa.duration_of(info)
        except qa.QAError as e:
            raise Permanent(f"plan {i + 1} : clip généré illisible ({e})") from e
        speech = None
        if s["kind"] == "ugc_avatar" and qa.has_audio(info):
            speech = qa.speech_bounds(src, duration, ffmpeg)
        out[i] = {"src": rel, "duration": duration, "speech": speech}
    return out


def _render(ctx: JobContext, content: sqlite3.Row, envelope: dict) -> dict:
    """Rendu sous verrou, dans un dossier temporaire, puis remplacement des fichiers de out/<id>/."""
    conn, cid, run = ctx.conn, content["id"], content["run"] or 0
    final_dir = store.content_dir(ctx.config, cid)
    work = final_dir / f".r{run}"
    shutil.rmtree(work, ignore_errors=True)
    stills = envelope.get("stills")
    job = renderer.RenderJob(cid, envelope["composition"], envelope["props"],
                             out=None if stills else work / f"{cid}.mp4", out_dir=work if stills else None,
                             stills=stills)
    lock = Path(ctx.config.data_dir) / "render.lock"
    try:
        with renderer.exclusive(lock):
            store.set_content(conn, cid, ctx.clock(), status="rendering", error=None)
            try:
                engine = renderer.get(ctx.services, ctx.config)
            except renderer.RenderUnavailable as e:
                raise Permanent(str(e)) from e
            result = engine.render([job]).get(cid) or renderer.RenderResult(cid, False, error="aucun résultat")
    except renderer.Busy as e:
        raise RetryLater(BUSY_RETRY_S, str(e)) from e
    if not result.ok:
        raise RenderFailed(f"rendu en échec : {(result.error or 'erreur inconnue')[:800]}")
    produced = [Path(f) for f in result.files]
    missing = [p.name for p in produced if not p.is_file()]
    if not produced or missing:
        raise RenderFailed(f"rendu sans fichier ({', '.join(missing) or 'aucun'})")
    files = _install(produced, final_dir, cid)
    shutil.rmtree(work, ignore_errors=True)
    with tx(conn):
        store.set_content(conn, cid, ctx.clock(), status="rendered", files=[str(f) for f in files], qa=None,
                          error=None)
        ctx.enqueue("content.qa", {"content_id": cid, "run": run}, key=f"content.qa:{cid}:r{run}",
                    app_id=content["app_id"])
    return {"content_id": cid, "run": run, "files": len(files), "seconds": result.seconds}


def _install(produced: list[Path], final_dir: Path, cid: str) -> list[Path]:
    """Met les fichiers rendus à leur place définitive et retire ceux d'un rendu précédent (seulement les
    nôtres : <id>.mp4, NN.png, poster.jpg ; les clips générés rangés là par le module providers restent)."""
    final_dir.mkdir(parents=True, exist_ok=True)
    names = {p.name for p in produced}
    for old in final_dir.iterdir():
        ours = old.name in (f"{cid}.mp4", "poster.jpg") or re.fullmatch(r"\d{2}\.png", old.name)
        if old.is_file() and ours and old.name not in names:
            old.unlink()                          # images d'un ancien carrousel, ancien aperçu
    out = []
    for p in sorted(produced):
        target = final_dir / p.name
        p.replace(target)
        out.append(target)
    return out


# --- content.qa ------------------------------------------------------------------------------------------------

@jobs.handler("content.qa", max_attempts=2, lease_s=900)
def check(ctx: JobContext, payload: dict) -> dict:
    content = _current(ctx, payload)
    if content is None or content["status"] != "rendered" or store.qa_ok(content):
        return _skip("production remplacée ou déjà contrôlée")
    with _failing(ctx, content):
        report = run_qa(ctx.conn, ctx.config, content)
        return apply_qa(ctx, content, report)


def run_qa(conn: sqlite3.Connection, config, content: sqlite3.Row) -> qa.Report:
    """Les contrôles d'un contenu rendu (aussi utilisés par `python -m loopcast content qa`)."""
    settings = config.settings or {}
    envelope = loads(content["props"], {}) or {}
    files = [Path(f) for f in loads(content["files"], []) or []]
    if not files:
        report = qa.Report("video")
        report.fail("Aucun fichier rendu.", transient=True)
        return report
    if (content["kind"] or "video") == "carousel":
        report = qa.check_carousel(files, expected=envelope.get("stills"))
    else:
        report = qa.check_video(files[0], settings, expect_audio=bool(envelope.get("expect_audio")),
                                timeline=envelope.get("timeline"))
    report.warnings[:0] = envelope.get("notes") or []
    try:
        duration = (report.details.get("probe") or {}).get("duration_s") or 0
        qa.make_poster(files[0], store.content_dir(config, content["id"]) / "poster.jpg",
                       is_video=report.kind == "video", ffmpeg=options.ffmpeg_bin(settings),
                       at_s=min(1.5, duration / 3) if duration else 0)
    except (qa.QAError, OSError) as e:
        report.warnings.append(f"aperçu non créé : {e}")
    return report


def apply_qa(ctx: JobContext, content: sqlite3.Row, report: qa.Report) -> dict:
    conn, now, cid, run = ctx.conn, ctx.clock(), content["id"], content["run"] or 0
    settings = ctx.config.settings or {}
    data = {**report.as_dict(), "checked_at": iso(now), "run": run}
    duration = (report.details.get("probe") or {}).get("duration_s")
    if report.ok:
        auto = options.review_mode(settings) == "auto"
        with tx(conn):
            store.set_content(conn, cid, now, qa=data, status="approved" if auto else "rendered",
                              approved_at=iso(now) if auto else None, duration_s=duration, error=None)
            store.set_idea(conn, content["idea_id"], now, "produced")
            store.event(conn, now, "content.approved" if auto else "content.ready",
                        f"{cid} : contrôle qualité réussi" + (", validé automatiquement" if auto else ", à valider"),
                        content["account_id"])
        return {"content_id": cid, "ok": True, "status": "approved" if auto else "rendered"}

    reasons = " ; ".join(report.reasons)
    retry = report.transient and (content["auto_retries"] or 0) < options.max_auto_retries(settings)
    with tx(conn):
        store.set_content(conn, cid, now, qa=data, status="qa_failed", error=reasons, duration_s=duration)
        if retry:
            new_run = run + 1
            store.set_content(conn, cid, now, run=new_run, auto_retries=(content["auto_retries"] or 0) + 1)
            jobs.enqueue(conn, "content.produce", {"idea_id": content["idea_id"], "run": new_run,
                                                   "regenerate": report.regenerate},
                         key=f"content.produce:{cid}:r{new_run}", app_id=content["app_id"], parent_id=ctx.job.id,
                         clock=ctx.clock)
            store.event(conn, now, "content.retry", f"{cid} : contrôle qualité raté ({reasons}), nouvelle tentative"
                        + (f" avec régénération des plans {', '.join(str(i + 1) for i in report.regenerate)}"
                           if report.regenerate else ""), content["account_id"])
        else:
            store.set_idea(conn, content["idea_id"], now, "failed", reasons)
            store.event(conn, now, "content.qa_failed", f"{cid} : {reasons}", content["account_id"])
    return {"content_id": cid, "ok": False, "retry": retry, "reasons": report.reasons}
