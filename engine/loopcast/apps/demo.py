"""Réponses de démo (serve --demo, sans clé) : plausibles et cohérentes avec l'app demandée.

Elles lisent le message préparé pour Claude (format de prompts.py : <app>, <team_description>,
<sources>, <assets>, <current_brief>, <new_answers>) et construisent la réponse à partir de ce que
l'équipe a fourni : nom, langues, description, fiche App Store, captures, réponses. La marque de démo
Habitudo (brands/habitudo.json) a une fiche écrite à la main, plus riche.
"""

from __future__ import annotations

import json
import re

from loopcast import llm
from loopcast.schemas import (AnalysisResult, AssetAnalysis, Feature, Localized, Objection, Persona, ProductBrief,
                              Question)


# --- Lecture du message -----------------------------------------------------------------------------------

def _text(req: llm.LLMRequest) -> str:
    return "\n".join(b.get("text", "") for b in req.content if b.get("type") == "text")


def _line(text: str, label: str) -> str:
    m = re.search(rf"^{re.escape(label)} : (.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def _section(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}(?: [^>]*)?>\n?(.*?)\n?</{tag}>", text, re.S)
    return m.group(1).strip() if m else ""


def _langs(text: str) -> list[str]:
    found = re.findall(r"\b(fr|en) :", _line(text, "Marchés visés"))
    return found or ["fr", "en"]


def _sentences(text: str) -> list[str]:
    text = re.sub(r"^[^:\n]{2,40} : ", "", text, flags=re.M)        # « Promesse (fr) : … » → « … »
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 15]


def _shot_ids(text: str) -> list[int]:
    return [int(i) for i in re.findall(r"^#(\d+) · (?:capture|fichier)", _section(text, "assets"), re.M)]


def _features(text: str) -> list[tuple[int, str]]:
    out, current = [], None
    for line in _section(text, "assets").splitlines():
        m = re.match(r"#(\d+) · ", line)
        if m:
            current = int(m.group(1))
        f = re.match(r"\s+fonctionnalité : (.+)", line)
        if f and current is not None:
            out.append((current, f.group(1).strip()))
    return out


def _store_facts(text: str) -> tuple[str, str, str]:
    """(fait de note sourcé, prix, catégorie) tirés de la fiche App Store, s'il y en a une."""
    sources = _section(text, "sources")
    m = re.search(r"Fiche App Store (\w+) \(relevée le ([\d/]+)\).*?Note : ([\d,]+)/5 sur ([\d ]+) notes", sources, re.S)
    rating = f"Note de {m.group(3)}/5 sur {m.group(4).strip()} notes (App Store {m.group(1)}, relevée le {m.group(2)})" if m else ""
    price = re.search(r"prix à l'achat : ([^·\n]+)", sources)
    category = re.search(r"catégories : ([^·\n,]+)", sources) or re.search(r"^Catégorie : (.+)$", text, re.M)
    return rating, price.group(1).strip() if price else "", category.group(1).strip() if category else ""


def _loc(langs: list[str], fr: str, en: str) -> Localized:
    return Localized(fr=fr if "fr" in langs else "", en=en if "en" in langs else "")


# --- asset.describe ----------------------------------------------------------------------------------------------

_HABITUDO_SCREENS = [
    ("aujourd'hui : les 3 habitudes du jour",
     "Fond clair, titre « Aujourd'hui » en haut. Trois cartes arrondies (Sport, Lecture, Boire de l'eau) avec une "
     "case à cocher violette ; deux sont cochées. Barre d'onglets en bas.",
     "cocher ses habitudes du soir en un geste", ["Aujourd'hui", "Sport", "Lecture", "Boire de l'eau"]),
    ("série de jours",
     "Un grand compteur « 12 jours » au centre, une flamme violette au-dessus, et une rangée de 7 pastilles pour "
     "la semaine, toutes remplies sauf la dernière.", "voir sa série grandir et ne pas vouloir la casser",
     ["12 jours", "Ta meilleure série"]),
    ("rappel du soir",
     "Écran de réglage avec un interrupteur « Rappel » activé et une heure choisie, 21:00, dans une roue de "
     "sélection.", "être rappelé le soir, au moment où on scrolle", ["Rappel", "21:00"]),
    ("ajout d'une habitude",
     "Une feuille qui monte du bas : champ « Nouvelle habitude », suggestions en pastilles (Méditer, Marcher, "
     "Écrire) et un bouton violet « Ajouter ».", "choisir ses 3 habitudes", ["Nouvelle habitude", "Ajouter"]),
    ("statistiques du mois",
     "Un calendrier du mois où chaque jour validé est une pastille violette, et un pourcentage de régularité "
     "en haut.", "suivre sa régularité sur le mois", ["Octobre", "86 %"]),
]

