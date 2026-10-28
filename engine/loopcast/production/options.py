"""Réglages lus par le module production (settings.yaml), tous avec une valeur par défaut ici.

    pipeline.review_mode          manual | auto        (repli : review_mode à la racine, ancien emplacement)
    render.node                   « node »             binaire Node pour render/render.mjs
    render.remotion_browser       null                 Chrome headless existant (sinon Remotion télécharge le sien)
    render.timeout_s              900                  durée maximale d'un rendu, bundle compris (1700 au plus)
    production.ffmpeg / ffprobe   « ffmpeg » / « ffprobe »
    production.qa                 {min_duration_s: 6, max_duration_s: 60, max_mb: 50, black_min_s: 0.5,
                                   freeze_min_s: 4, silent_db: -45}
    production.video_quality      {ai_video: standard, ugc_avatar: premium}   qualité demandée au générateur
    production.poll_s             30                   attente entre deux regards sur les générations vidéo
    production.generation_timeout_h  24                au-delà, le contenu échoue (génération jamais terminée)
    production.max_auto_retries   1                    nouvelles tentatives automatiques après un échec transitoire
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

QA_DEFAULTS = {
    "min_duration_s": 6.0,
    "max_duration_s": 60.0,
    "max_mb": 50.0,
    "black_min_s": 0.5,       # un passage noir plus long fait échouer
    "freeze_min_s": 4.0,      # une image figée plus longue fait échouer (les fins tenues durent moins de 3 s)
    "silent_db": -45.0,       # en dessous (volume max), la piste audio est muette
}
QUALITY_DEFAULTS = {"ai_video": "standard", "ugc_avatar": "premium"}

# Où chercher les outils quand ils ne sont pas dans le PATH (launchd n'a qu'un PATH minimal).
_TOOL_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin", "~/.local/node/bin")


def _section(settings: dict, name: str) -> dict:
    value = (settings or {}).get(name)
    return value if isinstance(value, dict) else {}


def review_mode(settings: dict) -> str:
    mode = _section(settings, "pipeline").get("review_mode") or (settings or {}).get("review_mode") or "manual"
    return "auto" if str(mode).lower() == "auto" else "manual"


RENDER_TIMEOUT_MAX_S = 1700.0     # sous le bail de 1800 s des tâches de rendu (sinon la tâche serait reprise en double)


def render_timeout_s(settings: dict) -> float:
    return min(float(_section(settings, "render").get("timeout_s") or 900), RENDER_TIMEOUT_MAX_S)


def remotion_browser(settings: dict) -> str | None:
    return _section(settings, "render").get("remotion_browser") or None


def qa_limits(settings: dict) -> dict[str, float]:
    custom = _section(_section(settings, "production"), "qa")
    return {k: float(custom.get(k, v)) for k, v in QA_DEFAULTS.items()}


def video_quality(settings: dict, kind: str) -> str:
    custom = _section(_section(settings, "production"), "video_quality")
    return str(custom.get(kind) or QUALITY_DEFAULTS.get(kind, "standard"))


def poll_s(settings: dict) -> float:
    return float(_section(settings, "production").get("poll_s") or 30)


def generation_timeout_h(settings: dict) -> float:
    return float(_section(settings, "production").get("generation_timeout_h") or 24)


def max_auto_retries(settings: dict) -> int:
    value = _section(settings, "production").get("max_auto_retries")
    return 1 if value is None else max(0, int(value))


def tool(name: str, configured: Any = None) -> str | None:
    """Chemin d'un exécutable : réglage explicite, sinon PATH, sinon emplacements usuels du Mac."""
    if configured:
        path = shutil.which(str(configured)) or (str(configured) if Path(str(configured)).exists() else None)
        return path
    found = shutil.which(name)
    if found:
        return found
    for d in _TOOL_DIRS:
        candidate = Path(os.path.expanduser(d)) / name
        if candidate.exists():
            return str(candidate)
    return None


def node_bin(settings: dict) -> str | None:
    return tool("node", _section(settings, "render").get("node"))


def ffmpeg_bin(settings: dict | None = None) -> str | None:
    return tool("ffmpeg", _section(settings or {}, "production").get("ffmpeg"))


def ffprobe_bin(settings: dict | None = None) -> str | None:
    return tool("ffprobe", _section(settings or {}, "production").get("ffprobe"))
