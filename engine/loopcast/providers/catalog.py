"""Catalogue des modèles de génération (vidéo, image) : prix, capacités, paramètres d'appel.

Les prix et les modèles changent tous les mois : tout se règle dans settings.yaml, sans toucher au code.

    providers:
      video:
        models:                                  # fusionnés avec les défauts, par `id`
          - {id: h3-max-768p, usd_per_s: 0.06}   # nouveau prix
          - {id: seedance25-720p, enabled: true} # modèle fourni mais désactivé par défaut
          - {id: wan3-720p, rank: -1}            # préféré dans son niveau
          - id: mon-modele                       # ajout : tous les champs de VideoModel
            provider: fal
            tier: standard
            endpoint: owner/app/text-to-video
            usd_per_s: 0.05
            max_s: 10
        disabled: [kling3-pro]                   # retirer des modèles par défaut
        replace_defaults: false                  # true : seuls les modèles de settings.yaml
      image:
        models: [...]

Niveaux (`tier`) : eco < standard < premium. Dans un niveau, le routeur préfère le `rank` le plus bas
puis l'ordre du catalogue. Défauts relevés le 29/10/2026 sur les pages officielles de fal.ai
(`source` de chaque modèle) ; comparatif et recommandations : docs/fournisseurs-video.md.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from loopcast.providers.base import QUALITIES, ImageRequest, VideoRequest

VERIFIED = "2026-10-29"
PROVIDERS = ("fal", "fake")
ASPECTS = ("9:16", "16:9", "1:1")
FAL_PAGE = "https://fal.ai/models/"

# Noms des paramètres d'appel quand le modèle ne dit rien d'autre (None dans `params` : ne pas l'envoyer).
VIDEO_PARAMS = {"prompt": "prompt", "duration": "duration", "aspect_ratio": "aspect_ratio",
                "aspect_ratio_i2v": "aspect_ratio", "resolution": "resolution", "audio": "generate_audio",
                "image": "image_url", "seed": "seed", "negative_prompt": "negative_prompt"}
IMAGE_PARAMS = {"prompt": "prompt", "aspect_ratio": "aspect_ratio", "image_size": "image_size",
                "resolution": "resolution", "image": "image_url", "seed": "seed",
                "negative_prompt": "negative_prompt"}

# Taille demandée aux modèles qui prennent des pixels (multiples de 32 ; la production recadre en 1080×1920).
IMAGE_SIZES = {"9:16": (1088, 1920), "16:9": (1920, 1088), "1:1": (1440, 1440)}


class CatalogError(ValueError):
    """Un modèle mal décrit dans settings.yaml (message en français, affiché dans /api/providers)."""


def _fmt_seconds(d: float) -> str:
    return str(int(d)) if float(d).is_integer() else f"{d:g}"


# --- Modèles vidéo -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class VideoModel:
    id: str
    label: str
    provider: str                              # fal | fake
    tier: str                                  # eco | standard | premium
    endpoint: str | None                       # texte → vidéo (None : image→vidéo seulement)
    endpoint_i2v: str | None = None            # image → vidéo (None : pas d'image de départ)
    usd_per_s: float = 0.0                     # $ par seconde, muet (ou son compris si audio = always)
    usd_per_s_audio: float | None = None       # $ par seconde avec le son (None : même prix)
    usd_per_video: dict[float, float] = field(default_factory=dict)   # prix fixe par durée (remplace usd_per_s)
    durations: tuple[float, ...] = ()          # durées acceptées ; vide : toute durée de min_s à max_s
    min_s: float = 1.0
    max_s: float = 10.0
    duration_format: str = "{n}"               # "{n}" → "5", "{n}s" → "5s", "int" → 5, "float" → 5.0
    audio: str = "toggle"                      # none | toggle (paramètre) | always (bande-son toujours là)
    aspects: tuple[str, ...] = ASPECTS
    resolution: str | None = None              # valeur envoyée au paramètre de résolution (None : rien)
    humans: bool = False                       # réaliste pour des personnes (visages, mains, parole)
    voice_langs: tuple[str, ...] = ()          # langues parlées documentées (vide : non documenté)
    params: dict[str, str | None] = field(default_factory=dict)       # noms de paramètres qui diffèrent
    extra: dict[str, Any] = field(default_factory=dict)               # envoyés tels quels
    rank: int = 0                              # préférence dans le niveau (plus bas = préféré)
    enabled: bool = True
    source: str = ""                           # page de prix consultée
    verified: str = ""                         # date du relevé
    notes: str = ""

    kind = "video"

    def param(self, name: str) -> str | None:
        return self.params[name] if name in self.params else VIDEO_PARAMS[name]

    def billed_duration(self, seconds: float) -> float | None:
        """La durée qu'on demandera (et paiera) pour avoir au moins `seconds` ; None si impossible."""
        allowed = sorted(self.durations or self.usd_per_video)
        if allowed:
            return next((float(d) for d in allowed if d >= seconds - 0.05), None)
        if self.duration_format == "float":
            d = round(max(seconds, self.min_s), 1)
        else:                                   # durées entières : on arrondit au-dessus
            d = float(max(math.ceil(seconds - 0.05), math.ceil(self.min_s)))
        return d if d <= self.max_s + 1e-9 else None

    def durations_label(self) -> str:
        allowed = sorted(self.durations or self.usd_per_video)
        if allowed:
            return " / ".join(_fmt_seconds(d) for d in allowed) + " s"
        return f"{_fmt_seconds(self.min_s)} à {_fmt_seconds(self.max_s)} s"

    def supports(self, req: VideoRequest) -> str | None:
        """None si le modèle sait faire ce plan, sinon la raison (pour l'API et les messages)."""
        if not self.enabled:
            return "désactivé"
        if req.image_path and not self.endpoint_i2v:
            return "pas d'image→vidéo"
        if not req.image_path and not self.endpoint:
            return "image→vidéo seulement"
        if req.aspect not in self.aspects:
            return f"pas de format {req.aspect}"
        if self.billed_duration(req.duration_s) is None:
            return f"durée {req.duration_s:g} s impossible ({self.durations_label()})"
        if req.audio and self.audio == "none":
            return "pas de son"
        if req.humans and not self.humans:
            return "pas fait pour des personnes réalistes"
        if req.audio and req.humans and req.lang and self.voice_langs and req.lang not in self.voice_langs:
            return f"ne parle pas « {req.lang} » ({', '.join(self.voice_langs)})"
        return None

    def price(self, req: VideoRequest) -> float:
        """Prix catalogue du plan, en $ (pour la durée facturée, son compris si demandé)."""
        d = self.billed_duration(req.duration_s)
        if d is None:
            raise ValueError(f"{self.id} : durée {req.duration_s:g} s impossible")
        if self.usd_per_video:
            return round(self.usd_per_video[min(k for k in self.usd_per_video if k >= d)], 4)
        rate = self.usd_per_s
        if req.audio and self.audio == "toggle" and self.usd_per_s_audio is not None:
            rate = self.usd_per_s_audio
        return round(rate * d, 4)

    def inputs(self, req: VideoRequest, image_url: str | None = None) -> dict:
        """Le corps JSON de l'appel (noms et formats propres à chaque modèle)."""
        p = self.param
        body: dict[str, Any] = {p("prompt"): req.prompt}
        d = self.billed_duration(req.duration_s)
        if p("duration") and d is not None:
            body[p("duration")] = _duration_value(d, self.duration_format)
        aspect = p("aspect_ratio_i2v") if image_url else p("aspect_ratio")
        if aspect:
            body[aspect] = req.aspect
        if self.resolution and p("resolution"):
            body[p("resolution")] = self.resolution
        if self.audio == "toggle" and p("audio"):
            body[p("audio")] = bool(req.audio)
        if req.seed is not None and p("seed"):
            body[p("seed")] = req.seed
        if req.negative_prompt and p("negative_prompt"):
            body[p("negative_prompt")] = req.negative_prompt
        if image_url:
            body[p("image")] = image_url
        body.update(self.extra)
        return body

    def sample_prices(self) -> dict[str, float | None]:
        """Coût d'un plan de 5 s et de 10 s, muet et avec le son (None : impossible)."""
        out: dict[str, float | None] = {}
        for seconds in (5, 10):
            for audio in (False, True):
                req = VideoRequest(prompt="x", duration_s=seconds, audio=audio,
                                   aspect="9:16" if "9:16" in self.aspects else self.aspects[0])
                ok = self.billed_duration(seconds) is not None and not (audio and self.audio == "none")
                out[f"{seconds}s{'_audio' if audio else ''}"] = self.price(req) if ok else None
        return out