_GENERIC_SCREENS = [
    ("écran d'accueil", "L'écran principal de {name} : un titre en haut, des cartes empilées avec le contenu du "
     "jour et une barre d'onglets en bas. Interface claire, une couleur d'accent.", "voir l'essentiel d'un coup "
     "d'œil"),
    ("parcours de bienvenue", "Un écran d'introduction : illustration au centre, une phrase d'accroche sur {name} "
     "et un bouton « Continuer » en bas.", "comprendre l'app en quelques secondes"),
    ("détail d'un élément", "Une page de détail avec un titre, une image, quelques informations et un bouton "
     "d'action principal.", "aller au bout de l'action principale"),
    ("statistiques", "Un graphique de progression sur la semaine et un chiffre clé en grand au-dessus.",
     "suivre ses progrès"),
    ("réglages", "Une liste de réglages avec des interrupteurs, dont les notifications activées.",
     "régler l'app à son rythme"),
]


@llm.demo_responder("asset.describe")
def describe_asset(req: llm.LLMRequest) -> AssetAnalysis:
    text = _text(req)
    name = re.sub(r" \(marchés.*$", "", _line(text, "App")) or "l'app"
    found = re.search(r"asset #(\d+)", text)
    asset_id = int(found.group(1)) if found else 0
    caption = _line(text, "Légende")
    store_visual = "visuel de la fiche App Store" in text
    if "extraites, dans l'ordre, d'une vidéo" in text:
        return AssetAnalysis(
            screen="démo : accueil → action principale → résultat",
            shows=f"Une démo de {name} filmée sur iPhone : on part de l'accueil, on touche l'action principale, "
                  "puis l'écran de résultat s'affiche avec une petite animation.",
            feature=caption or "le parcours principal de l'app", on_screen_text=[name],
            usable_in_video=True, caution="")
    if name.lower() == "habitudo":
        screen, shows, feature, texts = _HABITUDO_SCREENS[asset_id % len(_HABITUDO_SCREENS)]
    else:
        screen, shows, feature = _GENERIC_SCREENS[asset_id % len(_GENERIC_SCREENS)]
        shows, texts = shows.format(name=name), [name]
    if store_visual:
        screen, shows = f"visuel App Store : {screen}", f"Accroche marketing en haut, téléphone dessiné dessous. {shows}"
    return AssetAnalysis(screen=screen, shows=shows, feature=caption or feature, on_screen_text=texts,
                         usable_in_video=not store_visual,
                         caution="visuel marketing : texte d'accroche incrusté, à recadrer" if store_visual else "")


# --- app.analyze -------------------------------------------------------------------------------------------------

