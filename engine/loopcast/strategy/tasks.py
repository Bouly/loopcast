"""Les tâches du module strategy.

- strategy.generate   {app_id, brief_id}        fiche approuvée → stratégie (brouillon versionné)
- ideas.generate      {app_id, phone_id, count}  stratégie → idées validées pour un téléphone
- ideas.ensure_stock  {app_id}                   commande les idées qui manquent, téléphone par téléphone
- ideas.variations    {content_id}               un gagnant → 3 variations (accroche, angle, format)

Chaque tâche est rejouable : une tâche relancée après un plantage retrouve ce qu'elle avait écrit
(colonne job_id) au lieu de repayer Claude. Les appels à Claude passent par ctx.service("llm"), après
costs.check_budget, et sont inscrits au registre des coûts.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from loopcast import accounts, costs, formats, jobs, llm
from loopcast.schemas import AccountVoice, Idea, IdeaBatch, Strategy
from loopcast.strategy import prompts, store, validate

log = logging.getLogger(__name__)

# Coût estimé d'un appel, pour costs.check_budget (large : la dépense réelle est inscrite après).
ESTIMATE_USD = {"strategy.generate": 0.60, "ideas.generate": 0.50, "ideas.repair": 0.25, "ideas.variations": 0.40}
WINNERS_WINDOW = timedelta(days=14)


def _require(payload: dict, key: str) -> Any:
    value = payload.get(key)
    if value in (None, ""):
        raise jobs.Permanent(f"payload sans « {key} »")
    return value


def _settings(ctx: jobs.JobContext) -> dict:
    return getattr(ctx.config, "settings", None) or {}


def _effort(ctx: jobs.JobContext, task: str) -> str | None:
    """Effort explicite pour une tâche que llm.DEFAULT_EFFORT ne connaît pas (réglable dans llm.tasks)."""
    if task in llm.DEFAULT_EFFORT:
        return None
    per_task = ((_settings(ctx).get("llm") or {}).get("tasks") or {}).get(task) or {}
    return per_task.get("effort") or "high"


class _BudgetRefused(Exception):
    pass


def _ask(ctx: jobs.JobContext, *, task: str, system: str, content: str, schema: type, app_id: str,
         ref: str, wait_for_budget: bool = True) -> llm.LLMResult:
    """Un appel à Claude : budget vérifié avant, coût inscrit après, erreurs traduites pour la file."""
    now = ctx.clock()
    check = costs.check_budget(ctx.conn, _settings(ctx), now, ESTIMATE_USD.get(task, 0.5), app_id=app_id)
    if not check.ok:
        store.add_event_once(ctx.conn, now, "strategy.budget", f"{app_id} : {task} en attente ({check.reason})")
        if not wait_for_budget:
            raise _BudgetRefused(check.reason)
        delay = (check.retry_at - now).total_seconds() if check.retry_at else 3600
        raise jobs.RetryLater(max(60.0, delay), f"budget : {check.reason}")
    effort = _effort(ctx, task)
    try:
        res = ctx.service("llm").structured(task=task, system=system, content=content, schema=schema,
                                            **({"effort": effort} if effort else {}))
    except llm.LLMError as e:          # pas de clé, refus, réponse tronquée : réessayer n'y changera rien
        raise jobs.Permanent(f"{task} : {e}") from e
    llm.record_cost(ctx.conn, res, at=ctx.clock(), task=task, app_id=app_id, job_id=ctx.job.id, ref=ref)
    return res


def _data_errors(fn):
    """NotFound / Conflict (données) → échec définitif, avec le message en français."""

    @functools.wraps(fn)
    def wrapper(ctx: jobs.JobContext, payload: dict):
        try:
            return fn(ctx, payload)
        except (store.NotFound, store.Conflict) as e:
            raise jobs.Permanent(str(e)) from e

    return wrapper


# --- strategy.generate -----------------------------------------------------------------------------------

@jobs.handler("strategy.generate", lease_s=1800)
@_data_errors
def generate_strategy(ctx: jobs.JobContext, payload: dict) -> dict:
    """Fiche approuvée + captures + téléphones + catalogue → stratégie v(n+1), en brouillon."""
    app_id = _require(payload, "app_id")
    conn = ctx.conn
    done = store.strategy_for_job(conn, ctx.job.id)
    if done is not None:
        return {"strategy_id": done.id, "version": done.version, "reused": True}

    app = store.require_app(conn, app_id)
    brief_id = payload.get("brief_id")
    brief = store.approved_brief(conn, app_id, brief_id)
    if brief is None:
        raise jobs.Permanent(f"{app_id} : fiche produit #{brief_id} introuvable ou non approuvée" if brief_id
                             else f"{app_id} : aucune fiche produit approuvée")
    latest = store.approved_brief(conn, app_id)
    if latest is not None and latest.version > brief.version:
        return {"skipped": f"fiche v{brief.version} remplacée par la v{latest.version}"}
    phones = accounts.phones_for_app(ctx.config, app_id)
    if not phones:
        raise jobs.Permanent(f"{app_id} : aucun téléphone ne promeut cette app (devices.yaml, champ apps)")

    settings = store.pipeline_settings(_settings(ctx))
    now = ctx.clock()
    current = store.current_strategy(conn, app_id)
    content = prompts.strategy_request(
        app=app, brief=brief.brief, assets=store.app_assets(conn, app_id), phones=phones,
        cadence=settings["posts_per_day_per_account"], budget=costs.budget_settings(_settings(ctx)),
        current=current.strategy if current else None,
        winners=store.top_posts(conn, app_id, since=now - WINNERS_WINDOW), note=payload.get("note"))
    system = prompts.strategy_system()
    ask = dict(task="strategy.generate", system=system, schema=Strategy, app_id=app_id, ref=f"strategy:{app_id}")

    res = _ask(ctx, content=content, **ask)
    strategy, blocking, warnings = validate.check_strategy(res.data, phones)
    if blocking or warnings:          # une seconde chance, avec la liste des problèmes
        first = (res, strategy, blocking, warnings)
        res = _ask(ctx, content=content + prompts.strategy_fix(res.data, blocking + warnings), **ask)
        strategy, blocking, warnings = validate.check_strategy(res.data, phones)
        if blocking and not first[2]:     # la correction a cassé ce qui tenait : on garde la première version
            res, strategy, blocking, warnings = first
        if blocking:
            raise jobs.Permanent(f"{app_id} : stratégie inutilisable après correction : " + " ; ".join(blocking[:5]))

    note_parts = [f"consigne : {payload['note'].strip()}"] if (payload.get("note") or "").strip() else []
    if warnings:
        note_parts.append("à vérifier : " + " ; ".join(warnings))
    now = ctx.clock()
    with store.transaction(conn):
        again = store.strategy_for_job(conn, ctx.job.id)      # une autre exécution a déjà écrit
        if again is not None:
            return {"strategy_id": again.id, "version": again.version, "reused": True}
        rec = store.insert_strategy(conn, app_id=app_id, brief_id=brief.id, strategy=strategy, model=res.model,
                                    now=now, job_id=ctx.job.id, note=" · ".join(note_parts) or None)
        conn.execute("""UPDATE apps SET status='strategy_ready', updated_at=?
                        WHERE id=? AND status NOT IN ('active','paused')""", (store.iso(now), app_id))
        store.add_event(conn, now, "strategy.generated",
                        f"{app_id} : stratégie v{rec.version} prête à valider"
                        + (f" ({len(warnings)} point(s) à vérifier)" if warnings else ""))
    approved = False
    if settings["auto_approve_strategy"] and not warnings:
        store.approve_strategy(conn, rec.id, now)
        approved = True
    return {"strategy_id": rec.id, "version": rec.version, "approved": approved, "warnings": warnings}


# --- Le contexte d'un compte (idées, réparations, variations) ------------------------------------------------

@dataclass
class AccountEnv:
    app_id: str
    phone: Any
    voice: AccountVoice
    strategy: store.StrategyRecord
    brief: store.BriefRecord
    assets: list
    check: validate.IdeaContext
    used_hooks: list[str] = field(default_factory=list)


def _account_env(ctx: jobs.JobContext, app_id: str, phone_id: str) -> AccountEnv:
    conn = ctx.conn
    store.require_app(conn, app_id)
    brief = store.approved_brief(conn, app_id)
    if brief is None:
        raise jobs.Permanent(f"{app_id} : aucune fiche produit approuvée")
    strat = store.current_strategy(conn, app_id)
    if strat is None:
        raise jobs.Permanent(f"{app_id} : aucune stratégie approuvée (approuver une stratégie d'abord)")
    phone = ctx.config.phone_by_id(phone_id) if ctx.config is not None else None
    if phone is None:
        raise jobs.Permanent(f"téléphone « {phone_id} » absent de devices.yaml")
    if app_id not in (phone.apps or []):
        raise jobs.Permanent(f"{phone_id} ne promeut pas {app_id} (devices.yaml, champ apps)")
    voice = store.voice_for(strat.strategy, phone_id)
    if voice is None:
        raise jobs.Permanent(f"{app_id} : la stratégie v{strat.version} n'a pas de voix pour {phone_id} "
                             f"(relancer la stratégie)")
    assets = store.app_assets(conn, app_id)
    # Anti-doublon dans la langue du compte : ce sont ces accroches-là que Claude voit dans le prompt (comparer
    # entre langues écarterait des mots voisins, « POV: habits » contre « POV : habitudes »).
    return AccountEnv(app_id, phone, voice, strat, brief, assets,
                      store.idea_context(brief.brief, strat.strategy, phone, assets),
                      store.recent_hooks(conn, app_id, lang=phone.lang))


def _context_text(ctx: jobs.JobContext, env: AccountEnv) -> str:
    now = ctx.clock()
    return prompts.idea_context(
        phone=env.phone, voice=env.voice, strategy=env.strategy.strategy, brief=env.brief.brief, assets=env.assets,
        used_hooks=env.used_hooks,
        history=store.phone_history(ctx.conn, env.app_id, env.phone.id),
        winners=store.top_posts(ctx.conn, env.app_id, since=now - WINNERS_WINDOW, lang=env.phone.lang))


Extra = Callable[[int, Idea], list[str]]      # contrôles propres à une position (variations)


@dataclass
class Screening:
    """Le tri d'un lot d'idées ; chaque idée garde sa position d'origine dans la réponse de Claude."""
    valid: list[tuple[int, Idea]] = field(default_factory=list)
    invalid: list[tuple[int, Idea, list[str]]] = field(default_factory=list)
    duplicates: list[tuple[Idea, str]] = field(default_factory=list)


