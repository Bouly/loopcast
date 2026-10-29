"""Accès à Claude pour tout le pipeline : réponses validées par un schéma Pydantic, images, coût.

    llm = get_llm(config)
    res = llm.structured(task="app.analyze", system=SYSTEM, content=[...], schema=AnalysisResult)
    res.data        → AnalysisResult validé
    res.cost_usd    → coût de l'appel (inscrit au registre par record_cost)

Les tâches passent par `call_and_record` : l'appel, puis son coût au registre, même quand la réponse est
inutilisable (refus, réponse tronquée, sortie hors schéma) — Claude l'a facturée quand même ; l'usage et le
coût voyagent alors dans l'exception (`LLMError.result`).

Trois implémentations derrière la même interface :
- AnthropicLLM : le vrai Claude (SDK officiel `anthropic`), réponse en flux, sortie structurée,
  repli automatique côté serveur si le modèle refuse, cache du prompt système ;
- DemoLLM : réponses plausibles écrites par chaque module (mode --demo, sans clé) ;
- FakeLLM : réponses scriptées pour les tests.

Modèle et effort se règlent par tâche dans settings.yaml (`llm.tasks`) ; par défaut Claude Opus 5.5.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-5-5"

# Effort par tâche : la compréhension et la stratégie réfléchissent, la description d'une capture non.
DEFAULT_EFFORT = {
    "asset.describe": "low",
    "app.analyze": "high",
    "app.refine": "high",
    "strategy.generate": "high",
    "ideas.generate": "high",
    "ideas.repair": "medium",
    "ideas.variations": "high",
}

# $ par million de tokens : entrée, sortie, lecture du cache, écriture du cache (5 min = 1,25 × l'entrée).
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}

# Côté serveur : si le modèle décline (classifieurs de sécurité), l'API relance la même requête
# sur le modèle de repli adapté, dans le même appel.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """Échec d'un appel à Claude. `result` : l'usage et le coût de l'appel quand il a été facturé (refus,
    réponse tronquée, sortie absente ou hors schéma) ; None quand rien n'a été facturé (clé refusée,
    requête rejetée par l'API)."""

    def __init__(self, message: str = "", result: "LLMResult | None" = None):
        super().__init__(message)
        self.result = result


class LLMUnavailable(LLMError):
    """Pas de clé Claude : la tâche ne peut pas tourner (message clair dans le dashboard)."""


class LLMRefusal(LLMError):
    pass


@dataclass
class LLMRequest:
    task: str
    system: str
    content: list[dict]
    schema: type[BaseModel]
    model: str
    effort: str
    max_tokens: int


@dataclass
class LLMResult:
    data: Any
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    request_id: str | None = None
    stop_reason: str | None = None
    demo: bool = False


