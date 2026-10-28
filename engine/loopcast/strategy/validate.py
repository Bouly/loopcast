"""Contrôles automatiques : une idée (ou une stratégie) ne part en production que si elle tient debout.

Deux temps pour une idée :
- normalize_idea corrige ce qui n'est pas du contenu (téléphone visé, hashtags, chemins de fichiers
  que la production renseigne elle-même, label IA forcé quand il le faut) ;
- validate_idea liste ce que seul Claude peut corriger (format, limites de caractères, plans,
  captures, langue, chiffres non sourcés…).

Les messages sont en français : ils repartent tels quels vers Claude pour la réparation, et sont
montrés à l'équipe quand une idée est abandonnée.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable, Iterator

from loopcast import formats
from loopcast.schemas import AccountVoice, Idea, Shot, Strategy

# --- Limites ------------------------------------------------------------------------------------

MIN_TOTAL_S = 8.0           # durée totale d'un format à plans
MAX_TOTAL_S = 45.0
MIN_SHOT_S = 1.0
MAX_SHOT_S = 15.0
MAX_AI_SHOT_S = 10.0        # les générateurs vidéo rendent des plans de 5 à 10 s
MAX_HOOK = 90               # l'accroche doit se lire en 2 secondes
MAX_CAPTION = 2000          # sous les 2 200 caractères d'Instagram, hashtags compris
MAX_ON_SCREEN = 90
MAX_HASHTAGS = 8
DUP_WINDOW = 200            # accroches récentes de l'app comparées à chaque nouvelle
DUP_RATIO = 0.85            # au-delà, deux accroches normalisées sont des doublons
VOICE_RATIO = 0.7           # au-delà, deux voix (personnage) se ressemblent trop

AI_SHOTS = frozenset({"ai_video", "ugc_avatar"})
ASSET_SHOTS = frozenset({"app_screenshot", "app_recording"})
# Renseignés par la production (marque, langue, fichiers) : Claude ne les choisit pas.
PRODUCTION_KEYS = ("lang", "brand", "music")


# --- Contexte d'une idée ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssetRef:
    """Une capture (ou vidéo de démo) de l'app, vue par la validation."""
    id: int
    kind: str                       # screenshot | demo_video | other
    mime: str = ""
    usable: bool | None = None      # None : pas encore analysée par Claude
    caution: str = ""

    @property
    def is_video(self) -> bool:
        return self.kind == "demo_video" or self.mime.startswith("video/")

    @property
    def is_image(self) -> bool:
        return not self.is_video and self.kind not in ("document", "logo")


@dataclass
class IdeaContext:
    """Ce qu'il faut savoir pour juger une idée : le compte visé, ses captures, la fiche."""
    lang: str
    phone_id: str
    assets: dict[int, AssetRef] = field(default_factory=dict)
    pillars: list[str] = field(default_factory=list)
    do_not_say: list[str] = field(default_factory=list)
    sources: str = ""               # textes de la fiche : les chiffres qu'ils contiennent sont permis

    @property
    def usable_images(self) -> list[int]:
        return [a.id for a in self.assets.values() if a.is_image and a.usable]

    @property
    def usable_videos(self) -> list[int]:
        return [a.id for a in self.assets.values() if a.is_video and a.usable]


# --- Texte : normalisation, doublons ---------------------------------------------------------------