def _duration_value(d: float, fmt: str) -> Any:
    if fmt == "int":
        return int(round(d))
    if fmt == "float":
        return float(d)
    return fmt.replace("{n}", _fmt_seconds(d))


# --- Modèles image ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ImageModel:
    id: str
    label: str
    provider: str
    tier: str
    endpoint: str | None                       # texte → image
    endpoint_edit: str | None = None           # à partir d'une image de référence
    usd_per_image: float = 0.0
    usd_per_mp: float = 0.0                    # $ par mégapixel entamé (1 Mpx = 1024 × 1024)
    size_param: str = "aspect_ratio"           # aspect_ratio ("9:16") | image_size ({width, height})
    resolution: str | None = None
    aspects: tuple[str, ...] = ASPECTS
    params: dict[str, str | None] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    rank: int = 0
    enabled: bool = True
    source: str = ""
    verified: str = ""
    notes: str = ""

    kind = "image"

    def param(self, name: str) -> str | None:
        return self.params[name] if name in self.params else IMAGE_PARAMS[name]

    def supports(self, req: ImageRequest) -> str | None:
        if not self.enabled:
            return "désactivé"
        if req.image_path and not self.endpoint_edit:
            return "ne part pas d'une image"
        if not req.image_path and not self.endpoint:
            return "retouche seulement"
        if req.aspect not in self.aspects:
            return f"pas de format {req.aspect}"
        return None

    def price(self, req: ImageRequest) -> float:
        w, h = IMAGE_SIZES[req.aspect]
        return round(self.usd_per_image + self.usd_per_mp * math.ceil(w * h / 1024 ** 2), 4)

    def inputs(self, req: ImageRequest, image_url: str | None = None) -> dict:
        p = self.param
        body: dict[str, Any] = {p("prompt"): req.prompt}
        size = p(self.size_param)
        if size and self.size_param == "image_size":
            w, h = IMAGE_SIZES[req.aspect]
            body[size] = {"width": w, "height": h}
        elif size:
            body[size] = req.aspect
        if self.resolution and p("resolution"):
            body[p("resolution")] = self.resolution
        if req.seed is not None and p("seed"):
            body[p("seed")] = req.seed
        if req.negative_prompt and p("negative_prompt"):
            body[p("negative_prompt")] = req.negative_prompt
        if image_url:
            body[p("image")] = image_url
        body.update(self.extra)
        return body

    def sample_prices(self) -> dict[str, float | None]:
        return {"9:16": self.price(ImageRequest(prompt="x", aspect="9:16"))}