def _habitudo(langs: list[str], shots: list[int], rating: str, price: str) -> ProductBrief:
    def shot(i: int) -> list[int]:
        return shots[i:i + 1]

    return ProductBrief(
        app_name="Habitudo",
        one_liner=_loc(langs, "3 habitudes, une coche par soir : la série que tu n'auras pas envie de casser.",
                       "3 habits, one check a night: a streak you won't want to break."),
        category="suivi d'habitudes",
        problem="On prend de bonnes résolutions le dimanche soir et on lâche le mercredi : les apps d'habitudes "
                "demandent trop, on culpabilise, et on finit par scroller au lit au lieu de s'y tenir.",
        solution="Habitudo limite le suivi à 3 habitudes et à un seul geste par soir : une coche. La série de jours "
                 "qui grandit donne envie de continuer, sans tableau de bord à remplir.",
        value_props=["Tenir ses habitudes en 10 secondes par soir", "Une série de jours qui motive à ne pas lâcher",
                     "3 habitudes, pas 30 : rien à gérer, rien à culpabiliser",
                     "Un rappel le soir, au moment où on traîne sur son téléphone"],
        features=[
            Feature(name="La coche du soir", benefit="Valider sa journée en un geste",
                    proof="Filmer le pouce qui coche les 3 habitudes et l'animation de validation", asset_ids=shot(0)),
            Feature(name="La série", benefit="Voir ses jours d'affilée et ne pas vouloir casser la chaîne",
                    proof="Montrer le compteur qui passe de 11 à 12 jours", asset_ids=shot(1)),
            Feature(name="Le rappel du soir", benefit="Ne pas oublier, sans y penser",
                    proof="Montrer la notification de 21 h sur l'écran verrouillé", asset_ids=shot(2)),
        ],
        personas=[
            Persona(name="Étudiante qui veut reprendre le sport",
                    description="20 ans, en licence : pleine de résolutions le dimanche, débordée dès le mercredi.",
                    pains=["abandonne ses résolutions au bout de 3 jours", "trouve les apps d'habitudes trop compliquées"],
                    desires=["se sentir régulière", "voir ses progrès sans effort"],
                    triggers=["le dimanche soir, quand elle organise sa semaine", "au lit, téléphone en main, à 23 h"],
                    langs=list(langs)),
            Persona(name="Jeune actif qui scrolle trop le soir",
                    description="27 ans, premier CDI : rentre fatigué et culpabilise de finir la soirée sur TikTok.",
                    pains=["culpabilise de scroller le soir", "n'arrive pas à lire ni à bouger régulièrement"],
                    desires=["reprendre la main sur ses soirées", "une routine simple qui tient"],
                    triggers=["en rentrant du travail", "quand il se rend compte qu'il est minuit"],
                    langs=list(langs)),
        ],
        differentiators=["Volontairement limitée à 3 habitudes", "Un seul geste par jour, le soir"],
        competitors=["Habitica", "Streaks", "un carnet papier", "les rappels de l'iPhone"],
        objections=[
            Objection(objection="Encore une app d'habitudes que je vais abandonner",
                      answer="Justement : 3 habitudes et une coche par soir, c'est fait pour ceux qui abandonnent."),
            Objection(objection="Je n'ai pas le temps", answer="Dix secondes par soir, rappel compris."),
        ],
        proof_points=[rating] if rating else [],
        pricing=f"{price} (App Store) ; achats intégrés : non précisé" if price
        else "Gratuit au téléchargement d'après le fichier de marque ; offre payante : non précisée",
        tone="Direct, complice, tutoiement, jamais moralisateur",
        do_not_say=["Promettre un changement de vie ou un résultat garanti",
                    "Citer un nombre d'utilisateurs ou une note sans source", "Culpabiliser le spectateur"],
        cta=_loc(langs, "Télécharge Habitudo et coche ta première journée ce soir",
                 "Get Habitudo and check off your first day tonight"),
        keywords=_loc(langs, "habitudes, routine, motivation, bonnes résolutions, discipline",
                      "habit tracker, routine, streak, motivation, self improvement"),
        unknowns=["Prix et contenu de l'offre premium", "Note et nombre d'avis sur l'App Store",
                  "Public prioritaire (étudiants ou jeunes actifs)"],
        confidence=0.55,
    )


def _generic(name: str, langs: list[str], text: str, rating: str, price: str, category: str) -> ProductBrief:
    lines = _sentences(_section(text, "team_description")) or _sentences(_section(text, "sources"))
    promise = lines[0][:160] if lines else f"{name} rend son usage principal simple et rapide."
    features = _features(text)[:4]
    return ProductBrief(
        app_name=name,
        one_liner=_loc(langs, promise, f"{name}: the simplest way to get it done, right from your phone."),
        category=category or "app mobile",
        problem=lines[1] if len(lines) > 1 else f"Sans {name}, la tâche que l'app simplifie prend du temps et de "
                                                "l'énergie (à préciser avec l'équipe).",
        solution=lines[2] if len(lines) > 2 else f"{name} réunit l'essentiel dans une interface simple, sur le téléphone.",
        value_props=[f"{feature[0].upper()}{feature[1:]}" for _id, feature in features] or [promise],
        features=[Feature(name=f"{feature[0].upper()}{feature[1:60]}", benefit=f"Pouvoir {feature}",
                          proof=f"Montrer la capture #{i}", asset_ids=[i]) for i, feature in features],
        personas=[Persona(name=f"Utilisateur pressé qui découvre {name}",
                          description="Veut un résultat rapide sans apprendre une nouvelle app.",
                          pains=["manque de temps", "apps trop compliquées"], desires=["aller droit au but"],
                          triggers=["quand le besoin se présente dans la journée"], langs=list(langs))],
        differentiators=[], competitors=[],
        objections=[Objection(objection="Encore une app à installer",
                              answer=f"{name} se prend en main en quelques secondes.")],
        proof_points=[rating] if rating else [],
        pricing=f"{price} (App Store) ; achats intégrés : non précisé" if price else "Non précisé",
        tone="Clair, direct et chaleureux (à confirmer)",
        do_not_say=["Chiffres non sourcés", "Promesse de résultat garanti"],
        cta=_loc(langs, f"Télécharge {name}", f"Download {name}"),
        keywords=_loc(langs, f"{name.lower()}, {category or 'application'}", f"{name.lower()}, {category or 'app'}"),
        unknowns=["Public prioritaire", "Prix et offre payante", "Ce qui distingue l'app de ses concurrents"],
        confidence=0.35 if not rating else 0.5,
    )


