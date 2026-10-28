"""D'une idée aux props du rendu.

- Format Remotion à props : props de l'idée validées, captures (asset_id) publiées sous render/public/,
  marque, langue et appel à l'action ajoutés.
- Format à plans : chaque plan devient un plan de la composition `story` (clip, capture dans un iPhone,
  enregistrement d'écran, carte texte, carte de fin) ; les clips IA sont recadrés sur la parole et la
  durée réelle ; une carte de fin est ajoutée si l'idée n'en prévoit pas. La chronologie produite
  (début et fin de chaque plan) sert au contrôle qualité pour savoir quel plan IA régénérer.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any

from loopcast import formats
from loopcast.formats import FormatSpec
from loopcast.jobs import Permanent
from loopcast.production import assets, options, qa
from loopcast.production.formats_extra import AI_KINDS, END_CARD_S, uses_shots
from loopcast.schemas import Idea

FPS = 30                          # comme render/src/common/types.ts
SPEECH_LEAD_S = 0.15              # on garde un souffle avant la première syllabe…
SPEECH_TAIL_S = 0.35              # … et après la dernière
END_MARGIN_S = 0.3                # chaque plan déborde du fondu (8 images) sur le suivant : jamais au-delà du fichier
STORY_KIND = {"ai_video": "clip", "ugc_avatar": "clip", "app_screenshot": "screen",
              "app_recording": "recording", "text_card": "card", "end_card": "end"}


def frames(seconds: float) -> int:
    """Comme Math.round(seconds * FPS) côté TypeScript (round() de Python arrondit au pair)."""
    return max(1, math.floor(seconds * FPS + 0.5))


# --- Formats Remotion à props ----------------------------------------------------------------------------

def validated_props(idea: Idea, spec: FormatSpec) -> dict:
    """Les props de l'idée, validées comme le fait le module strategy : props_json pour un format Remotion,
    `{**props_json, "shots": [...]}` pour un format à plans. Permanent avec les erreurs sinon."""
    props, errors = formats.parse_props(idea.props_json)
    if not errors:
        data = {**props, "shots": [s.model_dump() for s in idea.shots]} if uses_shots(spec) else props
        errors = formats.validate(spec.id, data)
    if errors:
        raise Permanent(f"idée invalide pour {spec.id} : " + " ; ".join(errors))
    return props


def remotion_props(conn: sqlite3.Connection, config: Any, app_id: str, idea: Idea, spec: FormatSpec,
                   lang: str) -> tuple[dict, list[str]]:
    """Les props de la stratégie (avec `cta`, captures en `asset_id`) complétées de lang, brand, src/bg."""
    props = validated_props(idea, spec)
    brand, notes = assets.brand(conn, config, app_id, lang)
    # Les captures : asset_id → chemin sous public/ (screens[].src pour hook-demo, slides[].bg pour slideshow).
    for key, target in (("screens", "src"), ("slides", "bg")):
        for i, item in enumerate(props.get(key) or []):
            if isinstance(item, dict) and item.get("asset_id") is not None:
                item[target], _ = assets.publish_asset(conn, config, app_id, int(item["asset_id"]), video=False,
                                                       where=f"{key}[{i}]")
    music = props.pop("music", None)
    if music and (assets.public_dir(config) / str(music)).is_file():
        props["music"] = music
    elif music:
        notes.append(f"musique « {music} » introuvable sous render/public : vidéo sans musique")
    props.update(lang=lang, brand=brand, cta=assets.cta(conn, app_id, lang, brand["name"], props.get("cta")))
    return props, notes


def stills_count(spec: FormatSpec, props: dict) -> int | None:
    """Nombre d'images d'un carrousel (le slideshow ajoute une slide d'appel à l'action)."""
    if spec.kind != "carousel":
        return None
    return len(props.get("slides") or []) + 1


# --- Formats à plans --------------------------------------------------------------------------------------

def trims(props: dict) -> dict[int, float]:
    """Où commence chaque passage d'une vidéo de démo ({"trims": {"<index>": <début en s>}}, déjà validé)."""
    out: dict[int, float] = {}
    for key, start in (props.get("trims") or {}).items():
        try:
            out[int(key)] = float(start)
        except (TypeError, ValueError):
            continue
    return out


def prepare_shots(conn: sqlite3.Connection, config: Any, app_id: str, shots: list[dict]) -> list[dict]:
    """Vérifie et publie les captures et vidéos de démo de chaque plan, AVANT toute génération payante."""
    ffprobe = options.ffprobe_bin(config.settings or {})
    prepared = []
    for i, s in enumerate(shots):
        item: dict = {"index": i, "kind": s["kind"]}
        if s["kind"] in ("app_screenshot", "app_recording"):
            video = s["kind"] == "app_recording"
            rel, row = assets.publish_asset(conn, config, app_id, int(s["asset_id"]), video=video,
                                            where=f"plan {i + 1}")
            item.update(src=rel, width=row["width"], height=row["height"])
            if video:
                media_s = row["duration_s"]
                if not media_s:
                    try:
                        media_s = qa.duration_of(qa.probe(assets.public_dir(config) / rel, ffprobe))
                    except qa.QAError as e:
                        raise Permanent(f"plan {i + 1} : vidéo de démo illisible ({e})") from e
                item["media_s"] = float(media_s)
        prepared.append(item)
    return prepared