def _screen(items: list[tuple[int, Idea]], check: validate.IdeaContext, index: validate.HookIndex,
            extra: Extra | None = None) -> Screening:
    """Doublons écartés ; erreurs listées ; les valides rejoignent l'index (pas de doublon dans un lot)."""
    out = Screening()
    for pos, raw in items:
        idea = validate.normalize_idea(raw, check)
        twin = index.find(idea.hook)
        if twin is not None:
            out.duplicates.append((idea, twin))
            continue
        errors = validate.validate_idea(idea, check) + (extra(pos, idea) if extra else [])
        if errors:
            out.invalid.append((pos, idea, errors))
            continue
        index.add(idea.hook)
        out.valid.append((pos, idea))
    return out


def _repair(ctx: jobs.JobContext, env: AccountEnv, base: str, first: Screening, index: validate.HookIndex,
            extra: Extra | None = None) -> tuple[Screening, list[tuple[Idea, list[str]]]]:
    """Une seule réparation pour les idées refusées ; ce qui échoue encore est abandonné.
    Si la réparation ne peut pas avoir lieu (budget, refus), les idées valides du premier appel restent."""
    if not first.invalid:
        return Screening(), []
    rejected = [(idea, errors) for _, idea, errors in first.invalid]
    try:
        res = _ask(ctx, task="ideas.repair", system=prompts.ideas_system(), schema=IdeaBatch, app_id=env.app_id,
                   ref=f"ideas:{env.app_id}:{env.phone.id}", content=base + prompts.repair_order(rejected),
                   wait_for_budget=False)
    except Exception as e:  # noqa: BLE001 : la réparation est un bonus, elle ne fait pas perdre le premier appel
        log.warning("ideas.repair %s · %s : %s", env.app_id, env.phone.id, e)
        return Screening(), [(idea, errors + [f"réparation impossible ({e})"]) for idea, errors in rejected]
    fixed = list(res.data.ideas)[:len(first.invalid)]
    # Claude peut en rendre moins : les idées non rendues sont abandonnées plus bas.
    second = _screen([(pos, idea) for (pos, _, _), idea in zip(first.invalid, fixed, strict=False)],
                     env.check, index, extra)
    abandoned = [(idea, errors) for _, idea, errors in second.invalid]
    abandoned += [(idea, errors + ["non rendue par la réparation"]) for idea, errors in rejected[len(fixed):]]
    return second, abandoned