def _questions(name: str, price: str) -> list[Question]:
    out = []
    if not price or price.lower() in ("gratuit", "free", "0"):
        out.append(Question(
            question=f"{name} a-t-il une offre payante (abonnement ou achat unique) ? Si oui, à quel prix ?",
            why="On ne peut pas écrire « gratuit » dans les vidéos s'il y a un paywall, et le prix change les "
                "objections à traiter.", kind="text", options=[], priority="bloquante"))
    out += [
        Question(question="Quel public vise-t-on en priorité pour démarrer ?",
                 why="Les situations, les accroches et la voix de chaque compte en dépendent.", kind="choice",
                 options=["Étudiants (18-24 ans)", "Jeunes actifs (25-34 ans)", "Les deux à égalité"],
                 priority="bloquante"),
        Question(question="Y a-t-il des chiffres réels qu'on peut citer (utilisateurs, note, résultats) ?",
                 why="Une preuve chiffrée renforce une vidéo, mais on n'en cite aucune sans source.",
                 kind="text", options=[], priority="utile"),
        Question(question="Y a-t-il des écrans ou des fonctionnalités à ne pas montrer (bêta, bug connu, données) ?",
                 why="Évite de promettre ou de montrer ce qui n'est pas prêt.", kind="text", options=[],
                 priority="utile"),
    ]
    return out


@llm.demo_responder("app.analyze")
def analyze(req: llm.LLMRequest) -> AnalysisResult:
    text = _text(req)
    name = _line(text, "Nom") or "l'app"
    langs = _langs(text)
    rating, price, category = _store_facts(text)
    if _line(text, "Identifiant") == "habitudo":
        brief = _habitudo(langs, _shot_ids(text), rating, price)
    else:
        brief = _generic(name, langs, text, rating, price, category)
    return AnalysisResult(brief=brief, questions=_questions(name, price))


# --- app.refine --------------------------------------------------------------------------------------------------

_PRICE = ("prix", "payant", "abonnement", "gratuit", "premium", "offre")
_PROOF = ("chiffre", "note", "utilisateur", "avis", "téléchargement")
_HIDE = ("ne pas montrer", "à ne pas", "éviter", "jamais")
_AUDIENCE = ("public", "cible", "profil")


def _answers(section: str) -> list[tuple[str, str]]:
    pairs, question = [], None
    for line in section.splitlines():
        m = re.match(r"Q\d+ \(tour \d+, \w+\) : (.+)$", line)
        if m:
            question = m.group(1)
        elif question and line.startswith("R : "):
            answer = line[4:].strip()
            if not answer.startswith("("):            # « (passée par l'équipe…) »
                pairs.append((question, answer))
            question = None
    return pairs


@llm.demo_responder("app.refine")
def refine(req: llm.LLMRequest) -> AnalysisResult:
    text = _text(req)
    brief = ProductBrief.model_validate(json.loads(_section(text, "current_brief")))
    pairs = _answers(_section(text, "new_answers"))
    for question, answer in pairs:
        q = question.lower()
        if any(w in q for w in _PRICE):
            brief.pricing = f"{answer} (réponse de l'équipe)"
            if "gratuit" not in answer.lower():
                brief.do_not_say.append("Dire que l'app est entièrement gratuite")
        elif any(w in q for w in _PROOF):
            if re.search(r"\d", answer):
                brief.proof_points.append(f"{answer} (réponse de l'équipe)")
        elif any(w in q for w in _HIDE):
            brief.do_not_say.append(f"Montrer : {answer}")
        elif any(w in q for w in _AUDIENCE) and brief.personas:
            brief.personas[0].description += f" Public prioritaire d'après l'équipe : {answer}."
        words = {w for w in re.findall(r"\w{5,}", q)}
        brief.unknowns = [u for u in brief.unknowns if not words & set(re.findall(r"\w{5,}", u.lower()))]
    brief.confidence = round(min(0.9, brief.confidence + 0.1 * len(pairs)), 2)
    return AnalysisResult(brief=brief, questions=[])