# --- Défauts (relevés le 29/10/2026, pages officielles fal.ai) ----------------------------------------

H3_LANGS = ("fr", "en", "es", "de", "it", "pt", "ru", "ar", "zh", "ja", "ko")   # minimax.io, 03/08/2026
H3_PARAMS = {"negative_prompt": None, "audio": None, "aspect_ratio_i2v": None}
KLING_PARAMS = {"seed": None, "image": "start_image_url", "aspect_ratio_i2v": None}
WAN_PARAMS = {"audio": "audio", "image": "start_image_url", "negative_prompt": None}
SEEDANCE_PARAMS = {"seed": None, "negative_prompt": None}
PROMO = "prix normal ; {promo} $/s en promotion jusqu'au 31/10/2026"


def _page(endpoint: str) -> str:
    return FAL_PAGE + endpoint


DEFAULT_VIDEO_MODELS: list[VideoModel] = [
    # Éco : b-roll de remplissage, essais.
    VideoModel(
        id="h3-turbo-768p", label="MiniMax H3 Max Turbo (768p)", provider="fal", tier="eco",
        endpoint="minimax/h3-max-turbo/text-to-video", usd_per_s=0.04, min_s=1, max_s=15,
        duration_format="float", audio="always", resolution="768P", humans=True, voice_langs=H3_LANGS,
        params=H3_PARAMS, extra={"prompt_expansion_mode": "balanced"},
        source=_page("minimax/h3-max-turbo/text-to-video"), verified=VERIFIED,
        notes=PROMO.format(promo="0,026") + " ; bande-son native, sans option pour la couper ; "
              "pas d'image→vidéo documentée ; visages à juger au premier essai"),
    VideoModel(
        id="veo31-lite-720p", label="Google Veo 3.1 Lite (720p)", provider="fal", tier="eco",
        endpoint="fal-ai/veo3.1/lite", usd_per_s=0.03, usd_per_s_audio=0.05, durations=(4, 6, 8),
        duration_format="{n}s", aspects=("9:16", "16:9"), resolution="720p",
        source=_page("fal-ai/veo3.1/lite"), verified=VERIFIED,
        notes="image→vidéo annoncé mais endpoint non documenté ; qualité non classée"),
    # Standard : le cœur du volume (accroches b-roll, UGC face caméra).
    VideoModel(
        id="h3-max-768p", label="MiniMax H3 Max (768p)", provider="fal", tier="standard",
        endpoint="minimax/h3-max/text-to-video", endpoint_i2v="minimax/h3-max/image-to-video",
        usd_per_s=0.08, min_s=1, max_s=15, duration_format="float", audio="always", resolution="768P",
        humans=True, voice_langs=H3_LANGS, params=H3_PARAMS, extra={"prompt_expansion_mode": "balanced"},
        source=_page("minimax/h3-max/text-to-video"), verified=VERIFIED,
        notes=PROMO.format(promo="0,052") + " ; son stéréo natif, 11 langues parlées dont le français ; "
              "en image→vidéo, le format suit l'image"),
    VideoModel(
        id="wan3-720p", label="Alibaba Wan 3.0 (720p)", provider="fal", tier="standard",
        endpoint="alibaba/wan-3.0/text-to-video", endpoint_i2v="alibaba/wan-3.0/image-to-video",
        usd_per_s=0.10, min_s=2, max_s=30, duration_format="int", resolution="720p", humans=True,
        params=WAN_PARAMS, source=_page("alibaba/wan-3.0/text-to-video"), verified=VERIFIED,
        notes="son compris dans le prix ; langues parlées non documentées"),
    VideoModel(
        id="veo31-fast-1080p", label="Google Veo 3.1 Fast (1080p)", provider="fal", tier="standard",
        endpoint="fal-ai/veo3.1/fast", endpoint_i2v="fal-ai/veo3.1/fast/image-to-video",
        usd_per_s=0.10, usd_per_s_audio=0.15, durations=(4, 6, 8), duration_format="{n}s",
        aspects=("9:16", "16:9"), resolution="1080p", humans=True,
        source=_page("fal-ai/veo3.1/fast"), verified=VERIFIED,
        notes="1080p au prix du 720p ; image de départ ≥ 720p en 9:16 ou 16:9"),
    VideoModel(
        id="kling3-std", label="Kling 3.0 Standard", provider="fal", tier="standard",
        endpoint="fal-ai/kling-video/v3/standard/text-to-video",
        endpoint_i2v="fal-ai/kling-video/v3/standard/image-to-video",
        usd_per_s=0.084, usd_per_s_audio=0.126, min_s=3, max_s=15, humans=True, voice_langs=("zh", "en"),
        params=KLING_PARAMS, source=_page("fal-ai/kling-video/v3/standard/text-to-video"), verified=VERIFIED,
        notes="voix en chinois et en anglais seulement (le reste est traduit en anglais)"),
    # Premium : plans qui portent la vidéo (UGC soigné, démo produit).
    VideoModel(
        id="h3-max-1080p", label="MiniMax H3 Max (1080p)", provider="fal", tier="premium",
        endpoint="minimax/h3-max/text-to-video", endpoint_i2v="minimax/h3-max/image-to-video",
        usd_per_s=0.16, min_s=1, max_s=15, duration_format="float", audio="always", resolution="1080P",
        humans=True, voice_langs=H3_LANGS, params=H3_PARAMS, extra={"prompt_expansion_mode": "balanced"},
        source=_page("minimax/h3-max/text-to-video"), verified=VERIFIED,
        notes=PROMO.format(promo="0,104") + " ; 1080p = affinage d'un rendu 768p"),
    VideoModel(
        id="seedance2-720p", label="ByteDance Seedance 2.0 (720p)", provider="fal", tier="premium",
        endpoint="bytedance/seedance-2.0/text-to-video", endpoint_i2v="bytedance/seedance-2.0/image-to-video",
        usd_per_s=0.3034, min_s=4, max_s=15, resolution="720p", humans=True, params=SEEDANCE_PARAMS,
        source=_page("bytedance/seedance-2.0/text-to-video"), verified=VERIFIED,
        notes="son compris ; facturé au token (h × l × durée × 24 / 1024, 0,014 $ les 1000) ; "
              "n° 2 en image→vidéo (Artificial Analysis)"),
    VideoModel(
        id="wan3-1080p", label="Alibaba Wan 3.0 (1080p)", provider="fal", tier="premium",
        endpoint="alibaba/wan-3.0/text-to-video", endpoint_i2v="alibaba/wan-3.0/image-to-video",
        usd_per_s=0.20, min_s=2, max_s=30, duration_format="int", resolution="1080p", humans=True,
        params=WAN_PARAMS, source=_page("alibaba/wan-3.0/text-to-video"), verified=VERIFIED,
        notes="son compris ; n° 1 en texte→vidéo (Artificial Analysis)"),
    VideoModel(
        id="kling3-pro", label="Kling 3.0 Pro", provider="fal", tier="premium",
        endpoint="fal-ai/kling-video/v3/pro/text-to-video", endpoint_i2v="fal-ai/kling-video/v3/pro/image-to-video",
        usd_per_s=0.112, usd_per_s_audio=0.168, min_s=3, max_s=15, humans=True, voice_langs=("zh", "en"),
        params=KLING_PARAMS, source=_page("fal-ai/kling-video/v3/pro/text-to-video"), verified=VERIFIED,
        notes="voix en chinois et en anglais seulement"),
    VideoModel(
        id="veo31-1080p", label="Google Veo 3.1 (1080p)", provider="fal", tier="premium",
        endpoint="fal-ai/veo3.1", endpoint_i2v="fal-ai/veo3.1/image-to-video",
        usd_per_s=0.20, usd_per_s_audio=0.40, durations=(4, 6, 8), duration_format="{n}s",
        aspects=("9:16", "16:9"), resolution="1080p", humans=True,
        source=_page("fal-ai/veo3.1"), verified=VERIFIED, notes="le plus cher ; classé derrière H3, Wan 3.0, Seedance"),
    VideoModel(
        id="seedance25-720p", label="ByteDance Seedance 2.5 (720p, hébergé aux US)", provider="fal",
        tier="premium", endpoint="bytedance/seedance-2.5/us/text-to-video", usd_per_s=0.473, min_s=4, max_s=30,
        resolution="720p", humans=True, params=SEEDANCE_PARAMS, enabled=False,
        source=_page("bytedance/seedance-2.5/us/text-to-video"), verified=VERIFIED,
        notes="désactivé par défaut (cher) ; image→vidéo non documentée sur fal"),
]