def _store_ideas(ctx: jobs.JobContext, env: AccountEnv, ideas: list[Idea], *, parent_id: str | None,
                 duplicates: list[tuple[Idea, str]], abandoned: list[tuple[Idea, list[str]]],
                 summary: str) -> list[str]:
    """Inscrit les idées, enfile leur production (si approuvées) et les événements, en une transaction."""
    conn = ctx.conn
    now = ctx.clock()
    status = store.new_idea_status(_settings(ctx))
    account = store.target_account(env.phone)
    with store.transaction(conn):
        existing = store.ideas_for_job(conn, ctx.job.id)
        if existing:                    # une autre exécution de cette tâche a déjà tout écrit
            return existing
        ids = store.insert_ideas(conn, app_id=env.app_id, strategy_id=env.strategy.id, phone=env.phone,
                                 ideas=ideas, status=status, now=now, job_id=ctx.job.id, parent_id=parent_id)
        if status == "approved":
            for idea_id in ids:
                store.enqueue_production(conn, idea_id, env.app_id, now, parent_job=ctx.job.id)
        for idea, twin in duplicates:
            store.add_event(conn, now, "ideas.duplicate",
                            f"{env.app_id} · {env.phone.id} : accroche écartée « {idea.hook} » "
                            f"(trop proche de « {twin} »)", account)
        for idea, errors in abandoned:
            store.add_event(conn, now, "ideas.abandoned",
                            f"{env.app_id} · {env.phone.id} : idée abandonnée « {idea.hook or idea.title} » : "
                            + " ; ".join(errors[:4]), account)
        store.add_event(conn, now, "ideas.generated", f"{env.app_id} · {env.phone.id} : {summary}", account)
    return ids


