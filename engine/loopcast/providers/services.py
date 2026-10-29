"""Branchement (modules.py) : services["video"] et services["image"], réels, faux (démo) ou indisponibles.

- mode démo (`serve --demo`, `worker --demo`, ou `providers.demo: true`) : faux fournisseur ;
- pas de clé fal.ai (FAL_KEY ou trousseau macOS « loopcast-fal ») : générateur INDISPONIBLE, jamais de bascule
  silencieuse sur le faux fournisseur (ses clips de test finiraient en validation, voire validés d'office en
  review_mode: auto). Chaque demande est refusée avec la raison (la tâche video.generate s'arrête en échec
  définitif, message en français), et /api/providers comme /api/status le disent ;
- catalogue mal écrit dans settings.yaml : générateur indisponible aussi, l'erreur est dans le message ;
- sinon fal.ai pour les modèles du catalogue (un modèle `provider: fake` reste servi par le faux).

Tant qu'aucun générateur vidéo réel n'est branché (hors démo), les formats « premium » du catalogue
(vidéo IA payante : ai-hook-demo, ugc-ai) sont désactivés : la stratégie ne les propose plus et une idée dans
l'un d'eux est refusée à la validation. Ils reviennent dès que la clé est là (au prochain démarrage).

Rien ici n'appelle le réseau : la clé n'est vérifiée qu'au premier appel réel.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from loopcast import formats
from loopcast.providers import catalog, fake, fal
from loopcast.providers.base import NoModel, ProviderAuthError
from loopcast.providers.router import Router

log = logging.getLogger(__name__)

PAID_COST_CLASS = "premium"          # formats qui exigent un générateur vidéo payant
_disabled_formats: set[str] = set()  # ceux que CE module a désactivés (et lui seul réactive)


class UnavailableRouter(Router):
    """Aucun générateur réel branché (hors démo) : chaque demande est refusée avec la raison, en clair.

    route() / estimate() lèvent NoModel (la tâche video.generate passe en échec définitif, l'estimation de
    /api/providers répond « ok: false » avec le message) ; submit(), poll(), download()… lèvent
    ProviderAuthError (une génération d'avant reprise après redémarrage s'arrête aussi, sans réessai)."""

    def __init__(self, kind: str, models: list, *, why: str, default_quality: str = "standard"):
        super().__init__(kind, models, {}, mode="unavailable", why=why, default_quality=default_quality)
        self.disabled_formats: list[str] = []

    @property
    def real(self) -> bool:
        return False

    def why_not(self, model, req) -> str | None:
        return self.why

    def backend_of(self, model_id: str) -> str:
        return "aucun"

    def route(self, req, *, fits=None, exclude=(), tiers=None):
        raise NoModel(self.why)

    def submit(self, req, *, model: str | None = None) -> str:
        raise ProviderAuthError(self.why)

    def poll(self, handle: str) -> dict:
        raise ProviderAuthError(self.why)

    def download(self, handle, dest_dir, *, name=None, expect=None):
        raise ProviderAuthError(self.why)

    def cancel(self, handle: str) -> None:
        raise ProviderAuthError(self.why)

    def cost(self, handle: str) -> float | None:
        raise ProviderAuthError(self.why)

    def describe(self) -> dict:
        return {**super().describe(), "available": False, "disabled_formats": list(self.disabled_formats)}


def build(config: Any, demo: bool = False) -> dict[str, Router]:
    settings = getattr(config, "settings", None) or {}
    pcfg = settings.get("providers") or {}
    demo = bool(demo or getattr(config, "demo", False) or pcfg.get("demo"))
    problem = None
    try:
        video_models, image_models = catalog.video_models(settings), catalog.image_models(settings)
    except catalog.CatalogError as e:
        log.error("providers : %s", e)
        problem = f"catalogue invalide dans settings.yaml ({e}) : corriger providers.<video|image>.models"
        video_models, image_models = catalog.video_models(), catalog.image_models()

    key, source = (None, "") if demo else fal.find_key(settings)
    vcfg, icfg = pcfg.get("video") or {}, pcfg.get("image") or {}
    if demo:
        mode, why = "fake", "mode démo : faux fournisseur (fichiers de test fabriqués sur le Mac, aucun appel payant)"
    elif problem or not key:
        reason = problem or ("aucune clé fal.ai (variable FAL_KEY ou trousseau macOS « loopcast-fal ») ; le faux "
                             "fournisseur ne sert qu'en démo (--demo)")
        out: dict[str, Router] = {}
        for kind, models, cfg in (("video", video_models, vcfg), ("image", image_models, icfg)):
            label = "vidéo" if kind == "video" else "d'image"
            out[kind] = UnavailableRouter(
                kind, models, why=f"génération {label} indisponible : {reason}. Ajouter la clé (ou corriger le "
                                  "réglage) puis redémarrer Loopcast.",
                default_quality=cfg.get("default_quality", "standard"))
        out["video"].disabled_formats = _paid_formats(enabled=False, why=out["video"].why)
        return out
    else:
        mode, why = "fal", f"fal.ai, clé lue dans : {source}"

    _paid_formats(enabled=True)
    fake_cfg = pcfg.get("fake") or {}
    fake_opts = {"delay_s": float(fake_cfg.get("delay_s", 0)), "fail_rate": float(fake_cfg.get("fail_rate", 0))}
    client = None
    if mode == "fal":
        fal_cfg = pcfg.get("fal") or {}
        client = fal.FalClient(key, base_url=fal_cfg.get("base_url") or fal.QUEUE_URL,
                               timeout_s=float(fal_cfg.get("timeout_s", 30)))
    max_bytes = int(float(vcfg.get("max_mb", 300)) * 1e6)

    def video_provider(model):
        if client is not None and model.provider == "fal":
            return fal.FalVideoProvider(model, client, max_bytes=max_bytes)
        return fake.FakeVideoProvider(model, **fake_opts)

    def image_provider(model):
        if client is not None and model.provider == "fal":
            return fal.FalImageProvider(model, client, max_bytes=50_000_000)
        return fake.FakeImageProvider(model, **fake_opts)

    return {
        "video": Router("video", video_models, {m.id: video_provider(m) for m in video_models}, mode=mode,
                        why=why, default_quality=vcfg.get("default_quality", "standard")),
        "image": Router("image", image_models, {m.id: image_provider(m) for m in image_models}, mode=mode,
                        why=why, default_quality=icfg.get("default_quality", "standard")),
    }


def _paid_formats(*, enabled: bool, why: str = "") -> list[str]:
    """Désactive (ou réactive) les formats premium du catalogue, sans toucher à formats.py : seuls ceux que ce
    module a désactivés sont réactivés. Renvoie les formats désactivés par ce module."""
    try:
        importlib.import_module("loopcast.production.formats_extra")      # enregistre les formats à plans
    except ImportError:
        pass
    if enabled:
        for format_id in sorted(_disabled_formats):
            spec = formats.CATALOG.get(format_id)
            if spec is not None:
                spec.enabled = True
        _disabled_formats.clear()
        return []
    for spec in formats.CATALOG.values():
        if spec.cost_class == PAID_COST_CLASS and spec.enabled:
            spec.enabled = False
            _disabled_formats.add(spec.id)
    if _disabled_formats:
        log.warning("providers : formats %s retirés du catalogue (%s)", ", ".join(sorted(_disabled_formats)), why)
    return sorted(_disabled_formats)