def video_request(shot: dict, settings: dict, lang: str, image_path: str | None = None) -> dict:
    """Les champs de VideoRequest (contrat du module providers) pour un plan IA."""
    prompt = shot["prompt"].strip()
    if shot["kind"] == "ugc_avatar":
        line = (shot.get("voiceover") or "").strip()
        if line and line not in prompt:
            language = "French" if lang == "fr" else "English"
            prompt += f'\nThe person talks to the camera in {language}, naturally, and says exactly: "{line}"'
    if "no on-screen text" not in prompt.lower():
        prompt += "\nVertical 9:16 framing. No on-screen text, subtitles, logos or watermarks."
    return {"prompt": prompt, "duration_s": float(shot["duration_s"]), "aspect": "9:16", "image_path": image_path,
            "audio": shot["kind"] == "ugc_avatar", "quality": options.video_quality(settings, shot["kind"]),
            "seed": None}


def story_props(*, shots: list[dict], prepared: list[dict], clips: dict[int, dict], trims: dict[int, float],
                hook: str, brand: dict, cta: str, lang: str) -> tuple[dict, list[dict], list[str]]:
    """Props de la composition `story`, chronologie des plans et remarques pour la relecture.

    `clips[i]` (plans IA) = {"src": chemin sous public/, "duration": durée du fichier, "speech": (début, fin) | None}.
    """
    notes: list[str] = []
    cursor: dict[str, float] = {}             # où on en est dans chaque vidéo de démo (passages dans l'ordre)
    out: list[dict] = []
    timeline: list[dict] = []
    for i, s in enumerate(shots):
        kind, planned = s["kind"], float(s["duration_s"])
        text = (s.get("on_screen_text") or "").strip()
        if i == 0 and not text and kind != "end_card" and not _says(s.get("voiceover") or "", hook):
            text = hook.strip()                # le premier plan porte l'accroche (sauf si la voix la dit déjà)
        shot: dict = {"kind": STORY_KIND[kind], "duration": planned}
        if text:
            shot["text"] = text
        if (s.get("voiceover") or "").strip() and kind != "end_card":
            shot["subtitle"] = s["voiceover"].strip()
        if kind in AI_KINDS:
            clip = clips[i]
            shot["src"] = clip["src"]
            shot["duration"] = _clip_duration(shot, clip, planned, kind, i, notes)
        elif kind == "app_screenshot":
            shot["src"] = prepared[i]["src"]
        elif kind == "app_recording":
            _recording(shot, prepared[i], trims.get(i), cursor, i, notes)
        out.append(shot)
        timeline.append({"index": i, "kind": kind, "ai": kind in AI_KINDS})
    if not shots or shots[-1]["kind"] != "end_card":
        out.append({"kind": "end", "duration": END_CARD_S})
        timeline.append({"index": None, "kind": "end_card", "ai": False})
    for shot in out:
        if shot["kind"] == "end" and not shot.get("text"):
            shot["text"] = cta
    start = 0
    for shot, item in zip(out, timeline):
        n = frames(shot["duration"])
        item.update(start=round(start / FPS, 3), end=round((start + n) / FPS, 3))
        start += n
    props = {"lang": lang, "brand": brand, "cta": cta, "shots": out}
    return props, timeline, notes


def _norm(text: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


def _says(voice: str, text: str) -> bool:
    """La voix off dit-elle déjà ce texte ? (sans tenir compte de la casse ni de la ponctuation)"""
    return bool(_norm(text)) and _norm(text) in _norm(voice)


def _clip_duration(shot: dict, clip: dict, planned: float, kind: str, i: int, notes: list[str]) -> float:
    """Durée utile d'un clip IA : la parole pour un UGC (silences coupés), sinon la durée prévue."""
    available = max(1.0, float(clip["duration"]) - END_MARGIN_S)
    if kind == "ugc_avatar":
        shot["audio"] = True
        speech = clip.get("speech")
        if speech:
            begin = max(0.0, speech[0] - SPEECH_LEAD_S)
            end = min(available, speech[1] + SPEECH_TAIL_S)
            if begin >= 0.2:
                shot["trimBefore"] = round(begin, 3)
            return round(max(1.0, end - begin), 3)
        notes.append(f"plan {i + 1} : aucune voix détectée dans le clip généré")
    if available + 0.05 < planned:
        notes.append(f"plan {i + 1} : clip de {qa.fr(float(clip['duration']))} s pour {qa.fr(planned)} s prévues, "
                     "plan raccourci")
        return round(available, 3)
    return planned


def _recording(shot: dict, item: dict, trim: float | None, cursor: dict[str, float], i: int,
               notes: list[str]) -> None:
    """Un passage d'une vidéo de démo : là où l'idée le dit, sinon à la suite du passage précédent."""
    src, media = item["src"], float(item["media_s"])
    usable = max(1.0, media - END_MARGIN_S)
    start = trim if trim is not None else cursor.get(src, 0.0)
    length = min(shot["duration"], usable)
    if start + length > usable:
        start = max(0.0, usable - length)
        notes.append(f"plan {i + 1} : la démo ne dure que {qa.fr(media)} s, passage avancé à {qa.fr(start)} s")
    cursor[src] = start + length
    shot.update(src=src, duration=round(length, 3))
    if start > 0:
        shot["trimBefore"] = round(start, 3)
    w, h = item.get("width"), item.get("height")
    if w and h and w >= h:                    # démo horizontale : montrée en entier, hors iPhone
        shot.update(kind="clip", fit="contain")