DEFAULT_IMAGE_MODELS: list[ImageModel] = [
    ImageModel(
        id="z-image-turbo", label="Z-Image Turbo", provider="fal", tier="eco", endpoint="fal-ai/z-image/turbo",
        usd_per_mp=0.005, size_param="image_size", params={"negative_prompt": None},
        source=_page("fal-ai/z-image/turbo"), verified=VERIFIED, notes="0,005 $ par mégapixel"),
    ImageModel(
        id="nano-banana", label="Google Nano Banana (Gemini 2.5 Flash Image)", provider="fal", tier="standard",
        endpoint="fal-ai/nano-banana", usd_per_image=0.0398, params={"negative_prompt": None},
        extra={"num_images": 1}, source=_page("fal-ai/nano-banana"), verified=VERIFIED),
    ImageModel(
        id="flux2-pro", label="FLUX.2 [pro]", provider="fal", tier="standard", endpoint="fal-ai/flux-2-pro",
        usd_per_image=0.015, usd_per_mp=0.015, size_param="image_size", params={"negative_prompt": None},
        source=_page("fal-ai/flux-2-pro"), verified=VERIFIED,
        notes="0,03 $ le premier mégapixel puis 0,015 $ par mégapixel"),
    ImageModel(
        id="nano-banana-pro", label="Google Nano Banana Pro (1K)", provider="fal", tier="premium",
        endpoint="fal-ai/nano-banana-pro", usd_per_image=0.15, resolution="1K", params={"negative_prompt": None},
        extra={"num_images": 1}, source=_page("fal-ai/nano-banana-pro"), verified=VERIFIED,
        notes="4K au double du prix"),
]