# --- ideas.generate ----------------------------------------------------------------------------------------

@jobs.handler("ideas.generate", lease_s=1500)
@_data_errors
def generate_ideas(ctx: jobs.JobContext, payload: dict) -> dict:
    """Les idées d'un téléphone : écrites dans sa voix, validées, dédoublonnées, réparées une fois."""
    app_id = _require(payload, "app_id")
    phone_id = _require(payload, "phone_id")
    settings = store.pipeline_settings(_settings(ctx))
    try:
        count = int(payload.get("count") or settings["ideas_per_batch"])
    except (TypeError, ValueError) as e:
        raise jobs.Permanent(f"count invalide : {payload.get('count')!r}") from e
    count = max(1, min(count, store.MAX_BATCH))
    done = store.ideas_for_job(ctx.conn, ctx.job.id)
    if done:
        return {"ideas": done, "reused": True}

    env = _account_env(ctx, app_id, phone_id)
    base = _context_text(ctx, env)
    today = ctx.clock().date().isoformat()
    res = _ask(ctx, task="ideas.generate", system=prompts.ideas_system(), schema=IdeaBatch, app_id=app_id,
               ref=f"ideas:{app_id}:{phone_id}",
               content=base + prompts.ideas_order(count=count, phone=env.phone, today=today))
    index = validate.HookIndex(env.used_hooks)
    first = _screen(list(enumerate(res.data.ideas[:count])), env.check, index)
    second, abandoned = _repair(ctx, env, base, first, index)
    valid = [idea for _, idea in first.valid + second.valid]
    duplicates = first.duplicates + second.duplicates
    summary = (f"{len(valid)} idée(s) sur {count} demandée(s)"
               + (f", {len(second.valid)} après réparation" if second.valid else "")
               + (f", {len(duplicates)} doublon(s) écarté(s)" if duplicates else "")
               + (f", {len(abandoned)} abandonnée(s)" if abandoned else ""))
    ids = _store_ideas(ctx, env, valid, parent_id=None, duplicates=duplicates, abandoned=abandoned, summary=summary)
    return {"ideas": ids, "status": store.new_idea_status(_settings(ctx)), "requested": count,
            "repaired": len(second.valid), "duplicates": len(duplicates), "abandoned": len(abandoned)}