class LLM(Protocol):
    name: str

    def structured(self, *, task: str, system: str, content: list[dict] | str, schema: type[T],
                   max_tokens: int = 32000, model: str | None = None,
                   effort: str | None = None) -> LLMResult: ...


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def image_block(path: Path | str, max_side: int = 1568) -> dict:
    """Une image pour Claude, réduite à 1568 px de côté (au-delà, Claude la réduit de toute façon)."""
    from PIL import Image

    img = Image.open(path)
    img.load()
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img.convert("RGBA").save(buf, "PNG", optimize=True)
        media = "image/png"
    else:
        img.convert("RGB").save(buf, "JPEG", quality=88)
        media = "image/jpeg"
    return {"type": "image", "source": {"type": "base64", "media_type": media,
                                        "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def cost_of(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    p_in, p_out, p_read, p_write = PRICES.get(model, PRICES[DEFAULT_MODEL])
    return (input_tokens * p_in + output_tokens * p_out + cache_read * p_read + cache_write * p_write) / 1e6


def _task_settings(settings: dict, task: str) -> tuple[str, str]:
    llm = settings.get("llm") or {}
    per_task = (llm.get("tasks") or {}).get(task) or {}
    model = per_task.get("model") or llm.get("model") or DEFAULT_MODEL
    effort = per_task.get("effort") or DEFAULT_EFFORT.get(task, "medium")
    return model, effort


# --- Le vrai Claude ----------------------------------------------------------------------------------

class AnthropicLLM:
    name = "anthropic"

    def __init__(self, settings: dict | None = None, client: Any = None, api_key: str | None = None):
        self.settings = settings or {}
        if client is None:
            import anthropic

            timeout = float((self.settings.get("llm") or {}).get("timeout_s", 600))
            client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=timeout) if api_key \
                else anthropic.Anthropic(max_retries=3, timeout=timeout)
        self.client = client

    def structured(self, *, task: str, system: str, content: list[dict] | str, schema: type[T],
                   max_tokens: int = 32000, model: str | None = None, effort: str | None = None) -> LLMResult:
        import anthropic

        cfg_model, cfg_effort = _task_settings(self.settings, task)
        model = model or cfg_model
        effort = effort or cfg_effort
        blocks = [text_block(content)] if isinstance(content, str) else content
        try:
            with self.client.beta.messages.stream(
                model=model,
                max_tokens=max_tokens,
                # Le prompt système (consignes + savoir-faire) est stable : mis en cache.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": blocks}],
                # Le schéma part dans output_config.format, exactement ce que le SDK envoie pour output_format ;
                # mais c'est nous qui lisons la réponse, une fois le flux fini. Avec output_format, le SDK la
                # valide au milieu du flux : une réponse tronquée ou hors schéma lève une erreur de pydantic
                # avant que l'usage soit connu, et l'appel, facturé, ne pourrait plus être inscrit au registre.
                output_config={"effort": effort, "format": output_format(schema)},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise LLMUnavailable("clé Claude refusée : vérifier ANTHROPIC_API_KEY") from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"requête refusée par l'API : {e.message}") from e
        # Les autres erreurs (429, 5xx, réseau) remontent telles quelles : la file de tâches réessaie.

        res = _billed(msg, model)            # l'appel est facturé, que la réponse serve ou non
        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            raise LLMRefusal(f"Claude a décliné ({getattr(details, 'category', None) or 'sans catégorie'})",
                             result=res)
        if msg.stop_reason == "max_tokens":
            raise LLMError(f"réponse tronquée à {max_tokens} tokens ({task}) : augmenter max_tokens", result=res)
        data, why = _parse(msg, schema)
        if data is None:
            raise LLMError(f"réponse sans sortie structurée valide ({task}, stop={msg.stop_reason}) : {why}",
                           result=res)
        res.data = data
        return res


def output_format(schema: type[BaseModel]) -> dict:
    """Le format JSON demandé à Claude, construit comme le fait le SDK pour `output_format` : schéma de pydantic
    transformé pour l'API (anthropic.transform_schema)."""
    import anthropic
    from pydantic import TypeAdapter

    return {"type": "json_schema", "schema": anthropic.transform_schema(TypeAdapter(schema).json_schema())}


def _billed(msg: Any, model: str) -> LLMResult:
    """L'usage d'une réponse et son coût ; `data` reste vide tant que la réponse n'est pas validée."""
    u = getattr(msg, "usage", None)
    served_by = getattr(msg, "model", None) or model
    in_t, out_t = getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0
    c_read = getattr(u, "cache_read_input_tokens", 0) or 0
    c_write = getattr(u, "cache_creation_input_tokens", 0) or 0
    return LLMResult(
        data=None, model=served_by, input_tokens=in_t, output_tokens=out_t,
        cache_read_tokens=c_read, cache_write_tokens=c_write,
        cost_usd=cost_of(served_by, in_t, out_t, c_read, c_write),
        request_id=getattr(msg, "_request_id", None), stop_reason=getattr(msg, "stop_reason", None),
    )


def _parse(msg: Any, schema: type[BaseModel]) -> tuple[Any, str]:
    """La sortie structurée : déjà lue par le client (faux clients des tests), sinon le premier bloc de texte
    conforme au schéma, validé comme le fait le SDK. Renvoie (données, "") ou (None, la raison)."""
    from pydantic import TypeAdapter

    parsed = getattr(msg, "parsed_output", None)
    if parsed is not None:
        return parsed, ""
    why = "aucun bloc de texte"
    adapter = TypeAdapter(schema)
    for block in getattr(msg, "content", None) or []:
        if getattr(block, "type", None) != "text":
            continue
        try:
            return adapter.validate_json(block.text), ""
        except ValueError as e:              # pydantic.ValidationError (JSON invalide compris)
            why = str(e).splitlines()[0]
    return None, why


# --- Démo et tests -------------------------------------------------------------------------------------

DemoResponder = Callable[[LLMRequest], BaseModel]
DEMO_RESPONDERS: dict[str, DemoResponder] = {}


def demo_responder(task: str):
    """Chaque module enregistre une réponse plausible par tâche, pour le mode démo (sans clé)."""

    def deco(fn: DemoResponder) -> DemoResponder:
        DEMO_RESPONDERS[task] = fn
        return fn

    return deco


class FakeLLM:
    """Réponses scriptées : FakeLLM({"app.analyze": lambda req: AnalysisResult(...)}). Garde les appels."""
    name = "fake"

    def __init__(self, responders: dict[str, DemoResponder] | None = None, cost_usd: float = 0.01,
                 settings: dict | None = None):
        self.responders = dict(responders or {})
        self.cost_usd = cost_usd
        self.settings = settings or {}
        self.calls: list[LLMRequest] = []

    def structured(self, *, task: str, system: str, content: list[dict] | str, schema: type[T],
                   max_tokens: int = 32000, model: str | None = None, effort: str | None = None) -> LLMResult:
        cfg_model, cfg_effort = _task_settings(self.settings, task)
        req = LLMRequest(task, system, [text_block(content)] if isinstance(content, str) else content,
                         schema, model or cfg_model, effort or cfg_effort, max_tokens)
        self.calls.append(req)
        fn = self.responders.get(task)
        if fn is None:
            raise LLMError(f"FakeLLM : aucune réponse prévue pour « {task} »")
        out = fn(req)
        data = out if isinstance(out, BaseModel) else schema.model_validate(out)
        if not isinstance(data, schema):
            data = schema.model_validate(data.model_dump())
        return LLMResult(data=data, model=req.model, input_tokens=1000, output_tokens=500,
                         cost_usd=self.cost_usd, stop_reason="end_turn")


class DemoLLM(FakeLLM):
    """Le mode démo : les réponses enregistrées par les modules, coût nul, marquées « démo »."""
    name = "demo"

    def __init__(self, settings: dict | None = None):
        super().__init__(DEMO_RESPONDERS, cost_usd=0.0, settings=settings)

    def structured(self, **kw) -> LLMResult:
        res = super().structured(**kw)
        res.demo = True
        return res


class UnavailableLLM:
    name = "unavailable"

    def structured(self, **kw) -> LLMResult:
        raise LLMUnavailable("aucune clé Claude configurée : ajouter ANTHROPIC_API_KEY (ou le trousseau "
                             "macOS, service « loopcast-anthropic »), ou lancer en mode --demo")


# --- Choix de l'implémentation -----------------------------------------------------------------------

def keychain_secret(service: str) -> str | None:
    """Lit un secret dans le trousseau macOS (jamais dans git ni dans settings.yaml)."""
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def get_llm(config: Any, demo: bool | None = None) -> LLM:
    settings = getattr(config, "settings", None) or {}
    llm_cfg = settings.get("llm") or {}
    if demo if demo is not None else llm_cfg.get("demo"):
        return DemoLLM(settings)
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return AnthropicLLM(settings)
    key = keychain_secret(llm_cfg.get("keychain_service", "loopcast-anthropic"))
    if key:
        return AnthropicLLM(settings, api_key=key)
    if (Path.home() / ".config" / "anthropic").exists():      # profil `ant auth login`
        return AnthropicLLM(settings)
    return UnavailableLLM()


def record_cost(conn, res: LLMResult, *, at: datetime, task: str, app_id: str | None = None,
                job_id: int | None = None, ref: str | None = None, note: str | None = None) -> None:
    """Inscrit l'appel au registre des coûts (rien pour la démo)."""
    if res.demo:
        return
    from loopcast import costs

    costs.record(conn, at=at, provider="anthropic", kind="llm", cost_usd=res.cost_usd, app_id=app_id,
                 model=res.model, units=res.input_tokens + res.output_tokens, unit="tokens",
                 job_id=job_id, ref=ref, note=(note or task)[:300])


def call_and_record(llm: LLM, conn, *, clock: Callable[[], datetime], task: str, system: str,
                    content: list[dict] | str, schema: type[T], app_id: str | None = None,
                    job_id: int | None = None, ref: str | None = None, **options: Any) -> LLMResult:
    """Le passage obligé des tâches : l'appel à Claude, puis son coût au registre, succès comme échec.
    Un refus, une réponse tronquée ou hors schéma sont facturés : leur coût (porté par l'exception) est inscrit,
    puis l'erreur repart telle quelle vers l'appelant. `options` : max_tokens, model, effort."""
    try:
        res = llm.structured(task=task, system=system, content=content, schema=schema, **options)
    except LLMError as e:
        if e.result is not None:
            try:
                record_cost(conn, e.result, at=clock(), task=task, app_id=app_id, job_id=job_id, ref=ref,
                            note=f"{task} — réponse inutilisable : {e}")
            except Exception:  # noqa: BLE001 : c'est l'erreur de Claude qui doit remonter, pas celle du registre
                log.exception("%s : coût d'un appel en échec impossible à inscrire", task)
        raise
    record_cost(conn, res, at=clock(), task=task, app_id=app_id, job_id=job_id, ref=ref)
    return res