# --- Chargement avec les surcharges de settings.yaml ---------------------------------------------------

def video_models(settings: dict | None = None) -> list[VideoModel]:
    return _load(VideoModel, DEFAULT_VIDEO_MODELS, _section(settings, "video"), "video")


def image_models(settings: dict | None = None) -> list[ImageModel]:
    return _load(ImageModel, DEFAULT_IMAGE_MODELS, _section(settings, "image"), "image")


def _section(settings: dict | None, kind: str) -> dict:
    return (((settings or {}).get("providers") or {}).get(kind) or {})


def _load(cls, defaults: list, cfg: dict, kind: str) -> list:
    names = {f.name for f in fields(cls)}
    merged: dict[str, dict] = {} if cfg.get("replace_defaults") else {m.id: asdict(m) for m in defaults}
    for raw in cfg.get("models") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            raise CatalogError(f"providers.{kind}.models : chaque modèle doit avoir un « id »")
        unknown = sorted(set(raw) - names)
        if unknown:
            raise CatalogError(f"providers.{kind}.models, modèle « {raw['id']} » : champ(s) inconnu(s) "
                               f"{', '.join(unknown)}")
        merged[raw["id"]] = {**merged.get(raw["id"], {}), **raw}
    for model_id in cfg.get("disabled") or []:
        if model_id in merged:
            merged[model_id]["enabled"] = False
    models = [_build(cls, data, kind) for data in merged.values()]
    order = {m.id: i for i, m in enumerate(models)}
    return sorted(models, key=lambda m: (QUALITIES.index(m.tier), m.rank, order[m.id]))