# --- ideas.ensure_stock ---------------------------------------------------------------------------------------

@jobs.handler("ideas.ensure_stock", lease_s=120)
@_data_errors
def ensure_stock(ctx: jobs.JobContext, payload: dict) -> dict:
    """Pour chaque téléphone de l'app : stock = idées en cours + contenus non publiés + idées commandées ;
    s'il manque des vidéos par rapport à pipeline.stock_target, commande les idées (par lots bornés)."""
    app_id = _require(payload, "app_id")
    conn = ctx.conn
    app = store.require_app(conn, app_id)
    if app["status"] != "active":
        return {"skipped": f"app au statut « {app['status']} »"}
    strat = store.current_strategy(conn, app_id)
    if strat is None:
        return {"skipped": "aucune stratégie approuvée"}
    now = ctx.clock()
    if isinstance(ctx.services.get("llm"), llm.UnavailableLLM) or "llm" not in ctx.services:
        store.add_event_once(conn, now, "strategy.no_llm",
                             f"{app_id} : stock d'idées bas mais aucune clé Claude configurée")
        return {"skipped": "aucune clé Claude"}

    settings = store.pipeline_settings(_settings(ctx))
    bucket = store.hour_bucket(now)
    report: dict[str, dict] = {}
    for phone in accounts.phones_for_app(ctx.config, app_id):
        if not store.phone_accounts(phone):
            report[phone.id] = {"skipped": "aucun compte configuré"}
            continue
        stock = store.phone_stock(conn, app_id, phone.id)
        missing = max(0, settings["stock_target"] - stock["total"])
        entry = {**stock, "target": settings["stock_target"], "missing": missing}
        if missing and store.voice_for(strat.strategy, phone.id) is None:
            entry["skipped"] = "pas de voix dans la stratégie"
            store.add_event_once(conn, now, "strategy.voice_missing",
                                 f"{app_id} : la stratégie v{strat.version} n'a pas de voix pour {phone.id} "
                                 f"(relancer la stratégie)")
        elif missing:
            count = min(missing, settings["ideas_per_batch"])
            entry["enqueued"] = count
            entry["job_id"] = ctx.enqueue("ideas.generate", {"app_id": app_id, "phone_id": phone.id, "count": count},
                                          key=f"ideas.generate:{app_id}:{phone.id}:{bucket}", app_id=app_id)
        report[phone.id] = entry
    return {"phones": report}


# --- ideas.variations ------------------------------------------------------------------------------------------

