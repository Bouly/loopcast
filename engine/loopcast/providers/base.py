"""Contrat des générateurs IA (vidéo, image) : requêtes, interface commune, erreurs, contrôle des fichiers.

Ce que les autres modules utilisent (docs/architecture-pipeline.md, « Générateur vidéo ») :

    video = ctx.service("video")                  # le routeur (providers/router.py)
    est = video.estimate(req)                     # coût estimé en $ (pour costs.check_budget)
    handle = video.submit(req)                    # str : à garder (résultat de la tâche) pour reprendre
    st = video.poll(handle)                       # {"status": "queued|running|done|failed", "error", "progress"}
    path = video.download(handle, dest_dir)       # Path du .mp4, vérifié (taille, type, durée via ffprobe)
    video.cancel(handle)

En pratique, `production` n'appelle pas ces méthodes elle-même : elle enfile la tâche `video.generate`
(providers/tasks.py), qui s'occupe du budget, du sondage, des reprises et du registre des coûts.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

Quality = Literal["eco", "standard", "premium"]
QUALITIES: tuple[str, ...] = ("eco", "standard", "premium")      # du moins cher au plus cher
Aspect = Literal["9:16", "16:9", "1:1"]
STATUSES = ("queued", "running", "done", "failed")

# Taille de référence par format (le faux fournisseur rend à cette taille ; la production recadre le reste).
TARGET_SIZE = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}


# --- Requêtes --------------------------------------------------------------------------------------

class VideoRequest(BaseModel):
    """Un plan vidéo à générer. Les trois derniers champs sont des ajouts facultatifs au contrat.

    Un plan IA dure 10 s au plus (contrat de `strategy`). Si le modèle n'a que des durées fixes, on prend
    la plus proche au-dessus (la composition coupe) : la durée réelle est dans le résultat de la tâche."""
    prompt: str = Field(min_length=1, max_length=4000,
                        description="En anglais, précis : sujet, action, cadrage, lumière, style")
    duration_s: float = Field(gt=0, le=10)
    aspect: Aspect = "9:16"
    image_path: str | None = None            # image de départ → image→vidéo
    audio: bool = False                      # son natif (ambiance, voix) ; sinon muet
    quality: Quality = "standard"
    seed: int | None = None
    negative_prompt: str | None = None
    humans: bool = False                     # une personne réaliste à l'écran (UGC face caméra)
    lang: str | None = None                  # langue parlée quand audio=True (« fr », « en »)
    model: str | None = None                 # forcer un modèle du catalogue (essais, CLI)


class ImageRequest(BaseModel):
    """Une image (fond de carrousel, image de départ d'un plan vidéo)."""
    prompt: str = Field(min_length=1, max_length=4000)
    aspect: Aspect = "9:16"
    quality: Quality = "standard"
    seed: int | None = None
    negative_prompt: str | None = None
    image_path: str | None = None            # image de référence, pour les modèles qui savent retoucher
    model: str | None = None


Request = VideoRequest | ImageRequest


def parse_request(kind: str, raw: object) -> Request:
    """Valide la requête d'une tâche ; ValueError avec un message lisible sinon."""
    cls = VideoRequest if kind == "video" else ImageRequest
    try:
        return cls.model_validate(raw if raw is not None else {})
    except ValidationError as e:
        details = "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'requête'} : {err['msg']}"
                            for err in e.errors())
        raise ValueError(f"requête {kind} invalide : {details}") from e


# --- Interface commune --------------------------------------------------------------------------------

class VideoProvider(Protocol):
    """Un générateur vidéo. Le routeur en est un (il relaie vers le fournisseur du modèle choisi)."""
    name: str

    def estimate(self, req: VideoRequest) -> float: ...

    def submit(self, req: VideoRequest) -> str: ...

    def poll(self, handle: str) -> dict: ...

    def download(self, handle: str, dest_dir: Path) -> Path: ...

    def cancel(self, handle: str) -> None: ...


class ImageProvider(Protocol):
    """Pareil pour les images (en général plus rapide, mais par la même file d'attente)."""
    name: str

    def estimate(self, req: ImageRequest) -> float: ...

    def submit(self, req: ImageRequest) -> str: ...

    def poll(self, handle: str) -> dict: ...

    def download(self, handle: str, dest_dir: Path) -> Path: ...

    def cancel(self, handle: str) -> None: ...


def status(state: str, *, error: str | None = None, progress: float | None = None,
           retryable: bool | None = None, **extra) -> dict:
    """La réponse de poll() : status ∈ queued | running | done | failed."""
    assert state in STATUSES, state
    out = {"status": state, "error": error, "progress": progress}
    if retryable is not None:
        out["retryable"] = retryable
    out.update(extra)
    return out


# --- Erreurs -----------------------------------------------------------------------------------------