def _build(cls, data: dict, kind: str):
    where = f"providers.{kind}.models, modèle « {data.get('id')} »"
    for key in ("durations", "aspects", "voice_langs"):
        if key in data and data[key] is not None:
            data[key] = tuple(data[key])
    if "usd_per_video" in data:
        data["usd_per_video"] = {float(k): float(v) for k, v in (data["usd_per_video"] or {}).items()}
    try:
        model = cls(**data)
    except TypeError as e:
        raise CatalogError(f"{where} : champ obligatoire manquant ({e})") from e
    if "|" in model.id:
        raise CatalogError(f"{where} : « | » interdit dans un id")
    if model.tier not in QUALITIES:
        raise CatalogError(f"{where} : tier « {model.tier} » inconnu (eco, standard, premium)")
    if model.provider not in PROVIDERS:
        raise CatalogError(f"{where} : fournisseur « {model.provider} » non pris en charge ({', '.join(PROVIDERS)})")
    if not (model.endpoint or getattr(model, "endpoint_i2v", None) or getattr(model, "endpoint_edit", None)):
        raise CatalogError(f"{where} : aucun endpoint")
    if bad := [a for a in model.aspects if a not in ASPECTS]:
        raise CatalogError(f"{where} : format(s) inconnu(s) {', '.join(bad)}")
    prices = [getattr(model, k) for k in ("usd_per_s", "usd_per_s_audio", "usd_per_image", "usd_per_mp")
              if getattr(model, k, None) is not None]
    if any(not isinstance(p, (int, float)) or p < 0 for p in prices):
        raise CatalogError(f"{where} : prix invalide")
    if isinstance(model, VideoModel):
        if model.audio not in ("none", "toggle", "always"):
            raise CatalogError(f"{where} : audio « {model.audio} » inconnu (none, toggle, always)")
        if model.duration_format not in ("int", "float") and "{n}" not in model.duration_format:
            raise CatalogError(f"{where} : duration_format doit contenir {{n}}, ou valoir int / float")
    elif model.size_param not in ("aspect_ratio", "image_size"):
        raise CatalogError(f"{where} : size_param « {model.size_param} » inconnu (aspect_ratio, image_size)")
    return model


def find(models: list, model_id: str):
    return next((m for m in models if m.id == model_id), None)


def describe(model) -> dict:
    """Ce que l'API et la CLI montrent d'un modèle."""
    d = asdict(model)
    d["kind"] = model.kind
    d["prices"] = model.sample_prices()
    if isinstance(model, VideoModel):
        d["durations_label"] = model.durations_label()
        d["image_to_video"] = bool(model.endpoint_i2v)
        d["usd_per_video"] = {_fmt_seconds(k): v for k, v in model.usd_per_video.items()}
    return d
