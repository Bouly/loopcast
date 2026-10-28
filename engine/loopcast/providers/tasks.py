"""Tâches video.generate et image.generate : budget → soumission → sondage → téléchargement → coût.

Payload  : {"content_id": "habitudo-fr-0007", "shot_index": 0, "request": {VideoRequest | ImageRequest}}
Résultat : {"path", "cost_usd", "model", "provider", "duration_s", …} ; le fichier est sous
           data/media/<content_id>/shot-NN.mp4 (image-NN.png pour une image).

Chaque passage est court ; entre deux, la tâche se rendort avec jobs.RetryLater en gardant son état dans
son résultat (`jobs.result`) :
- avant de soumettre : costs.check_budget avec l'estimation, plus ce qui est déjà en cours chez les
  fournisseurs ; si ça ne passe pas, un niveau de qualité en dessous ; sinon attente jusqu'au lendemain,
  avec un événement « providers.budget » ;
- après la soumission, l'identifiant de la génération est gardé : une reprise (plantage, redémarrage du
  Mac) sonde la même génération au lieu d'en payer une deuxième ;
- sondage à intervalle croissant, délai maximal ; un échec du fournisseur → nouvel essai (un autre modèle du
  même niveau s'il y en a un), puis abandon (`dead`) avec la raison ;
- téléchargement vérifié (taille, type, durée, format), puis costs.record du coût réel — l'estimation,
  marquée `estimated`, si le fournisseur ne le donne pas — une seule fois, même si la tâche est rejouée.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from loopcast import costs, jobs
from loopcast.providers.base import (NoModel, OverBudget, ProviderAuthError, ProviderError, Request,
                                     aspect_matches, check_image, parse_request, probe_video)

log = logging.getLogger(__name__)

KINDS = ("video", "image")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True)
class Options:
    """Réglages `providers.video.*` / `providers.image.*` (valeurs par défaut ci-dessous)."""
    poll_initial_s: float = 10.0          # premier sondage après la soumission
    poll_factor: float = 1.5              # intervalle × 1,5 à chaque sondage…
    poll_max_s: float = 60.0              # … jusqu'à 1 min
    max_wait_s: float = 1800.0            # au-delà : annulation et nouvel essai
    max_failures: int = 3                 # échecs du fournisseur avant abandon
    retry_backoff_s: tuple[float, ...] = (30.0, 120.0, 600.0)

    @classmethod
    def load(cls, config: Any, kind: str) -> "Options":
        raw = (((getattr(config, "settings", None) or {}).get("providers") or {}).get(kind) or {})
        base = cls() if kind == "video" else cls(poll_initial_s=3.0, poll_max_s=20.0, max_wait_s=600.0)
        values = {f.name: raw[f.name] for f in fields(cls) if f.name in raw}
        if "retry_backoff_s" in values:
            values["retry_backoff_s"] = tuple(float(x) for x in values["retry_backoff_s"]) or base.retry_backoff_s
        return replace(base, **values)


# --- Les tâches -------------------------------------------------------------------------------------------

@jobs.handler("video.generate", max_attempts=5)
def generate_video(ctx: jobs.JobContext, payload: dict) -> dict:
    return advance(ctx, "video", payload, stored_state(ctx))


@jobs.handler("image.generate", max_attempts=5)
def generate_image(ctx: jobs.JobContext, payload: dict) -> dict:
    return advance(ctx, "image", payload, stored_state(ctx))


def advance(ctx: jobs.JobContext, kind: str, payload: dict, state: dict) -> dict:
    """Un pas de la génération. Lève RetryLater (avec le nouvel état) tant que ce n'est pas fini."""
    content_id, shot_index = _target(payload)
    try:
        req = parse_request(kind, payload.get("request"))
    except ValueError as e:
        raise jobs.Permanent(str(e)) from e
    req = _resolve_image(ctx.config, req, check=not state.get("handle"))
    gen = ctx.service(kind)
    step = _Step(ctx, kind, gen, req, Options.load(ctx.config, kind), ctx.clock(),
                 f"{kind} {content_id}#{shot_index}")
    try:
        if not state.get("handle"):
            step.submit(state)
        try:
            st = gen.poll(state["handle"])
        except ProviderAuthError:
            raise
        except ProviderError as e:                  # identifiant illisible ou inconnu : on relance
            st = {"status": "failed", "error": str(e), "retryable": e.retryable}
        if st["status"] in ("queued", "running"):
            step.wait(state, st)
        if st["status"] == "failed":
            step.failed(state, st.get("error") or "échec sans détail", bool(st.get("retryable", True)))
        return step.finish(state, content_id, shot_index)
    except ProviderAuthError as e:
        raise jobs.Permanent(str(e)) from e


