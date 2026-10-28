"""Formats « à plans » : la vidéo est une suite de plans (schemas.Shot) au lieu de props Remotion.

Ils sont tous rendus par la composition Remotion `story` (render/src/formats/Story.tsx), après la
génération des plans IA éventuels (tâches `video.generate` du module providers). Importé par les
tâches du module : les formats s'ajoutent au catalogue commun (formats.register).

Contrat avec le module strategy : `formats.validate(<format>, {**props, "shots": [...]})`, où `props` vient de
`props_json` (souvent `{}`) et les plans de `Idea.shots`. Seule clé de props reconnue : `trims`, pour choisir
où couper une vidéo de démo : `{"trims": {"<index du plan>": <début en s>}}`.
"""

from __future__ import annotations

from loopcast import formats
from loopcast.formats import FormatSpec

STORY = "story"                          # la composition Remotion qui enchaîne les plans

AI_KINDS = ("ai_video", "ugc_avatar")    # plans générés par le module providers
APP_KINDS = ("app_screenshot", "app_recording")

# Durée permise par type de plan (secondes) : assez pour lire, assez court pour garder le rythme.
DURATIONS: dict[str, tuple[float, float]] = {
    "ai_video": (2.0, 10.0),              # un plan IA dure 10 s au plus (contrat avec strategy et providers)
    "ugc_avatar": (3.0, 10.0),
    "app_screenshot": (1.5, 6.0),
    "app_recording": (2.0, 15.0),
    "text_card": (1.5, 5.0),
    "end_card": (2.0, 4.0),
}
END_CARD_S = 2.5                         # carte de fin ajoutée si l'idée n'en prévoit pas
TOTAL_S = (8.0, 50.0)                    # durée totale visée (le contrôle qualité accepte 6 à 60 s)
MAX_SHOTS = 10
TEXT_MAX = 80                            # texte incrusté : 2 à 3 lignes lisibles
SPEECH_CPS = 16                          # caractères dits par seconde, au plus (au-delà la voix court)
PROMPT_MIN, PROMPT_MAX = 20, 1500


def uses_shots(spec: FormatSpec) -> bool:
    """Vrai pour un format produit plan par plan (rendu par `story`), faux pour un format Remotion à props."""
    return spec.composition in (None, STORY)