def fold(text: str) -> str:
    """Minuscules, sans accents, sans ponctuation ni emoji, espaces simples."""
    text = unicodedata.normalize("NFKD", (text or "").replace("**", "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


class HookIndex:
    """Les accroches déjà prises : find() renvoie celle dont une nouvelle est trop proche."""

    def __init__(self, hooks: Iterable[str] = (), ratio: float = DUP_RATIO):
        self.ratio = ratio
        self._items: list[tuple[str, str]] = []
        for hook in hooks:
            self.add(hook)

    def add(self, hook: str) -> None:
        key = fold(hook)
        if key:
            self._items.append((key, hook))

    def find(self, hook: str) -> str | None:
        key = fold(hook)
        if not key:
            return None
        matcher = difflib.SequenceMatcher(None, "", key, autojunk=False)
        for other, original in self._items:
            if other == key:
                return original
            matcher.set_seq1(other)
            if (matcher.real_quick_ratio() >= self.ratio and matcher.quick_ratio() >= self.ratio
                    and matcher.ratio() >= self.ratio):
                return original
        return None

    def __len__(self) -> int:
        return len(self._items)


def similar(a: str, b: str, ratio: float = DUP_RATIO) -> bool:
    return HookIndex([a], ratio).find(b) is not None


def normalize_hashtags(tags: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        word = re.sub(r"[^\w]", "", str(tag or ""))
        if word and word.lower() not in seen:
            seen.add(word.lower())
            out.append(f"#{word}")
    return out[:MAX_HASHTAGS]


_TRAILING_TAGS = re.compile(r"(?:\s*#\w+)+\s*$")


def split_trailing_hashtags(caption: str) -> tuple[str, list[str]]:
    """« Légende #a #b » → (« Légende », [#a, #b]) : les hashtags vont dans leur champ."""
    m = _TRAILING_TAGS.search(caption)
    if not m or m.start() == 0:
        return caption, []
    return caption[:m.start()].rstrip(), re.findall(r"#\w+", m.group(0))


def match_pillar(name: str, pillars: list[str]) -> str:
    """Rattache un pilier mal orthographié au pilier de la stratégie le plus proche."""
    name = " ".join((name or "").split())
    if not pillars or name in pillars:
        return name
    by_key = {fold(p): p for p in pillars}
    if fold(name) in by_key:
        return by_key[fold(name)]
    close = difflib.get_close_matches(fold(name), list(by_key), n=1, cutoff=0.6)
    return by_key[close[0]] if close else name


_FR_CHARS = set("éèêëàâçùûôîïœ")
_FR_WORDS = {"une", "des", "les", "dans", "avec", "sur", "pour", "qui", "est", "sont", "elle",
             "il", "le", "la", "du", "au", "et", "un", "de"}


def looks_french(text: str) -> bool:
    """Heuristique : les prompts des générateurs vidéo doivent être en anglais."""
    low = text.lower()
    words = re.findall(r"[a-zà-ÿœ']+", low)
    if sum(c in _FR_CHARS for c in low) >= 3:
        return True
    return len(words) >= 6 and sum(w in _FR_WORDS for w in words) / len(words) >= 0.15


# --- Chiffres non sourcés ---------------------------------------------------------------------------

_NUM = r"(?P<n>\d{1,3}(?:[   .,]\d{3})+|\d+(?:[.,]\d+)?)"
_PERCENT = re.compile(_NUM + r"\s?%")
_CLAIMS = [
    _PERCENT,
    re.compile(_NUM + r"\s?(?:k|m|millions?|milliers?|thousands?)?\s?\+?\s+(?:d['’]\s?)?"
               r"(?:utilisateur|user|téléchargement|download|personne|people|client|customer|avis|review|"
               r"abonné|subscriber|member|membre|étudiant|student|installation|install)s?\b", re.I),
    re.compile(_NUM + r"\s?(?:★|⭐|étoiles?|stars?)", re.I),
]


def _norm_number(raw: str) -> str:
    raw = re.sub(r"[   ]", "", raw)
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
        return re.sub(r"[.,]", "", raw)
    return raw.replace(",", ".")


def numbers_in(text: str) -> set[str]:
    return {_norm_number(m.group("n")) for m in re.finditer(_NUM, text or "")}


def unsourced_claims(texts: Iterable[str], sources: str) -> list[str]:
    """Pourcentages, nombres d'utilisateurs ou d'avis, notes : permis seulement s'ils sont dans la fiche."""
    allowed = numbers_in(sources)
    found: list[str] = []
    for text in texts:
        for pattern in _CLAIMS:
            for m in pattern.finditer(text or ""):
                num = _norm_number(m.group("n"))
                if pattern is _PERCENT and num in ("0", "100"):
                    continue          # « 100 % gratuit », « 0 % de pub » : des tournures, pas des statistiques
                if num not in allowed:
                    found.append(m.group(0).strip())
    return list(dict.fromkeys(found))


# --- Idées : normalisation ---------------------------------------------------------------------------

def ai_label_required(idea: Idea) -> bool:
    """Visages, voix ou scènes réalistes générés : le label IA est obligatoire (REPRISE §3)."""
    spec = formats.CATALOG.get(idea.format)
    if spec is not None and spec.ai_label_required:
        return True
    return any(s.kind in AI_SHOTS for s in idea.shots)


def is_props_format(format_id: str) -> bool:
    spec = formats.CATALOG.get(format_id)
    return spec is not None and spec.engine == "remotion"


def normalize_idea(idea: Idea, ctx: IdeaContext) -> Idea:
    """Corrige la forme sans toucher au fond (le fond, c'est à Claude de le reprendre)."""
    d = idea.model_copy(deep=True)
    d.phone_id = ctx.phone_id
    d.format = d.format.strip()
    d.hook = " ".join(d.hook.split())
    d.title = " ".join(d.title.split()) or d.hook[:80]
    caption, tags = split_trailing_hashtags(d.caption.strip())
    d.caption = caption
    d.hashtags = normalize_hashtags([*d.hashtags, *tags])
    d.pillar = match_pillar(d.pillar, ctx.pillars)
    if is_props_format(d.format):
        d.shots = []
        props, errors = formats.parse_props(d.props_json)
        if not errors:
            d.props_json = json.dumps(_clean_props(d.format, props), ensure_ascii=False)
    else:
        d.shots = [_clean_shot(s) for s in d.shots]
    if ai_label_required(d):
        d.ai_label = True
    return d


def _clean_props(format_id: str, props: dict) -> dict:
    props = {k: v for k, v in props.items() if k not in PRODUCTION_KEYS}
    if format_id == "hook-demo":       # une capture se désigne par asset_id ; la production pose le fichier
        for screen in props.get("screens") or []:
            if isinstance(screen, dict):
                screen.pop("src", None)
    if format_id == "slideshow":       # images de fond : choisies par la production
        for slide in props.get("slides") or []:
            if isinstance(slide, dict):
                slide.pop("bg", None)
    return props


def _clean_shot(shot: Shot) -> Shot:
    s = shot.model_copy()
    s.prompt = " ".join(s.prompt.split()) if s.kind in AI_SHOTS else ""
    if s.kind not in ASSET_SHOTS:
        s.asset_id = None
    s.on_screen_text = s.on_screen_text.strip()
    s.voiceover = s.voiceover.strip()
    return s


# --- Idées : validation ---------------------------------------------------------------------------------

def validate_idea(idea: Idea, ctx: IdeaContext) -> list[str]:
    """Liste des erreurs (vide = l'idée peut partir en production)."""
    spec = formats.CATALOG.get(idea.format)
    if spec is None:
        known = ", ".join(s.id for s in formats.catalog())
        return [f"format inconnu : « {idea.format} » (formats possibles : {known})"]
    errors: list[str] = []
    if not spec.enabled:
        errors.append(f"format « {idea.format} » désactivé : en choisir un autre du catalogue")
    if idea.lang != ctx.lang:
        errors.append(f"langue « {idea.lang} » : ce compte publie en « {ctx.lang} » ; écrire l'idée directement "
                      f"dans cette langue, sans traduire")
    if not idea.hook:
        errors.append("hook : accroche obligatoire")
    elif len(idea.hook) > MAX_HOOK:
        errors.append(f"hook : {len(idea.hook)} caractères, {MAX_HOOK} au plus (elle doit se lire en 2 secondes)")
    if not idea.caption:
        errors.append("caption : légende obligatoire")
    elif len(idea.caption) > MAX_CAPTION:
        errors.append(f"caption : {len(idea.caption)} caractères, {MAX_CAPTION} au plus")
    if spec.engine == "remotion":
        errors += _check_props(idea, ctx)
    else:
        errors += _check_shots(idea, ctx)
    texts = visible_texts(idea)
    errors += _check_do_not_say(texts, ctx.do_not_say)
    errors += [f"chiffre non sourcé « {c} » : n'utiliser que les chiffres de la fiche produit (proof_points), "
               f"sinon reformuler sans chiffre" for c in unsourced_claims(texts, ctx.sources)]
    return errors


def _check_props(idea: Idea, ctx: IdeaContext) -> list[str]:
    props, errors = formats.parse_props(idea.props_json)
    if errors:
        return errors
    if not props:
        return [f"props_json : vide ; le format « {idea.format} » attend ses props (voir le catalogue)"]
    errors = [f"props_json.{e}" for e in formats.validate(idea.format, props)]
    refs = list(_asset_values(props))
    errors += _check_assets(refs, ctx, want="image", where="props_json")
    if idea.format == "hook-demo" and ctx.usable_images and not refs:
        errors.append("props_json.screens : montrer au moins une vraie capture (asset_id) : l'app en a de disponibles")
    return errors


def _check_shots(idea: Idea, ctx: IdeaContext) -> list[str]:
    shots = idea.shots
    if not shots:
        return [f"shots : le format « {idea.format} » se décrit en plans (shots), aucun n'est fourni"]
    errors: list[str] = []
    total = sum(max(0.0, s.duration_s) for s in shots)
    if not MIN_TOTAL_S <= total <= MAX_TOTAL_S:
        errors.append(f"shots : {total:g} s au total, entre {MIN_TOTAL_S:g} et {MAX_TOTAL_S:g} s attendues")
    for i, s in enumerate(shots):
        where = f"shots[{i}]"
        if s.duration_s < MIN_SHOT_S:
            errors.append(f"{where}.duration_s : {s.duration_s:g} s, au moins {MIN_SHOT_S:g} s")
        elif s.kind in AI_SHOTS and s.duration_s > MAX_AI_SHOT_S:
            errors.append(f"{where} : plan IA de {s.duration_s:g} s, {MAX_AI_SHOT_S:g} s au plus "
                          f"(le couper en deux plans)")
        elif s.duration_s > MAX_SHOT_S:
            errors.append(f"{where} : {s.duration_s:g} s, {MAX_SHOT_S:g} s au plus par plan")
        if s.kind in ASSET_SHOTS:
            if s.asset_id is None:
                errors.append(f"{where}.asset_id : obligatoire pour un plan {s.kind}")
            else:
                want = "video" if s.kind == "app_recording" else "image"
                errors += _check_assets([s.asset_id], ctx, want=want, where=f"{where}.asset_id")
        if s.kind in AI_SHOTS:
            if len(s.prompt) < 20:
                errors.append(f"{where}.prompt : prompt du générateur obligatoire (en anglais, concret et filmable)")
            elif looks_french(s.prompt):
                errors.append(f"{where}.prompt : à écrire en anglais (le générateur vidéo comprend mieux l'anglais)")
        if s.kind == "ugc_avatar" and not s.voiceover:
            errors.append(f"{where}.voiceover : ce que dit l'avatar, dans la langue du compte")
        if len(s.on_screen_text) > MAX_ON_SCREEN:
            errors.append(f"{where}.on_screen_text : {len(s.on_screen_text)} caractères, {MAX_ON_SCREEN} au plus")
    if (ctx.usable_images or ctx.usable_videos) and not any(s.kind in ASSET_SHOTS for s in shots):
        errors.append("shots : montrer la vraie app (au moins un plan app_screenshot ou app_recording sur une "
                      "capture disponible)")
    props: dict = {}
    if idea.props_json.strip():
        props, perr = formats.parse_props(idea.props_json)
        errors += perr
    # Un format à plans enregistré par la production reçoit ses props et ses plans.
    errors += [f"format : {e}" for e in
               formats.validate(idea.format, {**props, "shots": [s.model_dump() for s in shots]})]
    return errors


def _asset_values(obj: Any) -> Iterator[Any]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "asset_id":
                yield v
            else:
                yield from _asset_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _asset_values(v)


def _check_assets(values: list[Any], ctx: IdeaContext, *, want: str, where: str) -> list[str]:
    errors: list[str] = []
    available = ", ".join(str(i) for i in sorted(ctx.usable_videos if want == "video" else ctx.usable_images))
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, str)) or not str(v).isdigit():
            errors.append(f"{where} : asset_id « {v} » n'est pas un id de capture")
            continue
        aid = int(v)
        asset = ctx.assets.get(aid)
        if asset is None:
            errors.append(f"{where} : asset_id {aid} inconnu (ids disponibles : {available or 'aucun'})")
        elif asset.usable is False:
            errors.append(f"{where} : la capture {aid} n'est pas utilisable en vidéo "
                          f"({asset.caution or 'données privées ou illisible'})")
        elif want == "image" and not asset.is_image:
            errors.append(f"{where} : l'asset {aid} est une vidéo, pas une capture (plan app_recording)")
        elif want == "video" and not asset.is_video:
            errors.append(f"{where} : l'asset {aid} est une image, pas une vidéo de démo (plan app_screenshot)")
    return errors


def visible_texts(idea: Idea) -> list[str]:
    """Tout ce que le spectateur lit ou entend."""
    texts = [idea.hook, idea.caption]
    for s in idea.shots:
        texts += [s.on_screen_text, s.voiceover]
    props, errors = formats.parse_props(idea.props_json) if idea.props_json.strip() else ({}, [])
    if not errors:
        texts += list(_strings(props))
    return [t for t in texts if t]


def _strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _check_do_not_say(texts: list[str], items: list[str]) -> list[str]:
    """Les interdits courts de la fiche (« gratuit à vie », « guérir »…) ne doivent pas apparaître tels quels."""
    blob = f" {fold(' '.join(texts))} "
    errors = []
    for item in items:
        key = fold(item)
        if key and len(key.split()) <= 6 and f" {key} " in blob:
            errors.append(f"« {item} » fait partie de ce qu'on ne dit jamais (do_not_say)")
    return errors


# --- Stratégie -----------------------------------------------------------------------------------------

def check_strategy(strategy: Strategy, phones: Iterable[Any]) -> tuple[Strategy, list[str], list[str]]:
    """Normalise la stratégie. Renvoie (stratégie, erreurs bloquantes, réserves).

    Bloquant : ce qui empêche d'écrire des idées (pas de voix pour un téléphone, mauvaise langue, aucun
    format du catalogue, moins de 2 piliers). Réserves : ce qu'un humain doit regarder avant d'approuver
    (voix trop proches, trop peu d'accroches dans une langue…).
    """
    s = strategy.model_copy(deep=True)
    blocking: list[str] = []
    warnings: list[str] = []
    known = [f.id for f in formats.catalog()]

    plans, seen = [], set()
    for plan in s.formats:
        fid = plan.format.strip()
        if fid in seen:
            continue
        if fid not in known:
            warnings.append(f"formats : « {fid} » n'est pas dans le catalogue (retiré)")
            continue
        seen.add(fid)
        plans.append(plan.model_copy(update={"format": fid}))
    if not plans:
        blocking.append(f"formats : aucun format du catalogue (ids possibles : {', '.join(known)})")
    s.formats = _rescale(plans)

    pillars, seen_p = [], set()
    for p in s.pillars:
        name = " ".join(p.name.split())
        if name and fold(name) not in seen_p:
            seen_p.add(fold(name))
            pillars.append(p.model_copy(update={"name": name}))
    if len(pillars) < 2:
        blocking.append("pillars : au moins 2 piliers de contenu")
    s.pillars = _rescale(pillars)
    names = [p.name for p in s.pillars]
    s.posts_per_day_per_account = max(1, min(int(s.posts_per_day_per_account or 1), 5))

    phones = list(phones)
    wanted = {ph.id: ph.lang for ph in phones}
    by_phone: dict[str, AccountVoice] = {}
    for v in s.voices:
        pid = v.phone_id.strip()
        if pid not in wanted:
            warnings.append(f"voices : « {pid} » n'est pas un téléphone de l'app (voix retirée)")
        elif pid not in by_phone:
            by_phone[pid] = v
    voices = []
    for ph in phones:
        v = by_phone.get(ph.id)
        if v is None:
            blocking.append(f"voices : il manque la voix de {ph.id} (compte en « {ph.lang} »)")
            continue
        if v.lang != ph.lang:
            blocking.append(f"voices : {ph.id} publie en « {ph.lang} », pas en « {v.lang} » "
                            f"(lang = {ph.lang}, bio écrite en {ph.lang})")
        if not v.bio.strip():
            warnings.append(f"voices : bio vide pour {ph.id}")
        fmts = [f for f in dict.fromkeys(x.strip() for x in v.formats) if f in known] or [p.format for p in s.formats]
        pls = [m for m in dict.fromkeys(match_pillar(x, names) for x in v.pillars) if m in names] or names
        voices.append(v.model_copy(update={"phone_id": ph.id, "formats": fmts, "pillars": pls}))
    s.voices = voices
    warnings += voice_overlaps(voices)

    s.hooks = [h for h in s.hooks if h.text.strip()]
    for lang in sorted(set(wanted.values())):
        n = sum(h.lang == lang for h in s.hooks)
        if n < 5:
            warnings.append(f"hooks : {n} accroche(s) en « {lang} », au moins 5 attendues")
    if not s.positioning.strip():
        warnings.append("positioning : vide")
    return s, blocking, warnings


def voice_overlaps(voices: list[AccountVoice]) -> list[str]:
    """Deux comptes ne doivent jamais pouvoir s'échanger leurs vidéos."""
    out = []
    for a, b in combinations(voices, 2):
        reasons = []
        if difflib.SequenceMatcher(None, fold(a.voice), fold(b.voice), autojunk=False).ratio() >= VOICE_RATIO:
            reasons.append("même personnage")
        if fold(a.bio) and fold(a.bio) == fold(b.bio):
            reasons.append("même bio")
        if (a.lang == b.lang and fold(a.persona_target) == fold(b.persona_target)
                and set(a.pillars) == set(b.pillars) and set(a.formats) == set(b.formats)):
            reasons.append("même persona, mêmes piliers et mêmes formats")
        if reasons:
            out.append(f"voices : {a.phone_id} et {b.phone_id} se ressemblent trop ({', '.join(reasons)}) : "
                       f"différencier le persona visé, le mélange de piliers ou de formats, et le personnage")
    return out


def _rescale(items: list) -> list:
    """Ramène les parts (share) à un total de 100."""
    if not items:
        return items
    shares = [max(0, int(it.share or 0)) for it in items]
    total = sum(shares)
    if total == 100:
        return items
    if total == 0:
        shares = [1] * len(items)
        total = len(items)
    scaled = [math.floor(sh * 100 / total) for sh in shares]
    rest = 100 - sum(scaled)
    order = sorted(range(len(items)), key=lambda i: -(shares[i] * 100 / total - scaled[i]))
    for i in order[:rest]:
        scaled[i] += 1
    return [it.model_copy(update={"share": sh}) for it, sh in zip(items, scaled, strict=True)]
