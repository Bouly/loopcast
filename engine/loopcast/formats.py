"""Catalogue des formats de contenu : ce que la stratégie peut choisir, ce que la production sait faire.

Un format = un id, un moteur (Remotion, IA, hybride), une description pour Claude, des contraintes,
une classe de coût, et une fonction de validation. La stratégie lit le catalogue (catalog_for_prompt) ;
la production le complète (nouveaux formats hybrides) et valide chaque idée avant de la produire.

Les 4 formats Remotion existants (render/src/formats/) suivent les contraintes de REPRISE §4.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Literal

Engine = Literal["remotion", "ai", "hybrid"]
CostClass = Literal["free", "low", "premium"]


@dataclass
class FormatSpec:
    id: str
    kind: Literal["video", "carousel"]
    engine: Engine
    composition: str | None            # composition Remotion, si le format en a une
    title: str                          # nom lisible (français)
    description: str                    # pour Claude : à quoi il sert, ce qui marche
    props_hint: str                     # forme des props (formats Remotion) ou des plans (IA/hybride)
    cost_class: CostClass
    ai_label_required: bool = False
    validate: Callable[[dict], list[str]] = field(default=lambda props: [])
    enabled: bool = True


CATALOG: dict[str, FormatSpec] = {}


def register(spec: FormatSpec) -> FormatSpec:
    CATALOG[spec.id] = spec
    return spec


def catalog(enabled_only: bool = True) -> list[FormatSpec]:
    return [s for s in CATALOG.values() if s.enabled or not enabled_only]


def get(format_id: str) -> FormatSpec:
    if format_id not in CATALOG:
        raise KeyError(f"format inconnu : {format_id}")
    return CATALOG[format_id]


def validate(format_id: str, props: dict) -> list[str]:
    """Liste d'erreurs (vide = valide), en français, renvoyables telles quelles à Claude."""
    try:
        spec = get(format_id)
    except KeyError as e:
        return [str(e)]
    return spec.validate(props)


def parse_props(props_json: str) -> tuple[dict, list[str]]:
    try:
        props = json.loads(props_json or "{}")
    except json.JSONDecodeError as e:
        return {}, [f"props_json n'est pas du JSON valide : {e}"]
    if not isinstance(props, dict):
        return {}, ["props_json doit être un objet JSON"]
    return props, []


def catalog_for_prompt() -> str:
    """Le catalogue, tel qu'on le donne à Claude pour la stratégie et les idées."""
    lines = []
    for s in catalog():
        lines.append(
            f"- `{s.id}` ({s.kind}, moteur {s.engine}, coût {s.cost_class}"
            f"{', label IA obligatoire' if s.ai_label_required else ''}) : {s.title}. {s.description}\n"
            f"  Forme attendue : {s.props_hint}"
        )
    return "\n".join(lines)


# --- Contrôles communs ------------------------------------------------------------------------------

def _len(errors: list[str], label: str, value: object, max_len: int) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} : texte obligatoire")
    elif len(value) > max_len:
        errors.append(f"{label} : {len(value)} caractères, {max_len} au plus")


def _count(errors: list[str], label: str, items: object, lo: int, hi: int) -> list:
    if not isinstance(items, list):
        errors.append(f"{label} : liste obligatoire")
        return []
    if not lo <= len(items) <= hi:
        errors.append(f"{label} : {len(items)} éléments, entre {lo} et {hi} attendus")
    return items


# --- Les 4 formats Remotion existants (REPRISE §4) ------------------------------------------------------

def _notes_app(p: dict) -> list[str]:
    e: list[str] = []
    _len(e, "title", p.get("title"), 60)
    for i, it in enumerate(_count(e, "items", p.get("items"), 3, 7)):
        _len(e, f"items[{i}]", it, 70)
    return e


def _chat_story(p: dict) -> list[str]:
    e: list[str] = []
    _len(e, "contactName", p.get("contactName"), 40)
    for i, m in enumerate(_count(e, "messages", p.get("messages"), 4, 9)):
        if not isinstance(m, dict) or m.get("from") not in ("me", "them"):
            e.append(f"messages[{i}].from : « me » ou « them »")
            continue
        _len(e, f"messages[{i}].text", m.get("text"), 120)
    return e


def _hook_demo(p: dict) -> list[str]:
    e: list[str] = []
    _len(e, "hook", p.get("hook"), 60)
    for i, s in enumerate(_count(e, "screens", p.get("screens"), 2, 4)):
        if not isinstance(s, dict):
            e.append(f"screens[{i}] : objet attendu")
            continue
        _len(e, f"screens[{i}].caption", s.get("caption"), 45)
        if not s.get("src") and not s.get("mock") and s.get("asset_id") is None:
            e.append(f"screens[{i}] : une capture (asset_id ou src) ou un écran factice (mock) est obligatoire")
    return e


def _slideshow(p: dict) -> list[str]:
    e: list[str] = []
    for i, s in enumerate(_count(e, "slides", p.get("slides"), 4, 8)):
        if not isinstance(s, dict):
            e.append(f"slides[{i}] : objet attendu")
            continue
        _len(e, f"slides[{i}].title", s.get("title"), 70)
        if s.get("body") and len(s["body"]) > 140:
            e.append(f"slides[{i}].body : {len(s['body'])} caractères, 140 au plus")
    return e


register(FormatSpec(
    "notes-app", "video", "remotion", "notes-app", "Liste dans une app de notes",
    "Une note iPhone qui s'écrit ligne à ligne : « 5 choses que… ». Le dernier élément est le payoff qui "
    "amène l'app. Simple, très lisible, coût nul.",
    '{"title": "≤ 60 car.", "items": ["3 à 7 lignes de ≤ 70 car., la dernière mentionne l\'app"], '
    '"highlightLast": true, "numbered": true}',
    "free", validate=_notes_app))

register(FormatSpec(
    "chat-story", "video", "remotion", "chat-story", "Conversation de messagerie",
    "Une conversation qui raconte un problème puis la solution (l'app). Arc : problème → tension → solution.",
    '{"contactName": "≤ 40 car.", "messages": [{"from": "me|them", "text": "≤ 120 car."}] (4 à 9)}',
    "free", validate=_chat_story))

register(FormatSpec(
    "hook-demo", "video", "remotion", "hook-demo", "Accroche + démo sur vraies captures",
    "Une accroche forte puis 2 à 4 écrans de l'app dans un iPhone, avec une légende par écran. Utilise les "
    "VRAIES captures de l'app (asset_id) : c'est notre avantage.",
    '{"hook": "≤ 60 car., **mot** = mot coloré", "screens": [{"caption": "≤ 45 car.", "asset_id": 12}] (2 à 4)}',
    "free", validate=_hook_demo))

register(FormatSpec(
    "slideshow", "carousel", "remotion", "slideshow", "Carrousel de slides",
    "4 à 8 slides (carrousel Instagram / photos TikTok). Slide 0 = l'accroche ; une slide CTA est ajoutée "
    "automatiquement.",
    '{"slides": [{"title": "≤ 70 car. (slide 0 : lignes séparées par \\n)", "body": "≤ 140 car.", "emoji": ""}] (4 à 8)}',
    "free", validate=_slideshow))