@jobs.handler("ideas.variations", lease_s=1500)
@_data_errors
def make_variations(ctx: jobs.JobContext, payload: dict) -> dict:
    """Un gagnant → 3 variations pour le même compte : nouvelle accroche, nouvel angle, autre format."""
    content_id = _require(payload, "content_id")
    conn = ctx.conn
    existing = store.ideas_with_parent(conn, content_id)
    if existing:
        return {"ideas": existing, "reused": True}
    content = store.get_content(conn, content_id)
    if content is None:
        raise jobs.Permanent(f"contenu « {content_id} » introuvable")
    parent = store.get_idea(conn, content["idea_id"]) if content.get("idea_id") else None
    app_id = content.get("app_id") or (parent or {}).get("app_id")
    if not app_id:
        raise jobs.Permanent(f"contenu « {content_id} » sans app")
    phone = _winner_phone(ctx, app_id, content, parent)
    env = _account_env(ctx, app_id, phone.id)

    winner_hook = store.content_hook(content, parent)
    winner_format = (parent or {}).get("format") or content.get("format") or ""
    metrics = store.content_metrics(conn, content_id)
    winner = {
        "content_id": content_id, "phone_id": phone.id, "lang": content.get("lang") or phone.lang,
        "format": winner_format, "hook": winner_hook, "caption": content.get("caption") or "",
        "idee": (parent or {}).get("idea") or {"props": content.get("props") or {}},
        "vues": metrics["views"], "likes": metrics["likes"],
        "mediane_des_vues_du_compte": store.median_views(conn, store.phone_accounts(phone),
                                                          ctx.clock() - WINNERS_WINDOW),
    }
    base = _context_text(ctx, env)
    res = _ask(ctx, task="ideas.variations", system=prompts.ideas_system(), schema=IdeaBatch, app_id=app_id,
               ref=f"variations:{content_id}", content=base + prompts.variations_order(winner))

    def extra(pos: int, idea: Idea) -> list[str]:
        label = prompts.VARIATIONS[pos][0]
        errors = []
        if label in ("accroche", "angle") and validate.similar(idea.hook, winner_hook):
            errors.append(f"variation « {label} » : l'accroche doit être nouvelle (trop proche de celle du gagnant)")
        if label == "accroche" and winner_format in formats.CATALOG and idea.format != winner_format:
            errors.append(f"variation « accroche » : garder le format du gagnant ({winner_format})")
        if label == "format" and idea.format == winner_format:
            errors.append(f"variation « format » : changer de format (le gagnant est en {winner_format})")
        return errors

    # La variation « format » peut garder l'accroche gagnante : elle ne compte pas comme un doublon.
    index = validate.HookIndex(h for h in env.used_hooks if not validate.similar(h, winner_hook, 0.999))
    first = _screen(list(enumerate(res.data.ideas[:len(prompts.VARIATIONS)])), env.check, index, extra)
    second, abandoned = _repair(ctx, env, base + prompts.variations_order(winner), first, index, extra)
    valid = [_label(idea, pos) for pos, idea in sorted(first.valid + second.valid, key=lambda t: t[0])]
    duplicates = first.duplicates + second.duplicates
    ids = _store_ideas(ctx, env, valid, parent_id=content_id, duplicates=duplicates, abandoned=abandoned,
                       summary=f"{len(valid)} variation(s) du gagnant {content_id}")
    return {"ideas": ids, "parent_id": content_id, "duplicates": len(duplicates), "abandoned": len(abandoned)}


def _label(idea: Idea, position: int) -> Idea:
    return idea.model_copy(update={"title": f"Variation ({prompts.VARIATIONS[position][0]}) · {idea.title}"})


def _winner_phone(ctx: jobs.JobContext, app_id: str, content: dict, parent: dict | None):
    """Le téléphone du gagnant ; à défaut, un téléphone de l'app dans la même langue."""
    phone_id = (parent or {}).get("phone_id") or (content.get("account_id") or "").split(":")[0]
    phone = ctx.config.phone_by_id(phone_id) if phone_id else None
    if phone is not None and app_id in (phone.apps or []):
        return phone
    lang = content.get("lang") or (parent or {}).get("lang")
    for candidate in accounts.phones_for_app(ctx.config, app_id):
        if candidate.lang == lang:
            return candidate
    raise jobs.Permanent(f"{app_id} : aucun téléphone en « {lang} » pour décliner le gagnant {content.get('id')}")