@dataclass
class _Step:
    ctx: jobs.JobContext
    kind: str
    gen: Any                      # le routeur
    req: Request
    opts: Options
    now: datetime
    label: str

    def submit(self, state: dict) -> None:
        settings = getattr(self.ctx.config, "settings", None) or {}
        inflight = inflight_usd(self.ctx.conn, exclude_job=self.ctx.job.id)

        def fits(estimate: float):
            return costs.check_budget(self.ctx.conn, settings, self.now, estimate + inflight,
                                      app_id=self.ctx.job.app_id)

        exclude = list(state.get("exclude") or [])       # après un échec : les modèles à ne pas reprendre
        tiers = [state["tier"]] if state.get("failures") and state.get("tier") else None
        try:
            route = self.gen.route(self.req, fits=fits, exclude=exclude, tiers=tiers)
        except NoModel as e:
            raise jobs.Permanent(str(e)) from e
        except OverBudget as e:
            retry_at = e.retry_at or self.now + timedelta(hours=1)
            if state.get("budget_wait_until") != jobs.iso(retry_at):
                _event(self.ctx, "providers.budget",
                       f"{self.label} en attente de budget jusqu'au {retry_at:%d/%m à %H:%M} UTC : {e.reason}")
            # Juste après la remise à zéro, étalé de quelques minutes pour ne pas tout relancer d'un coup.
            delay = max(60.0, (retry_at - self.now).total_seconds()) + 60 + (self.ctx.job.id or 0) % 300
            raise jobs.RetryLater(delay, f"budget : {e.reason}",
                                  result={**state, "budget_wait_until": jobs.iso(retry_at)}) from e
        if route.downgraded:
            _event(self.ctx, "providers.downgrade",
                   f"{self.label} : {route.wanted} → {route.tier} ({route.model.id}) — {route.reason}")
        try:
            handle = self.gen.submit(self.req, model=route.model.id)
        except ProviderAuthError:
            raise
        except ProviderError as e:                  # refus immédiat : paramètre, filtre de contenu…
            self.failed({**state, "model": route.model.id, "tier": route.tier}, str(e), e.retryable)
        new = {"handle": handle, "model": route.model.id, "provider": self.gen.backend_of(route.model.id),
               "tier": route.tier, "wanted": route.wanted, "downgraded": route.downgraded,
               "estimate_usd": route.estimate_usd, "list_usd": route.list_usd,
               "billed_duration_s": route.billed_duration_s, "submitted_at": jobs.iso(self.now), "polls": 0,
               **{k: state[k] for k in ("failures", "tried_models", "banned_models", "exclude", "errors")
                  if state.get(k)}}
        raise jobs.RetryLater(self.opts.poll_initial_s, f"soumis à {route.model.id}", result=new)

    def wait(self, state: dict, st: dict) -> None:
        waited = (self.now - datetime.fromisoformat(state["submitted_at"])).total_seconds()
        if waited > self.opts.max_wait_s:
            try:
                self.gen.cancel(state["handle"])
            except Exception as e:  # noqa: BLE001 : l'annulation est une politesse, pas une condition
                log.warning("annulation impossible (%s) : %s", state["handle"], e)
            self.failed(state, f"délai maximal dépassé ({self.opts.max_wait_s / 60:.0f} min, encore "
                               f"« {st['status']} »)", True)
        polls = int(state.get("polls") or 0) + 1
        delay = min(self.opts.poll_max_s, self.opts.poll_initial_s * self.opts.poll_factor ** polls)
        raise jobs.RetryLater(delay, f"{st['status']} chez {state['model']}",
                              result={**state, "polls": polls, "status": st["status"], "progress": st.get("progress"),
                                      "queue_position": st.get("queue_position")})

    def failed(self, state: dict, error: str, retryable: bool) -> None:
        """Échec du fournisseur : nouvel essai, de préférence avec un autre modèle du même niveau ; sinon le
        même si l'échec était passager ; sinon abandon. Au-delà de `max_failures` échecs : abandon."""
        model = state.get("model") or "?"
        failures = int(state.get("failures") or 0) + 1
        tried = list(dict.fromkeys([*(state.get("tried_models") or []), model]))
        banned = list(state.get("banned_models") or [])
        if not retryable and model not in banned:
            banned.append(model)                    # refus définitif : ne plus le lui redemander
        errors = (list(state.get("errors") or []) + [f"{model} : {error}"])[-5:]
        tier = state.get("tier")
        if failures >= self.opts.max_failures:
            self.give_up(f"{self.label} abandonné après {failures} échecs — dernier, {model} : {error}", errors)
        exclude = tried                             # d'abord un modèle pas encore essayé…
        nxt = self._alternative(exclude, tier)
        if nxt is None:
            exclude = banned                        # … sinon on retente ceux dont l'échec était passager
            nxt = self._alternative(exclude, tier)
        if nxt is None:
            self.give_up(f"{self.label} : {model} a échoué ({error}) et aucun autre modèle "
                         f"{tier or ''} ne convient".replace("  ", " "), errors)
        delay = self.opts.retry_backoff_s[min(failures - 1, len(self.opts.retry_backoff_s) - 1)]
        _event(self.ctx, "providers.retry", f"{self.label} : échec chez {model} ({error}) ; nouvel essai "
                                            f"avec {nxt.model.id} dans {delay:.0f} s")
        raise jobs.RetryLater(delay, f"échec chez {model} : {error}",
                              result={"failures": failures, "tried_models": tried, "banned_models": banned,
                                      "exclude": exclude, "errors": errors, "tier": tier})

    def _alternative(self, exclude: list[str], tier: str | None):
        try:
            return self.gen.route(self.req, exclude=exclude, tiers=[tier] if tier else None)
        except NoModel:
            return None

    def give_up(self, reason: str, errors: list[str]) -> None:
        # Une relance à la main (dashboard) repartira de zéro : on efface le compte des échecs.
        _save_state(self.ctx, {"errors": errors, "gave_up_at": jobs.iso(self.now), "reason": reason})
        raise jobs.Permanent(reason)

    def finish(self, state: dict, content_id: str, shot_index: int) -> dict:
        dest_dir = media_dir(self.ctx.config) / content_id
        name = f"{'shot' if self.kind == 'video' else 'image'}-{shot_index:02d}"
        expect = {"aspect": self.req.aspect, "duration_s": state.get("billed_duration_s")}
        try:
            path = self.gen.download(state["handle"], dest_dir, name=name, expect=expect)
        except ProviderAuthError:
            raise
        except ProviderError as e:                  # fichier inutilisable (durée, format, illisible, expiré)
            self.failed(state, f"fichier inutilisable : {e}", e.retryable)
        info = probe_video(path) if self.kind == "video" else check_image(path)
        actual = self.gen.cost(state["handle"])
        cost = float(actual) if actual is not None else float(state.get("estimate_usd") or 0.0)
        provider = state.get("provider") or self.gen.backend_of(state["model"])
        _record_once(self.ctx, self.kind, state, cost=cost, estimated=actual is None, provider=provider,
                     note=f"{content_id}#{shot_index}", now=self.now)
        result = {
            "path": str(path), "cost_usd": round(cost, 4), "estimated": actual is None,
            "model": state["model"], "provider": provider, "tier": state.get("tier"),
            "downgraded": bool(state.get("downgraded")), "retries": int(state.get("failures") or 0),
            "width": info.width, "height": info.height,
            "bytes": info.bytes, "ai_label": True,        # visages, voix ou scènes réalistes générés (REPRISE §3)
            "content_id": content_id, "shot_index": shot_index, "handle": state["handle"],
        }
        if self.kind == "video":
            result.update(duration_s=round(info.duration_s or 0.0, 2), has_audio=info.has_audio,
                          requested_duration_s=self.req.duration_s,
                          billed_duration_s=state.get("billed_duration_s"))
        return result