def _num(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _shot_errors(e: list[str], i: int, s: object, allowed: tuple[str, ...]) -> str | None:
    """Contrôle un plan ; renvoie son type s'il est exploitable."""
    if not isinstance(s, dict):
        e.append(f"shots[{i}] : objet attendu")
        return None
    kind = s.get("kind")
    if kind not in allowed:
        e.append(f"shots[{i}].kind : « {kind} » n'est pas permis dans ce format ({', '.join(allowed)})")
        return None
    d = s.get("duration_s")
    lo, hi = DURATIONS[kind]
    if not _num(d):
        e.append(f"shots[{i}].duration_s : durée en secondes obligatoire")
        d = None
    elif not lo <= d <= hi:
        e.append(f"shots[{i}].duration_s : {d:g} s, entre {lo:g} et {hi:g} s pour un plan {kind}")
    text = s.get("on_screen_text") or ""
    voice = s.get("voiceover") or ""
    if not isinstance(text, str) or not isinstance(voice, str):
        e.append(f"shots[{i}] : on_screen_text et voiceover sont des textes")
        return kind
    if len(text) > TEXT_MAX:
        e.append(f"shots[{i}].on_screen_text : {len(text)} caractères, {TEXT_MAX} au plus")
    if voice and d is not None and len(voice) > d * SPEECH_CPS:
        e.append(f"shots[{i}].voiceover : {len(voice)} caractères pour {d:g} s, {int(d * SPEECH_CPS)} au plus "
                 f"(sinon la voix et les sous-titres vont trop vite)")
    if kind in AI_KINDS:
        prompt = s.get("prompt") or ""
        if not isinstance(prompt, str) or len(prompt.strip()) < PROMPT_MIN:
            e.append(f"shots[{i}].prompt : prompt du générateur obligatoire, en anglais et précis "
                     f"(sujet, action, cadrage, lumière, style)")
        elif len(prompt) > PROMPT_MAX:
            e.append(f"shots[{i}].prompt : {len(prompt)} caractères, {PROMPT_MAX} au plus")
    if kind in APP_KINDS:
        asset = s.get("asset_id")
        if not isinstance(asset, int) or isinstance(asset, bool):
            what = "la capture" if kind == "app_screenshot" else "la vidéo de démo"
            e.append(f"shots[{i}].asset_id : id de {what} obligatoire")
    if kind == "text_card" and not text.strip():
        e.append(f"shots[{i}].on_screen_text : obligatoire pour une carte texte")
    if kind == "ugc_avatar" and not voice.strip():
        e.append(f"shots[{i}].voiceover : la phrase dite face caméra est obligatoire")
    return kind


def _shots(e: list[str], p: dict, allowed: tuple[str, ...]) -> list[str | None]:
    """Contrôles communs à tous les formats à plans ; renvoie le type de chaque plan (None si illisible)."""
    shots = p.get("shots") if isinstance(p, dict) else None
    if not isinstance(shots, list):
        e.append("shots : liste de plans obligatoire (props_json reste vide pour ce format)")
        return []
    if not 2 <= len(shots) <= MAX_SHOTS:
        e.append(f"shots : {len(shots)} plans, entre 2 et {MAX_SHOTS} attendus")
    kinds = [_shot_errors(e, i, s, allowed) for i, s in enumerate(shots)]
    ends = [i for i, k in enumerate(kinds) if k == "end_card"]
    if len(ends) > 1 or (ends and ends[0] != len(shots) - 1):
        e.append("shots : une seule carte de fin (end_card), en dernier")
    total = sum(s["duration_s"] for s in shots if isinstance(s, dict) and _num(s.get("duration_s")))
    if not ends:
        total += END_CARD_S
    if shots and not TOTAL_S[0] <= total <= TOTAL_S[1]:
        e.append(f"durée totale {total:g} s (carte de fin comprise), entre {TOTAL_S[0]:g} et {TOTAL_S[1]:g} s attendus")
    if "trims" in p:
        e.extend(trim_errors(p["trims"], shots))
    return kinds


def trim_errors(trims: object, shots: list) -> list[str]:
    """`trims` = {"<index du plan>": <début en s>} : où commence chaque passage d'une vidéo de démo."""
    if not isinstance(trims, dict):
        return ['trims : objet {"<index du plan>": <début en secondes>} attendu']
    e: list[str] = []
    for key, start in trims.items():
        try:
            i = int(key)
        except (TypeError, ValueError):
            e.append(f"trims : « {key} » n'est pas un index de plan")
            continue
        if not 0 <= i < len(shots) or not isinstance(shots[i], dict) or shots[i].get("kind") != "app_recording":
            e.append(f"trims[{key}] : le plan {key} n'est pas un passage de vidéo de démo (app_recording)")
        elif not _num(start) or start < 0:
            e.append(f"trims[{key}] : début en secondes (≥ 0) attendu")
    return e


def _count(kinds: list, wanted: tuple[str, ...]) -> int:
    return sum(1 for k in kinds if k in wanted)


# --- Les 4 formats ------------------------------------------------------------------------------------

def _app_story(p: dict) -> list[str]:
    e: list[str] = []
    kinds = _shots(e, p, ("app_screenshot", "app_recording", "text_card", "end_card"))
    if kinds and _count(kinds, APP_KINDS) < 2:
        e.append("shots : au moins 2 plans montrent l'app (app_screenshot ou app_recording)")
    return e


def _ai_hook_demo(p: dict) -> list[str]:
    e: list[str] = []
    kinds = _shots(e, p, ("ai_video", "app_screenshot", "app_recording", "text_card", "end_card"))
    if not kinds:
        return e
    first = p["shots"][0] if isinstance(p.get("shots"), list) and p["shots"] else None
    if kinds[0] != "ai_video":
        e.append("shots[0] : l'accroche est un plan ai_video")
    elif isinstance(first, dict) and _num(first.get("duration_s")) and not 2 <= first["duration_s"] <= 4:
        e.append(f"shots[0].duration_s : l'accroche IA dure 2 à 4 s ({first['duration_s']:g} s)")
    if _count(kinds, ("ai_video",)) > 1:
        e.append("shots : une seule vidéo IA (l'accroche), la suite montre les vraies captures")
    if _count(kinds, APP_KINDS) < 2:
        e.append("shots : au moins 2 plans de démo sur les vraies captures (app_screenshot ou app_recording)")
    return e


def _ugc_ai(p: dict) -> list[str]:
    e: list[str] = []
    kinds = _shots(e, p, ("ugc_avatar", "app_screenshot", "app_recording", "text_card", "end_card"))
    if not kinds:
        return e
    if kinds[0] != "ugc_avatar":
        e.append("shots[0] : la vidéo commence par la personne qui parle (ugc_avatar)")
    n = _count(kinds, ("ugc_avatar",))
    if not 1 <= n <= 3:
        e.append(f"shots : {n} plans ugc_avatar, entre 1 et 3 attendus")
    if _count(kinds, APP_KINDS) < 1:
        e.append("shots : au moins un plan montre l'app (app_screenshot ou app_recording)")
    return e


def _demo_recording(p: dict) -> list[str]:
    e: list[str] = []
    kinds = _shots(e, p, ("app_recording", "text_card", "end_card"))
    if kinds and _count(kinds, ("app_recording",)) < 1:
        e.append("shots : au moins un passage de la vidéo de démo (app_recording)")
    return e


_SHOT_FIELDS = ('"kind", "duration_s", "visual" (ce qu\'on voit, en français), "on_screen_text" (≤ 80 car., '
                'langue du compte), "voiceover", "prompt", "asset_id"')

APP_STORY = formats.register(FormatSpec(
    "app-story", "video", "remotion", STORY, "Histoire sur les vraies captures de l'app",
    "Une petite histoire racontée uniquement avec les VRAIES captures et enregistrements d'écran de l'app "
    "(dans un iPhone, avec un léger mouvement), des cartes texte pour rythmer et la carte de fin (appel à "
    "l'action, icône, store). Le texte du premier plan est l'accroche ; voiceover s'affiche en sous-titres "
    "incrustés (pas de voix : écrire une narration courte et orale). Idéal pour montrer une fonctionnalité "
    "concrète en 12 à 25 s. Coût nul, pas de label IA.",
    f"shots : 3 à 8 plans (total 10 à 40 s), {_SHOT_FIELDS}. Types : app_screenshot (1,5 à 6 s, asset_id d'une "
    "capture), app_recording (2 à 15 s, asset_id d'une vidéo de démo), text_card (1,5 à 5 s, on_screen_text "
    "obligatoire), end_card (facultative, en dernier : on_screen_text = l'appel à l'action). voiceover ≤ 16 "
    "car. par seconde de plan. prompt vide. props_json vide.",
    "free", validate=_app_story))

AI_HOOK_DEMO = formats.register(FormatSpec(
    "ai-hook-demo", "video", "hybrid", STORY, "Accroche en vidéo IA + démo sur vraies captures",
    "2 à 4 s de vidéo IA réaliste qui arrête le scroll (la situation-problème du persona, une scène forte et "
    "simple, sans texte à l'image), avec l'accroche écrite par-dessus ; puis la démo sur les VRAIES captures "
    "de l'app ; puis la carte de fin. Une seule vidéo IA. Payant : à réserver aux accroches très visuelles. "
    "Label IA posé automatiquement.",
    f"shots : 3 à 7 plans (total 10 à 30 s), {_SHOT_FIELDS}. shots[0] = ai_video de 2 à 4 s : prompt en "
    "anglais (sujet, action, cadrage vertical 9:16, lumière, style ; pas de texte, de logo ni d'interface "
    "dans l'image), on_screen_text = l'accroche. Puis au moins 2 plans app_screenshot / app_recording "
    "(asset_id, on_screen_text = ce que montre l'écran), text_card permis, end_card facultative. "
    "props_json vide.",
    "premium", validate=_ai_hook_demo))

UGC_AI = formats.register(FormatSpec(
    "ugc-ai", "video", "hybrid", STORY, "Personne générée qui parle face caméra + captures",
    "Une personne générée par IA parle face caméra, comme une vidéo filmée au téléphone (astuce, réaction, "
    "explication), puis on montre l'app sur ses vraies captures. Elle parle AU NOM de l'app, comme une "
    "présentatrice de la marque : jamais comme une cliente, jamais de témoignage, d'avis ou de résultat "
    "personnel (« depuis que j'utilise… »), ce serait un faux consommateur, interdit (playbook §4.2, §6). Ce "
    "qu'elle dit est dans voiceover (langue du compte, oral et naturel, une idée par plan) et s'affiche en "
    "sous-titres ; la personne, le décor et la façon de filmer sont décrits dans prompt (en anglais). Le plus "
    "convaincant, mais le plus cher : label IA obligatoire.",
    f"shots : 2 à 6 plans (total 12 à 35 s), {_SHOT_FIELDS}. shots[0] = ugc_avatar (3 à 10 s) ; 1 à 3 plans "
    "ugc_avatar en tout, avec voiceover ≤ 16 car. par seconde et prompt anglais décrivant la même personne "
    "à chaque plan (âge, style, lieu, lumière, selfie vertical) ; au moins un plan app_screenshot / "
    "app_recording (asset_id) ; end_card facultative. props_json vide.",
    "premium", ai_label_required=True, validate=_ugc_ai))

DEMO_RECORDING = formats.register(FormatSpec(
    "demo-recording", "video", "remotion", STORY, "Vraie vidéo de démo découpée",
    "La vraie vidéo de démo fournie par l'équipe (asset de type demo_video), découpée en 2 à 5 passages "
    "montrés dans un iPhone, avec une accroche (carte texte ou texte sur le premier passage), des "
    "sous-titres (voiceover) et la carte de fin. Les passages s'enchaînent dans l'ordre de la vidéo. Coût nul.",
    f"shots : 2 à 7 plans (total 10 à 40 s), {_SHOT_FIELDS}. Types : app_recording (2 à 15 s, asset_id de la "
    "vidéo de démo), text_card (1,5 à 5 s), end_card facultative. Pour choisir où couper : props_json = "
    '{"trims": {"<index du plan>": <début en secondes dans la vidéo>}}, sinon props_json vide.',
    "free", validate=_demo_recording))

SHOT_FORMATS = (APP_STORY.id, AI_HOOK_DEMO.id, UGC_AI.id, DEMO_RECORDING.id)
