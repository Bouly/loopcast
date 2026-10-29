"""Lectures et écritures du module strategy (aucun appel à Claude ici).

Partagé par les tâches (tasks.py), les routes (api.py) et la CLI (cli.py) : des requêtes courtes et
des transactions courtes. Les erreurs de donnée lèvent NotFound / Conflict : les tâches les changent
en jobs.Permanent, les routes en 404 / 409.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterator

from loopcast import accounts, jobs
from loopcast.schemas import AccountVoice, AssetAnalysis, Idea, ProductBrief, Strategy
from loopcast.strategy.validate import DUP_WINDOW, AssetRef, IdeaContext

MAX_BATCH = 12                                   # idées par appel à Claude, au plus

IDEAS_IN_PROGRESS = ("proposed", "approved", "producing")
CONTENT_IN_STOCK = ("draft", "rendering", "rendered", "approved")
POST_CONSUMED = ("running", "posted", "needs_human")


class NotFound(LookupError):
    pass


class Conflict(ValueError):
    pass


def iso(dt: datetime) -> str:
    return jobs.iso(dt)


def hour_bucket(now: datetime) -> str:
    """Tranche de temps des clés d'idempotence : une par heure (UTC)."""
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H")


def _json(raw: Any, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE … COMMIT (ROLLBACK sur exception). Dans une transaction déjà ouverte : rien de plus."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    else:
        if conn.in_transaction:
            conn.execute("COMMIT")


# --- Réglages ------------------------------------------------------------------------------------

def pipeline_settings(settings: dict | None) -> dict:
    """Les réglages `pipeline.*` lus par le module, avec leurs valeurs par défaut."""
    settings = settings or {}
    p = settings.get("pipeline") or {}

    def num(key: str, default: int, lo: int, hi: int) -> int:
        try:
            value = int(p.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(lo, min(value, hi))

    legacy_target = settings.get("stock_target", 6)      # ancien emplacement, à la racine de settings.yaml
    return {
        "auto_approve_strategy": bool(p.get("auto_approve_strategy", False)),
        "idea_review": str(p.get("idea_review", "auto")).strip().lower(),
        "stock_target": num("stock_target", legacy_target if isinstance(legacy_target, int) else 6, 0, 60),
        "ideas_per_batch": num("ideas_per_batch", 6, 1, MAX_BATCH),
        "posts_per_day_per_account": num("posts_per_day_per_account", 3, 1, 5),
    }


def new_idea_status(settings: dict | None) -> str:
    """`pipeline.idea_review` : auto (défaut) → l'idée part en production ; sinon elle attend un humain."""
    return "approved" if pipeline_settings(settings)["idea_review"] == "auto" else "proposed"


# --- Événements -------------------------------------------------------------------------------------

def add_event(conn: sqlite3.Connection, now: datetime, kind: str, message: str,
              account_id: str | None = None) -> None:
    conn.execute("INSERT INTO events(at, account_id, kind, message) VALUES (?,?,?,?)",
                 (iso(now), account_id, kind, message))


def add_event_once(conn: sqlite3.Connection, now: datetime, kind: str, message: str, *,
                   within: timedelta = timedelta(hours=24), account_id: str | None = None) -> bool:
    """Comme add_event, sauf si le même message a déjà été inscrit récemment (alertes répétées)."""
    if conn.execute("SELECT 1 FROM events WHERE kind=? AND message=? AND at >= ? LIMIT 1",
                    (kind, message, iso(now - within))).fetchone():
        return False
    add_event(conn, now, kind, message, account_id)
    return True


# --- App, fiche, captures ------------------------------------------------------------------------------

def get_app(conn: sqlite3.Connection, app_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
    if row is None:
        return None
    app = dict(row)
    app["langs"] = _json(app.get("langs"), [])
    app["brand"] = _json(app.get("brand"), {})
    return app


def require_app(conn: sqlite3.Connection, app_id: str) -> dict:
    app = get_app(conn, app_id)
    if app is None:
        raise NotFound(f"app « {app_id} » inconnue")
    return app


@dataclass
class BriefRecord:
    id: int
    version: int
    brief: ProductBrief
    approved_at: str | None


def approved_brief(conn: sqlite3.Connection, app_id: str, brief_id: int | None = None) -> BriefRecord | None:
    """La fiche approuvée demandée, ou la dernière fiche approuvée de l'app."""
    if brief_id is not None:
        row = conn.execute("SELECT * FROM app_briefs WHERE id=? AND app_id=? AND approved_at IS NOT NULL",
                           (brief_id, app_id)).fetchone()
    else:
        row = conn.execute("""SELECT * FROM app_briefs WHERE app_id=? AND approved_at IS NOT NULL
                              ORDER BY version DESC LIMIT 1""", (app_id,)).fetchone()
    if row is None:
        return None
    try:
        brief = ProductBrief.model_validate_json(row["brief"])
    except ValueError as e:
        raise Conflict(f"fiche produit #{row['id']} de {app_id} illisible : {e}") from e
    return BriefRecord(row["id"], row["version"], brief, row["approved_at"])


def brief_sources(brief: ProductBrief) -> str:
    """Les textes de la fiche validée par l'équipe : un chiffre qui s'y trouve est sourcé."""
    parts = [brief.pricing, brief.problem, brief.solution, brief.one_liner.fr, brief.one_liner.en,
             *brief.proof_points, *brief.value_props, *brief.differentiators]
    parts += [f"{f.benefit} {f.proof}" for f in brief.features]
    parts += [o.answer for o in brief.objections]
    return "\n".join(p for p in parts if p)


@dataclass
class Asset:
    id: int
    kind: str
    filename: str
    mime: str
    caption: str
    duration_s: float | None
    analysis: AssetAnalysis | None

    def ref(self) -> AssetRef:
        a = self.analysis
        return AssetRef(self.id, self.kind, self.mime, None if a is None else a.usable_in_video,
                        a.caution if a else "")

    def for_prompt(self) -> dict:
        d: dict[str, Any] = {"asset_id": self.id, "kind": self.kind}
        if self.caption:
            d["caption"] = self.caption
        if self.duration_s:
            d["duration_s"] = round(self.duration_s, 1)
        if self.analysis is not None:
            d.update(self.analysis.model_dump())
        else:
            d.update(usable_in_video=None, note="pas encore analysée : ne pas l'utiliser")
        return d


def app_assets(conn: sqlite3.Connection, app_id: str) -> list[Asset]:
    """Captures et vidéos de démo (pas le logo ni les documents)."""
    out = []
    for r in conn.execute("""SELECT * FROM app_assets WHERE app_id=? AND kind IN ('screenshot','demo_video','other')
                             ORDER BY id""", (app_id,)):
        analysis = None
        if r["analysis"]:
            try:
                analysis = AssetAnalysis.model_validate_json(r["analysis"])
            except ValueError:
                analysis = None
        out.append(Asset(r["id"], r["kind"], r["filename"] or "", r["mime"] or "", r["caption"] or "",
                         r["duration_s"], analysis))
    return out


# --- Stratégies -------------------------------------------------------------------------------------------

@dataclass
class StrategyRecord:
    id: int
    app_id: str
    version: int
    status: str
    brief_id: int | None
    strategy: Strategy
    model: str | None
    created_at: str | None
    approved_at: str | None
    note: str | None
    job_id: int | None

    def to_dict(self, full: bool = True) -> dict:
        d = {"id": self.id, "app_id": self.app_id, "version": self.version, "status": self.status,
             "brief_id": self.brief_id, "model": self.model, "created_at": self.created_at,
             "approved_at": self.approved_at, "note": self.note}
        if full:
            d["strategy"] = self.strategy.model_dump()
        return d


def _strategy(row: sqlite3.Row | None) -> StrategyRecord | None:
    if row is None:
        return None
    try:
        strategy = Strategy.model_validate_json(row["strategy"])
    except ValueError as e:
        raise Conflict(f"stratégie #{row['id']} illisible : {e}") from e
    return StrategyRecord(row["id"], row["app_id"], row["version"], row["status"], row["brief_id"], strategy,
                          row["model"], row["created_at"], row["approved_at"], row["note"], row["job_id"])


def current_strategy(conn: sqlite3.Connection, app_id: str) -> StrategyRecord | None:
    """La stratégie en vigueur : la plus récente approuvée."""
    return _strategy(conn.execute("""SELECT * FROM strategies WHERE app_id=? AND status='approved'
                                     ORDER BY version DESC LIMIT 1""", (app_id,)).fetchone())


def latest_draft(conn: sqlite3.Connection, app_id: str) -> StrategyRecord | None:
    """Le brouillon le plus récent, s'il est plus récent que la stratégie en vigueur."""
    current = current_strategy(conn, app_id)
    return _strategy(conn.execute("""SELECT * FROM strategies WHERE app_id=? AND status='draft' AND version > ?
                                     ORDER BY version DESC LIMIT 1""",
                                  (app_id, current.version if current else 0)).fetchone())


def strategy_versions(conn: sqlite3.Connection, app_id: str) -> list[StrategyRecord]:
    return [_strategy(r) for r in conn.execute("SELECT * FROM strategies WHERE app_id=? ORDER BY version DESC",
                                               (app_id,))]


def strategy_by_version(conn: sqlite3.Connection, app_id: str, version: int) -> StrategyRecord | None:
    return _strategy(conn.execute("SELECT * FROM strategies WHERE app_id=? AND version=?",
                                  (app_id, version)).fetchone())


def strategy_by_id(conn: sqlite3.Connection, strategy_id: int) -> StrategyRecord | None:
    return _strategy(conn.execute("SELECT * FROM strategies WHERE id=?", (strategy_id,)).fetchone())


def strategy_for_job(conn: sqlite3.Connection, job_id: int) -> StrategyRecord | None:
    return _strategy(conn.execute("SELECT * FROM strategies WHERE job_id=? ORDER BY id LIMIT 1",
                                  (job_id,)).fetchone())


def insert_strategy(conn: sqlite3.Connection, *, app_id: str, brief_id: int | None, strategy: Strategy,
                    model: str | None, now: datetime, job_id: int | None = None,
                    note: str | None = None) -> StrategyRecord:
    """Nouvelle version (brouillon). À appeler dans une transaction (numéro de version)."""
    version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM strategies WHERE app_id=?",
                           (app_id,)).fetchone()[0]
    cur = conn.execute(
        """INSERT INTO strategies(app_id, version, brief_id, strategy, status, model, created_at, job_id, note)
           VALUES (?,?,?,?,'draft',?,?,?,?)""",
        (app_id, version, brief_id, strategy.model_dump_json(), model, iso(now), job_id, note or None))
    return strategy_by_id(conn, cur.lastrowid)


def save_edit(conn: sqlite3.Connection, record: StrategyRecord, strategy: Strategy, now: datetime,
              note: str | None) -> StrategyRecord:
    """Édition humaine : un brouillon est modifié sur place ; une version approuvée ou archivée donne
    un nouveau brouillon (la stratégie en vigueur ne change qu'à l'approbation)."""
    with transaction(conn):
        if record.status == "draft":
            conn.execute("UPDATE strategies SET strategy=?, note=? WHERE id=? AND status='draft'",
                         (strategy.model_dump_json(), note or None, record.id))
            return strategy_by_id(conn, record.id)
        return insert_strategy(conn, app_id=record.app_id, brief_id=record.brief_id, strategy=strategy,
                               model=record.model, now=now,
                               note=note or f"édition de la v{record.version}")


def approve_strategy(conn: sqlite3.Connection, strategy_id: int, now: datetime, *, priority: int = 0) -> dict:
    """Approuve une version : l'ancienne est archivée, l'app passe active, le stock d'idées est demandé.
    Idempotent : approuver deux fois la même version ne fait rien de plus."""
    with transaction(conn):
        rec = strategy_by_id(conn, strategy_id)
        if rec is None:
            raise NotFound(f"stratégie #{strategy_id} introuvable")
        if rec.status == "archived":
            raise Conflict(f"la v{rec.version} est archivée : la modifier crée une nouvelle version à approuver")
        already = rec.status == "approved"
        if not already:
            conn.execute("""UPDATE strategies SET status='archived'
                            WHERE app_id=? AND id<>? AND (status='approved' OR (status='draft' AND version < ?))""",
                         (rec.app_id, rec.id, rec.version))
            conn.execute("UPDATE strategies SET status='approved', approved_at=? WHERE id=?", (iso(now), rec.id))
            add_event(conn, now, "strategy.approved", f"{rec.app_id} : stratégie v{rec.version} approuvée")
        conn.execute("UPDATE apps SET status='active', updated_at=? WHERE id=? AND status NOT IN ('active','paused')",
                     (iso(now), rec.app_id))
        job_id = jobs.enqueue(conn, "ideas.ensure_stock", {"app_id": rec.app_id},
                              key=f"ideas.ensure_stock:{rec.app_id}:strategy-{rec.id}", app_id=rec.app_id,
                              priority=priority, clock=lambda: now)
    return {"app_id": rec.app_id, "strategy_id": rec.id, "version": rec.version, "already": already,
            "ensure_stock_job": job_id}


def voice_for(strategy: Strategy, phone_id: str) -> AccountVoice | None:
    return next((v for v in strategy.voices if v.phone_id == phone_id), None)


# --- Téléphones et comptes ------------------------------------------------------------------------------

def phone_accounts(phone: Any) -> list[str]:
    """Les comptes configurés du téléphone (« phone-1:tiktok », « phone-1:instagram »)."""
    return [f"{phone.id}:{p}" for p in accounts.PLATFORMS if isinstance((phone.accounts or {}).get(p), dict)]


def target_account(phone: Any) -> str | None:
    """Le compte visé par une idée : le TikTok du téléphone (le contenu peut aussi partir sur son Instagram)."""
    accs = phone_accounts(phone)
    return accs[0] if accs else None


def idea_context(brief: ProductBrief, strategy: Strategy, phone: Any, assets: list[Asset]) -> IdeaContext:
    return IdeaContext(lang=phone.lang, phone_id=phone.id, assets={a.id: a.ref() for a in assets},
                       pillars=[p.name for p in strategy.pillars], do_not_say=list(brief.do_not_say),
                       sources=brief_sources(brief))


# --- Idées ---------------------------------------------------------------------------------------------------

def _idea_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["idea"] = _json(d.get("idea"), {})
    return d


def get_idea(conn: sqlite3.Connection, idea_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
    return _idea_row(row) if row else None


def list_ideas(conn: sqlite3.Connection, *, app_id: str | None = None, phone_id: str | None = None,
               status: str | None = None, parent_id: str | None = None, limit: int = 100,
               offset: int = 0) -> list[dict]:
    sql, args = "SELECT * FROM ideas WHERE 1=1", []
    for col, value in (("app_id", app_id), ("phone_id", phone_id), ("parent_id", parent_id)):
        if value:
            sql += f" AND {col}=?"
            args.append(value)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        sql += f" AND status IN ({','.join('?' * len(statuses))})"
        args += statuses
    sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    args += [max(1, min(limit, 500)), max(0, offset)]
    return [_idea_row(r) for r in conn.execute(sql, args)]


def idea_videos(conn: sqlite3.Connection, idea_ids: list[str]) -> dict[str, dict]:
    """La vidéo de chaque idée et ses posts (hors annulés) : de l'idée, l'écran mène à la vidéo puis au post.
    `to_review` : rendue, contrôle qualité réussi, pas encore décidée (le « à valider » de la validation)."""
    out: dict[str, dict] = {}
    for start in range(0, len(idea_ids), 400):                  # limite de paramètres de SQLite
        chunk = idea_ids[start:start + 400]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"""SELECT id, idea_id, status, (status = 'rendered' AND json_extract(qa, '$.ok') = 1) AS to_review
                    FROM content WHERE idea_id IN ({marks}) ORDER BY created_at""", chunk):
            out[r["idea_id"]] = {"id": r["id"], "status": r["status"], "to_review": bool(r["to_review"]),
                                 "posts": []}
    by_content = {v["id"]: v for v in out.values()}
    for start in range(0, len(by_content), 400):
        chunk = list(by_content)[start:start + 400]
        marks = ",".join("?" * len(chunk))
        for p in conn.execute(
                f"""SELECT id, content_id, account_id, platform, status, scheduled_at, posted_at FROM posts
                    WHERE content_id IN ({marks}) AND status != 'skipped'
                    ORDER BY COALESCE(posted_at, scheduled_at), id""", chunk):
            by_content[p["content_id"]]["posts"].append({k: p[k] for k in p.keys() if k != "content_id"})
    return out


def recent_hooks(conn: sqlite3.Connection, app_id: str, *, limit: int = DUP_WINDOW,
                 lang: str | None = None) -> list[str]:
    """Les accroches les plus récentes de l'app (toutes idées, rejetées comprises), pour l'anti-doublon."""
    sql, args = "SELECT hook FROM ideas WHERE app_id=?", [app_id]
    if lang:
        sql += " AND lang=?"
        args.append(lang)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    args.append(limit)
    return [r["hook"] for r in conn.execute(sql, args) if r["hook"]]


def ideas_for_job(conn: sqlite3.Connection, job_id: int) -> list[str]:
    return [r["id"] for r in conn.execute("SELECT id FROM ideas WHERE job_id=? ORDER BY id", (job_id,))]


def ideas_with_parent(conn: sqlite3.Connection, parent_id: str) -> list[str]:
    return [r["id"] for r in conn.execute("SELECT id FROM ideas WHERE parent_id=? ORDER BY id", (parent_id,))]


def _next_idea_number(conn: sqlite3.Connection, prefix: str) -> int:
    n = 0
    for (iid,) in conn.execute("SELECT id FROM ideas WHERE substr(id, 1, ?) = ?", (len(prefix), prefix)):
        tail = iid[len(prefix):]
        if tail.isdigit():
            n = max(n, int(tail))
    return n + 1


def insert_ideas(conn: sqlite3.Connection, *, app_id: str, strategy_id: int | None, phone: Any,
                 ideas: list[Idea], status: str, now: datetime, job_id: int | None,
                 parent_id: str | None = None) -> list[str]:
    """Inscrit les idées avec des ids lisibles « <app>-<lang>-<AAAAMMJJ>-<n> ». Dans une transaction."""
    day = now.astimezone(timezone.utc).strftime("%Y%m%d")
    account = target_account(phone)
    numbers: dict[str, int] = {}
    ids = []
    for idea in ideas:
        prefix = f"{app_id}-{idea.lang}-{day}-"
        n = numbers.get(prefix) or _next_idea_number(conn, prefix)
        numbers[prefix] = n + 1
        idea_id = f"{prefix}{n:04d}"
        conn.execute(
            """INSERT INTO ideas(id, app_id, strategy_id, account_id, phone_id, lang, format, pillar, hook, idea,
                                 status, parent_id, job_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (idea_id, app_id, strategy_id, account, phone.id, idea.lang, idea.format, idea.pillar, idea.hook,
             idea.model_dump_json(), status, parent_id, job_id, iso(now), iso(now)))
        ids.append(idea_id)
    return ids


def enqueue_production(conn: sqlite3.Connection, idea_id: str, app_id: str, now: datetime, *,
                       parent_job: int | None = None) -> int:
    """La production prend le relais (tâche content.produce, traitée par le module production)."""
    return jobs.enqueue(conn, "content.produce", {"idea_id": idea_id}, key=f"content.produce:{idea_id}",
                        app_id=app_id, parent_id=parent_job, clock=lambda: now)


RELAUNCHABLE_CONTENT = ("rejected", "failed", "qa_failed")    # contenu d'une idée qu'on peut refaire


def approve_idea(conn: sqlite3.Connection, idea_id: str, now: datetime) -> dict:
    """Approuve l'idée et lance sa production.

    Une idée déjà produite dont la vidéo a été rejetée (ou a échoué) repart pour de bon : nouvelle production
    du même contenu (production.review.relaunch, clé content.produce:<id>:r<n>). Avant, on retombait sur la
    tâche content.produce:<idée> déjà terminée : rien ne repartait, l'idée restait « approved » pour toujours
    et gonflait le stock."""
    with transaction(conn):
        idea = get_idea(conn, idea_id)
        if idea is None:
            raise NotFound(f"idée « {idea_id} » introuvable")
        if idea["status"] not in ("proposed", "rejected", "approved"):
            raise Conflict(f"idée déjà en production (statut « {idea['status']} »)")
        content = conn.execute("SELECT id, status FROM content WHERE id=? OR idea_id=? ORDER BY id=? DESC LIMIT 1",
                               (idea_id, idea_id, idea_id)).fetchone()
        if content is None:
            if idea["status"] != "approved":
                conn.execute("UPDATE ideas SET status='approved', review_note=NULL, updated_at=? WHERE id=?",
                             (iso(now), idea_id))
            job_id = enqueue_production(conn, idea_id, idea["app_id"], now)
            # Rejetée (avant la production) puis approuvée à nouveau : la tâche annulée (même clé) repart.
            jobs.retry(conn, job_id, clock=lambda: now)
            return {"id": idea_id, "status": "approved", "job_id": job_id}
        if content["status"] not in RELAUNCHABLE_CONTENT:
            raise Conflict(f"idée déjà produite : contenu {content['id']} au statut « {content['status']} » "
                           "(le valider ou le rejeter dans la file de validation)")
    # Hors de la transaction : la relance de la production ouvre la sienne.
    try:
        from loopcast.production import review
    except ImportError as e:                       # module production absent : on le dit plutôt que de bloquer
        raise Conflict("idée déjà produite puis rejetée : relance impossible sans le module production") from e
    try:
        job_id = review.relaunch(conn, content["id"], now)
    except review.ReviewError as e:
        raise Conflict(f"idée déjà produite, relance impossible : {e}") from e
    return {"id": idea_id, "status": "producing", "job_id": job_id, "content_id": content["id"]}


def reject_idea(conn: sqlite3.Connection, idea_id: str, note: str, now: datetime) -> dict:
    with transaction(conn):
        idea = get_idea(conn, idea_id)
        if idea is None:
            raise NotFound(f"idée « {idea_id} » introuvable")
        if idea["status"] not in ("proposed", "approved", "rejected"):
            raise Conflict(f"idée déjà en production (statut « {idea['status']} ») : rejeter le contenu à la place")
        if idea["status"] == "approved":
            job = conn.execute("SELECT id, status FROM jobs WHERE key=?", (f"content.produce:{idea_id}",)).fetchone()
            if job is not None and job["status"] not in ("queued", "dead", "cancelled"):
                raise Conflict("la production de cette idée a déjà commencé : rejeter le contenu à la place")
            if job is not None:
                jobs.cancel(conn, job["id"], clock=lambda: now)
        conn.execute("UPDATE ideas SET status='rejected', review_note=?, updated_at=? WHERE id=?",
                     (note.strip() or None, iso(now), idea_id))
    return {"id": idea_id, "status": "rejected"}


def phone_history(conn: sqlite3.Connection, app_id: str, phone_id: str, limit: int = 30) -> dict:
    """Ce que ce compte a reçu récemment : pour équilibrer piliers et formats."""
    rows = conn.execute("""SELECT format, pillar, hook, status FROM ideas WHERE app_id=? AND phone_id=?
                           ORDER BY created_at DESC, rowid DESC LIMIT ?""", (app_id, phone_id, limit)).fetchall()
    # Les refus de l'équipe et leur raison : le retour le plus direct sur ce qui ne convient pas.
    rejected = conn.execute("""SELECT hook, format, review_note FROM ideas
                               WHERE app_id=? AND phone_id=? AND status='rejected'
                               ORDER BY updated_at DESC, rowid DESC LIMIT 8""", (app_id, phone_id)).fetchall()
    return {
        "idees_recentes": len(rows),
        "par_pilier": dict(Counter(r["pillar"] or "—" for r in rows).most_common()),
        "par_format": dict(Counter(r["format"] for r in rows).most_common()),
        "dernieres_accroches": [r["hook"] for r in rows[:10]],
        "refusees_par_l_equipe": [{"hook": r["hook"], "format": r["format"], "raison": r["review_note"] or ""}
                                  for r in rejected],
    }


# --- Stock ------------------------------------------------------------------------------------------------

def phone_stock(conn: sqlite3.Connection, app_id: str, phone_id: str) -> dict:
    """Ce qui attend d'être publié pour ce téléphone : idées en cours, contenus prêts ou en préparation non
    publiés, et idées déjà commandées (tâches ideas.generate en attente).

    Le détail, avec les mots de l'écran : `proposed` idées à relire, `producing` vidéos en production (idées
    approuvées ou en cours de rendu), `to_review` vidéos à valider (rendues, contrôle qualité réussi, pas encore
    décidées), `ready` vidéos prêtes à publier (validées, pas encore publiées)."""
    accs = [f"{phone_id}:{p}" for p in accounts.PLATFORMS]
    ideas_q = ",".join("?" * len(IDEAS_IN_PROGRESS))
    ideas_n, proposed_n = conn.execute(
        f"""SELECT COUNT(*), COALESCE(SUM(status = 'proposed'), 0) FROM ideas
            WHERE app_id=? AND phone_id=? AND status IN ({ideas_q})""",
        (app_id, phone_id, *IDEAS_IN_PROGRESS)).fetchone()
    content_q = ",".join("?" * len(CONTENT_IN_STOCK))
    posts_q = ",".join("?" * len(POST_CONSUMED))
    content_n, review_n, ready_n = conn.execute(
        f"""SELECT COUNT(*),
                   COALESCE(SUM(c.status = 'rendered' AND json_extract(c.qa, '$.ok') = 1), 0),
                   COALESCE(SUM(c.status = 'approved'), 0)
            FROM content c
            WHERE c.app_id=? AND c.status IN ({content_q})
              AND (c.account_id IN (?,?) OR c.idea_id IN (SELECT id FROM ideas WHERE app_id=? AND phone_id=?))
              AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.content_id=c.id AND p.status IN ({posts_q}))
              AND NOT EXISTS (SELECT 1 FROM ideas i WHERE i.id=c.idea_id AND i.status IN ({ideas_q}))""",
        (app_id, *CONTENT_IN_STOCK, *accs, app_id, phone_id, *POST_CONSUMED, *IDEAS_IN_PROGRESS)).fetchone()
    pending_n = conn.execute(
        """SELECT COALESCE(SUM(CAST(json_extract(payload, '$.count') AS INTEGER)), 0) FROM jobs
           WHERE kind='ideas.generate' AND status IN ('queued','running')
             AND json_extract(payload, '$.app_id')=? AND json_extract(payload, '$.phone_id')=?""",
        (app_id, phone_id)).fetchone()[0]
    return {"ideas": ideas_n, "content": content_n, "pending": pending_n,
            "total": ideas_n + content_n + pending_n,
            "proposed": proposed_n, "producing": ideas_n - proposed_n + content_n - review_n - ready_n,
            "to_review": review_n, "ready": ready_n}


# --- Contenus et performances -------------------------------------------------------------------------------

def get_content(conn: sqlite3.Connection, content_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["props"] = _json(d.get("props"), {})
    d["hashtags"] = _json(d.get("hashtags"), [])
    return d


def content_hook(content: dict, idea: dict | None) -> str:
    if idea and idea.get("hook"):
        return idea["hook"]
    props = content.get("props") or {}
    for key in ("hook", "title"):
        if isinstance(props.get(key), str) and props[key]:
            return props[key]
    slides = props.get("slides") or []
    if slides and isinstance(slides[0], dict) and slides[0].get("title"):
        return str(slides[0]["title"])
    return (content.get("caption") or "")[:90]


def content_metrics(conn: sqlite3.Connection, content_id: str) -> dict:
    row = conn.execute("""SELECT MAX(views) AS views, MAX(likes) AS likes, COUNT(*) AS posts FROM posts
                          WHERE content_id=? AND status='posted'""", (content_id,)).fetchone()
    return {"views": row["views"], "likes": row["likes"], "posts": row["posts"]}


def median_views(conn: sqlite3.Connection, account_ids: list[str], since: datetime) -> float | None:
    if not account_ids:
        return None
    marks = ",".join("?" * len(account_ids))
    views = [r[0] for r in conn.execute(
        f"""SELECT views FROM posts WHERE account_id IN ({marks}) AND status='posted' AND views IS NOT NULL
            AND posted_at >= ?""", (*account_ids, iso(since)))]
    return float(median(views)) if views else None


def top_posts(conn: sqlite3.Connection, app_id: str, *, since: datetime, lang: str | None = None,
              min_judged: int = 5, share: float = 0.2, limit: int = 5) -> list[dict]:
    """Les gagnants récents (REPRISE §5.10 : top 20 % des vues, au moins 5 posts jugés)."""
    sql = """SELECT c.id AS content_id, c.format, c.lang, c.account_id, c.caption, c.props, c.idea_id,
                    i.hook AS idea_hook, i.pillar, MAX(p.views) AS views, MAX(p.likes) AS likes
             FROM posts p JOIN content c ON c.id = p.content_id
             LEFT JOIN ideas i ON i.id = c.idea_id
             WHERE c.app_id=? AND p.status='posted' AND p.views IS NOT NULL AND p.posted_at >= ?"""
    args: list = [app_id, iso(since)]
    if lang:
        sql += " AND c.lang=?"
        args.append(lang)
    rows = conn.execute(sql + " GROUP BY c.id ORDER BY views DESC", args).fetchall()
    if len(rows) < min_judged:
        return []
    keep = max(1, min(limit, math.ceil(len(rows) * share)))
    out = []
    for r in rows[:keep]:
        content = {"props": _json(r["props"], {}), "caption": r["caption"]}
        out.append({"content_id": r["content_id"], "format": r["format"], "lang": r["lang"],
                    "account_id": r["account_id"], "pillar": r["pillar"],
                    "hook": content_hook(content, {"hook": r["idea_hook"]}),
                    "views": r["views"], "likes": r["likes"]})
    return out
