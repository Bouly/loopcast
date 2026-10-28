"""Routage : quel modèle pour ce plan, puis relais vers le fournisseur de ce modèle.

Le routeur est ce que les autres modules reçoivent (`services["video"]`, `services["image"]`) : il respecte
le contrat VideoProvider (estimate, submit, poll, download, cancel) et ajoute `route()`, que la tâche
`video.generate` appelle avec une fonction de budget.

Choix d'un modèle :
1. ne garder que ceux qui savent faire le plan (durée, format, son, image→vidéo, personne réaliste, langue) ;
2. dans le niveau demandé (eco < standard < premium) : le préféré (`rank`, puis ordre du catalogue) ; s'il
   ne passe pas sous le budget, les autres du niveau, du moins cher au plus cher ;
3. sinon un niveau en dessous (« descendre d'un niveau ») ; sinon OverBudget : la tâche attend le lendemain.

La durée demandée au modèle est la plus proche au-dessus parmi celles qu'il propose (la composition coupe).
L'identifiant renvoyé par submit() : « {modèle}|{identifiant chez le fournisseur} ».
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from loopcast.providers import catalog
from loopcast.providers.base import QUALITIES, NoModel, OverBudget, ProviderError


@dataclass
class Route:
    model: Any
    estimate_usd: float                  # ce qui sera facturé (0 avec le faux fournisseur)
    list_usd: float                      # prix catalogue
    tier: str
    wanted: str
    reason: str = ""                     # pourquoi un niveau en dessous, le cas échéant
    billed_duration_s: float | None = None

    @property
    def downgraded(self) -> bool:
        return QUALITIES.index(self.tier) < QUALITIES.index(self.wanted)


BudgetFn = Callable[[float], Any]        # estimation → costs.BudgetCheck (ok, reason, retry_at)


class Router:
    def __init__(self, kind: str, models: list, providers: dict[str, Any], *, mode: str, why: str,
                 default_quality: str = "standard", downgrade_levels: int = 1):
        self.kind = kind                         # video | image
        self.models = list(models)
        self.providers = providers               # id du modèle → son fournisseur (fal ou faux)
        self.mode = mode                         # fal | fake
        self.why = why                           # en clair, pour /api/providers
        self.default_quality = default_quality if default_quality in QUALITIES else "standard"
        self.downgrade_levels = downgrade_levels

    @property
    def name(self) -> str:
        return self.mode

    @property
    def real(self) -> bool:
        return self.mode != "fake"

    def backend_of(self, model_id: str) -> str:
        return getattr(self.providers.get(model_id), "name", "?")

    # --- choix du modèle --------------------------------------------------------------------------------

    def why_not(self, model, req) -> str | None:
        if model.id not in self.providers:
            return "aucun fournisseur branché"
        return model.supports(req)

    def candidates(self, req) -> list[tuple[Any, str | None]]:
        """Tous les modèles, avec la raison pour laquelle ils ne conviennent pas (None : ils conviennent)."""
        return [(m, self.why_not(m, req)) for m in self.models]

    def tiers_for(self, wanted: str) -> list[str]:
        i = QUALITIES.index(wanted)
        return [QUALITIES[j] for j in range(i, max(-1, i - self.downgrade_levels - 1), -1)]

    def charge(self, model, req) -> float:
        return float(self.providers[model.id].estimate(req))

    def route(self, req, *, fits: BudgetFn | None = None, exclude=(), tiers: list[str] | None = None) -> Route:
        """Le modèle à utiliser. `fits(estimation)` : le budget le permet-il ? `exclude` : modèles en échec.
        `tiers` : niveaux permis (par défaut, le niveau demandé puis un en dessous)."""
        wanted = req.quality or self.default_quality
        if req.model:
            forced = catalog.find(self.models, req.model)
            if forced is None:
                raise NoModel(f"modèle {self.kind} inconnu : {req.model}")
            if why := self.why_not(forced, req):
                raise NoModel(f"{forced.id} ne convient pas : {why}")
            wanted = forced.tier                     # un modèle imposé n'est jamais « descendu »
            pools = [(forced.tier, [forced])]
        else:
            levels = tiers or self.tiers_for(wanted)
            pools = [(t, [m for m in self.models
                          if m.tier == t and m.id not in exclude and self.why_not(m, req) is None]) for t in levels]
        refusals = []
        for tier, pool in pools:
            ordered = pool[:1] + sorted(pool[1:], key=lambda m: self.charge(m, req))
            for model in ordered:
                estimate = self.charge(model, req)
                check = fits(estimate) if fits else None
                if check is None or check.ok:
                    reason = ""
                    if tier != wanted:
                        reason = f"budget : {refusals[0].reason}" if refusals else f"aucun modèle {wanted} ne convient"
                    billed = model.billed_duration(req.duration_s) if self.kind == "video" else None
                    return Route(model, estimate, model.price(req), tier, wanted, reason, billed)
                refusals.append(check)
        if not refusals:
            raise NoModel(self._no_model(req, wanted, exclude, tiers))
        retry = [c.retry_at for c in refusals if getattr(c, "retry_at", None)]
        raise OverBudget(refusals[0].reason, min(retry) if retry else None)

    def _no_model(self, req, wanted: str, exclude, tiers: list[str] | None) -> str:
        levels = tiers or self.tiers_for(wanted)
        reasons = []
        for m in self.models:
            if m.tier in levels:
                why = "en échec" if m.id in exclude else self.why_not(m, req)
                if why:
                    reasons.append(f"{m.id} : {why}")
        head = f"aucun modèle {self.kind} ({' / '.join(levels)}) ne sait faire ce plan"
        return head + (" — " + " ; ".join(reasons[:6]) if reasons else "")

    # --- contrat VideoProvider / ImageProvider ------------------------------------------------------------

    def estimate(self, req) -> float:
        return self.route(req).estimate_usd

    def submit(self, req, *, model: str | None = None) -> str:
        model_id = model or self.route(req).model.id
        return f"{model_id}|{self._provider(model_id).submit(req)}"

    def poll(self, handle: str) -> dict:
        model_id, inner = self._split(handle)
        return self._provider(model_id).poll(inner)

    def download(self, handle: str, dest_dir: Path, *, name: str | None = None, expect: dict | None = None) -> Path:
        model_id, inner = self._split(handle)
        return self._provider(model_id).download(inner, Path(dest_dir), name=name, expect=expect)

    def cancel(self, handle: str) -> None:
        model_id, inner = self._split(handle)
        self._provider(model_id).cancel(inner)

    def cost(self, handle: str) -> float | None:
        """Coût réel s'il est connu (None : inscrire l'estimation)."""
        model_id, inner = self._split(handle)
        return self._provider(model_id).cost(inner)

    def model_of(self, handle: str):
        return catalog.find(self.models, self._split(handle)[0])

    def _split(self, handle: str) -> tuple[str, str]:
        model_id, sep, inner = handle.partition("|")
        if not sep:
            raise ProviderError(f"identifiant de génération invalide : {handle[:80]}")
        return model_id, inner

    def _provider(self, model_id: str):
        provider = self.providers.get(model_id)
        if provider is None:
            raise ProviderError(f"modèle {model_id} absent du catalogue actif")
        return provider

    # --- pour l'API et la CLI ------------------------------------------------------------------------------

    def describe(self) -> dict:
        return {
            "kind": self.kind, "mode": self.mode, "real": self.real, "why": self.why,
            "default_quality": self.default_quality, "catalog_verified": catalog.VERIFIED,
            "models": [{**catalog.describe(m), "served_by": self.backend_of(m.id)} for m in self.models],
        }