# --- Outils -------------------------------------------------------------------------------------------------

def stored_state(ctx: jobs.JobContext) -> dict:
    """L'état gardé par le dernier RetryLater (vide au premier passage)."""
    if not ctx.job.id:
        return {}
    row = ctx.conn.execute("SELECT result FROM jobs WHERE id=?", (ctx.job.id,)).fetchone()
    try:
        data = json.loads(row["result"]) if row and row["result"] else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _save_state(ctx: jobs.JobContext, state: dict) -> None:
    """Pour l'abandon seulement : Permanent n'emporte pas de résultat, on l'écrit nous-mêmes."""
    if ctx.job.id:
        ctx.conn.execute("UPDATE jobs SET result=? WHERE id=?", (json.dumps(state, ensure_ascii=False), ctx.job.id))


def inflight_usd(conn, *, exclude_job: int | None = None) -> float:
    """Ce qui est soumis chez les fournisseurs mais pas encore inscrit au registre des coûts."""
    total = 0.0
    rows = conn.execute("""SELECT id, result FROM jobs WHERE kind IN ('video.generate', 'image.generate')
                           AND status IN ('queued', 'running') AND result IS NOT NULL""")
    for r in rows:
        if r["id"] == exclude_job:
            continue
        try:
            state = json.loads(r["result"])
        except ValueError:
            continue
        if isinstance(state, dict) and state.get("handle"):
            total += float(state.get("estimate_usd") or 0.0)
    return round(total, 4)


