"""Réglages du module (section `apps:` de settings.yaml), tous facultatifs."""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppsSettings:
    max_upload_mb: int = 500              # poids maximal d'un fichier envoyé (vidéos d'iPhone comprises)
    fetch_timeout_s: float = 20.0         # lecture d'une page (App Store, Google Play, site)
    max_page_bytes: int = 4_000_000       # au-delà, la page est tronquée (une fiche Google Play pèse ~1,2 Mo)
    max_source_chars: int = 20_000        # texte gardé par source
    analysis_images: int = 8              # captures montrées à Claude pendant l'analyse
    appstore_screenshots: int = 10        # captures App Store importées par pays si l'équipe n'en a pas fourni
    max_question_rounds: int = 3          # tours de questions au plus par analyse
    wait_inputs_minutes: int = 20         # l'analyse attend au plus ce temps les sources et captures en cours
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"


def apps_settings(config: Any) -> AppsSettings:
    raw = ((getattr(config, "settings", None) or {}).get("apps") or {})
    values: dict[str, Any] = {}
    for f in fields(AppsSettings):
        if f.name not in raw or raw[f.name] is None:
            continue
        default = getattr(AppsSettings, f.name)
        try:
            values[f.name] = type(default)(raw[f.name])
        except (TypeError, ValueError):
            log.warning("réglage apps.%s ignoré : valeur invalide %r", f.name, raw[f.name])
    return AppsSettings(**values)