class ProviderError(Exception):
    """Le fournisseur a refusé ou raté la génération (ou rendu un fichier inutilisable).

    `retryable` : relancer le même modèle a une chance de marcher (panne passagère) ; sinon, il faut
    un autre modèle ou une autre requête (filtre de contenu, paramètre refusé, fichier hors format)."""

    def __init__(self, message: str, *, retryable: bool = False, code: str | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


class ProviderAuthError(ProviderError):
    """Clé absente ou refusée : inutile de réessayer tant qu'un humain n'a rien changé."""


class NoModel(Exception):
    """Aucun modèle du catalogue ne sait faire cette requête (durée, audio, image→vidéo…)."""


class OverBudget(Exception):
    """Aucun modèle permis ne passe sous les plafonds de budget : réessayer à `retry_at`."""

    def __init__(self, reason: str, retry_at: datetime | None):
        super().__init__(reason)
        self.reason = reason
        self.retry_at = retry_at


# --- Contrôle des fichiers reçus ---------------------------------------------------------------------

@dataclass
class MediaInfo:
    path: Path
    bytes: int
    width: int
    height: int
    duration_s: float | None = None
    has_audio: bool = False
    format: str = ""


def find_tool(name: str) -> str:
    """ffmpeg / ffprobe : dans le PATH, sinon aux emplacements Homebrew (launchd a un PATH réduit)."""
    for candidate in (shutil.which(name), f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if candidate and Path(candidate).exists():
            return candidate
    raise ProviderError(f"{name} introuvable : l'installer (brew install ffmpeg)")


def aspect_matches(width: int, height: int, aspect: str, tolerance: float = 0.04) -> bool:
    w, h = (int(x) for x in aspect.split(":"))
    return height > 0 and abs(width / height - w / h) <= tolerance * (w / h)


def probe_video(path: Path) -> MediaInfo:
    out = subprocess.run(
        [find_tool("ffprobe"), "-v", "error", "-show_entries",
         "format=duration,format_name:stream=codec_type,width,height,duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise ProviderError(f"vidéo illisible ({path.name}) : {out.stderr.strip()[:200]}", code="bad_output")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProviderError(f"aucune piste vidéo dans {path.name}", code="bad_output")
    fmt = data.get("format") or {}
    duration = fmt.get("duration") or video.get("duration")
    return MediaInfo(path=path, bytes=path.stat().st_size, width=int(video.get("width") or 0),
                     height=int(video.get("height") or 0), duration_s=float(duration) if duration else None,
                     has_audio=any(s.get("codec_type") == "audio" for s in streams),
                     format=fmt.get("format_name") or "")


def check_video(path: Path, *, duration_s: float | None = None, aspect: str | None = None,
                min_bytes: int = 10_000, max_bytes: int = 300_000_000) -> MediaInfo:
    """Taille, type (mp4), durée et format d'image : un fichier qui ne passe pas n'entre pas dans le pipeline."""
    size = path.stat().st_size
    if size < min_bytes:
        raise ProviderError(f"fichier trop petit ({size} octets) : génération probablement vide", code="bad_output")
    if size > max_bytes:
        raise ProviderError(f"fichier trop lourd ({size / 1e6:.0f} Mo > {max_bytes / 1e6:.0f} Mo)", code="bad_output")
    info = probe_video(path)
    if "mp4" not in info.format and "mov" not in info.format:
        raise ProviderError(f"type inattendu ({info.format}) : un mp4 était attendu", code="bad_output")
    if not info.duration_s or info.duration_s <= 0.3:
        raise ProviderError("durée nulle ou illisible", code="bad_output")
    if duration_s and abs(info.duration_s - duration_s) > max(1.0, 0.2 * duration_s):
        raise ProviderError(f"durée {info.duration_s:.1f} s au lieu de {duration_s:g} s", code="bad_output")
    if aspect and not aspect_matches(info.width, info.height, aspect):
        raise ProviderError(f"image {info.width}×{info.height} : le format {aspect} était demandé", code="bad_output")
    return info


def check_image(path: Path, *, aspect: str | None = None, min_bytes: int = 1_000,
                max_bytes: int = 50_000_000) -> MediaInfo:
    from PIL import Image, UnidentifiedImageError

    size = path.stat().st_size
    if not min_bytes <= size <= max_bytes:
        raise ProviderError(f"taille d'image anormale ({size} octets)", code="bad_output")
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height, fmt = img.width, img.height, (img.format or "").lower()
    except (UnidentifiedImageError, OSError) as e:
        raise ProviderError(f"image illisible ({path.name}) : {e}", code="bad_output") from e
    if aspect and not aspect_matches(width, height, aspect):
        raise ProviderError(f"image {width}×{height} : le format {aspect} était demandé", code="bad_output")
    return MediaInfo(path=path, bytes=size, width=width, height=height, format=fmt)