def media_dir(config: Any) -> Path:
    return Path(getattr(config, "data_dir", None) or "data") / "media"


def _target(payload: dict) -> tuple[str, int]:
    content_id = str(payload.get("content_id") or "").strip()
    if not SAFE_ID.fullmatch(content_id):
        raise jobs.Permanent("content_id manquant ou invalide (lettres, chiffres, « . », « _ », « - »)")
    try:
        shot_index = int(payload.get("shot_index", 0))
    except (TypeError, ValueError) as e:
        raise jobs.Permanent("shot_index doit être un entier") from e
    if shot_index < 0:
        raise jobs.Permanent("shot_index doit être positif")
    return content_id, shot_index


def _resolve_image(config: Any, req: Request, *, check: bool) -> Request:
    """Chemin absolu de l'image de départ ; avant de soumettre, on vérifie qu'elle existe et qu'elle a le
    format du plan : plusieurs modèles (H3, Kling…) gardent les proportions de l'image, et une capture
    d'iPhone (9:19,5) donnerait une vidéo refusée au contrôle… mais payée. La production place la capture
    sur un fond au bon format avant d'enfiler la tâche."""
    if not req.image_path:
        return req
    path = Path(req.image_path)
    if not path.is_absolute():
        path = Path(getattr(config, "root", None) or ".") / path
    if check:
        if not path.is_file():
            raise jobs.Permanent(f"image de départ introuvable : {path}")
        try:
            with Image.open(path) as img:
                width, height = img.size
        except OSError as e:
            raise jobs.Permanent(f"image de départ illisible : {path} ({e})") from e
        if not aspect_matches(width, height, req.aspect):
            raise jobs.Permanent(f"image de départ {width}×{height} : le plan est en {req.aspect} ; fournir une "
                                 f"image {req.aspect} (capture posée sur un fond au bon format)")
    return req.model_copy(update={"image_path": str(path)})


