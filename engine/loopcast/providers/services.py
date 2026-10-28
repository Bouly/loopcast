"""Branchement (modules.py) : services["video"] et services["image"], réels ou faux, et pourquoi.

- mode démo (`serve --demo`, `worker --demo`, ou `providers.demo: true`) : faux fournisseur ;
- pas de clé fal.ai (FAL_KEY ou trousseau macOS « loopcast-fal ») : faux fournisseur, et on le dit ;
- catalogue mal écrit dans settings.yaml : faux fournisseur (aucune dépense), l'erreur est affichée ;
- sinon fal.ai pour les modèles du catalogue (un modèle `provider: fake` reste servi par le faux).

Rien ici n'appelle le réseau : la clé n'est vérifiée qu'au premier appel réel.
"""

from __future__ import annotations

import logging
from typing import Any

from loopcast.providers import catalog, fake, fal
from loopcast.providers.router import Router

log = logging.getLogger(__name__)


def build(config: Any, demo: bool = False) -> dict[str, Router]:
    settings = getattr(config, "settings", None) or {}
    pcfg = settings.get("providers") or {}
    demo = bool(demo or pcfg.get("demo"))
    problem = None
    try:
        video_models, image_models = catalog.video_models(settings), catalog.image_models(settings)
    except catalog.CatalogError as e:
        log.error("providers : %s", e)
        problem = f"catalogue invalide dans settings.yaml ({e})"
        video_models, image_models = catalog.video_models(), catalog.image_models()

    key, source = (None, "") if demo else fal.find_key(settings)
    if demo:
        mode, why = "fake", "mode démo : faux fournisseur (fichiers de test fabriqués sur le Mac, aucun appel payant)"
    elif problem:
        mode, why = "fake", f"{problem} : faux fournisseur en attendant (aucune dépense)"
    elif not key:
        mode, why = "fake", ("aucune clé fal.ai (variable FAL_KEY ou trousseau macOS « loopcast-fal ») : "
                             "faux fournisseur, générations de test seulement")
    else:
        mode, why = "fal", f"fal.ai, clé lue dans : {source}"

    fake_cfg = pcfg.get("fake") or {}
    fake_opts = {"delay_s": float(fake_cfg.get("delay_s", 0)), "fail_rate": float(fake_cfg.get("fail_rate", 0))}
    client = None
    if mode == "fal":
        fal_cfg = pcfg.get("fal") or {}
        client = fal.FalClient(key, base_url=fal_cfg.get("base_url") or fal.QUEUE_URL,
                               timeout_s=float(fal_cfg.get("timeout_s", 30)))
    vcfg, icfg = pcfg.get("video") or {}, pcfg.get("image") or {}
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