def _ref(handle: str) -> str:
    """La référence inscrite au registre (l'identifiant fal.ai tel quel ; abrégé s'il est très long)."""
    if len(handle) <= 160:
        return handle
    return f"{handle.split('|')[0]}|sha1:{hashlib.sha1(handle.encode()).hexdigest()}"


def _record_once(ctx: jobs.JobContext, kind: str, state: dict, *, cost: float, estimated: bool, provider: str,
                 note: str, now: datetime) -> None:
    ref = _ref(state["handle"])
    if ctx.conn.execute("SELECT 1 FROM cost_ledger WHERE ref=? AND kind=?", (ref, kind)).fetchone():
        return                                   # déjà inscrit (tâche rejouée après un plantage)
    if provider == "fake" and cost == 0:
        return                                   # comme la démo de Claude : rien à inscrire
    units, unit = (state.get("billed_duration_s"), "seconds") if kind == "video" else (1, "images")
    costs.record(ctx.conn, at=now, provider=provider, kind=kind, cost_usd=cost, app_id=ctx.job.app_id,
                 model=state["model"], units=units, unit=unit, estimated=estimated, job_id=ctx.job.id or None,
                 ref=ref, note=note)


def _event(ctx: jobs.JobContext, kind: str, message: str) -> None:
    ctx.conn.execute("INSERT INTO events(at, kind, message) VALUES (?,?,?)", (jobs.iso(ctx.clock()), kind, message))


# --- Estimation avec le budget (API, CLI) et exécution sans la file (CLI) -------------------------------

def quote(conn, settings: dict, now: datetime, gen, req: Request, *, app_id: str | None = None) -> dict:
    """Le modèle choisi, son prix, ce que dit le budget aujourd'hui, et les autres modèles."""
    inflight = inflight_usd(conn)
    out: dict[str, Any] = {"kind": gen.kind, "mode": gen.mode, "real": gen.real, "why": gen.why,
                           "inflight_usd": inflight}
    out["alternatives"] = [
        {"id": m.id, "label": m.label, "tier": m.tier, "eligible": why is None, "why": why,
         "list_usd": m.price(req) if why is None else None} for m, why in gen.candidates(req)]
    try:
        best = gen.route(req)
    except NoModel as e:
        return {**out, "ok": False, "error": str(e)}
    out.update(ok=True, model=best.model.id, label=best.model.label, tier=best.tier,
               estimate_usd=best.estimate_usd, list_usd=best.list_usd, billed_duration_s=best.billed_duration_s)
    try:
        within = gen.route(req, fits=lambda est: costs.check_budget(conn, settings, now, est + inflight, app_id=app_id))
        out["budget"] = {"ok": True, "model": within.model.id, "tier": within.tier,
                         "downgraded": within.downgraded, "reason": within.reason}
    except OverBudget as e:
        out["budget"] = {"ok": False, "reason": e.reason, "retry_at": jobs.iso(e.retry_at) if e.retry_at else None}
    return out


def run_inline(conn, config: Any, services: dict, kind: str, payload: dict, *, app_id: str | None = None,
               clock: Callable = jobs.utcnow, sleep: Callable[[float], None] | None = None,
               on_wait: Callable[[str, dict], None] | None = None, poll_cap_s: float | None = None,
               max_sleep_s: float = 900.0) -> dict:
    """Exécute une génération dans ce processus, sans passer par la file (python -m loopcast providers test)."""
    sleep = sleep or time.sleep
    job = jobs.Job(id=0, kind=f"{kind}.generate", key=None, payload=payload, attempts=1, max_attempts=1,
                   app_id=app_id, parent_id=None)
    ctx = jobs.JobContext(conn=conn, config=config, job=job, clock=clock, services=services)
    state: dict = {}
    while True:
        try:
            return advance(ctx, kind, payload, state)
        except jobs.RetryLater as e:
            if e.result is not None:
                state = e.result
            if e.delay_s > max_sleep_s:
                raise RuntimeError(f"en attente : {e}") from e
            if on_wait:
                on_wait(str(e), state)
            sleep(min(e.delay_s, poll_cap_s) if poll_cap_s else e.delay_s)
