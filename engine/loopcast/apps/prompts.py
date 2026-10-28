"""Ce qu'on dit à Claude pour comprendre une app : consignes (stables, mises en cache) et messages.

Trois tâches :
- asset.describe : regarder une capture (ou des images extraites d'une vidéo de démo) → AssetAnalysis ;
- app.analyze    : tout ce qu'on sait de l'app → fiche produit + questions (AnalysisResult) ;
- app.refine     : fiche + réponses de l'équipe → fiche mise à jour (+ questions bloquantes restantes).

Les consignes sont en français ; les sections du message sont balisées (<app>, <sources>…) pour que
Claude sache d'où vient chaque information et puisse la citer. Le savoir-faire partagé de l'équipe
(engine/loopcast/knowledge/playbook.md, s'il existe) est lu au moment de l'appel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from loopcast.llm import text_block

PLAYBOOK = Path(__file__).resolve().parents[1] / "knowledge" / "playbook.md"

KIND_LABELS = {"screenshot": "capture", "logo": "logo", "demo_video": "vidéo de démo", "document": "document",
               "other": "fichier"}
ORIGIN_LABELS = {"upload": "fournie par l'équipe", "appstore": "visuel de la fiche App Store",
                 "brand": "fichier de marque"}
SOURCE_LABELS = {"appstore": "fiche App Store", "playstore": "fiche Google Play", "website": "site web",
                 "text": "texte fourni par l'équipe"}
BRIEF_ORIGINS = {"analyze": "rédigée par l'analyse", "refine": "affinée avec les réponses de l'équipe",
                 "edit": "modifiée à la main par l'équipe"}
MARKETS = {"fr": "fr : français (France et pays francophones)", "en": "en : anglais (États-Unis et pays anglophones)"}
LANG_NAMES = {"fr": "français", "en": "anglais"}


# --- Consignes (prompts système) ------------------------------------------------------------------------

DESCRIBE_SYSTEM = """\
Tu es le regard d'une équipe marketing qui fait connaître des apps mobiles par des vidéos courtes \
(TikTok, Instagram Reels). On te montre une image fournie pour une app : une capture d'écran, un visuel \
de la fiche App Store, ou quelques images extraites d'une vidéo de démo enregistrée sur iPhone. Ta \
description sera lue par un stratège et par un monteur qui ne voient pas l'image : ils décideront à \
partir d'elle quelle fonctionnalité montrer, et si l'image peut passer telle quelle à l'écran.

Règles :
- Décris ce qui est visible, pas ce que tu supposes. Si un élément est ambigu, dis-le (« semble être… »).
- `screen` : l'écran en quelques mots (« accueil », « liste du jour », « statistiques », « paywall », \
« onboarding », « réglages »…). Pour un visuel de fiche App Store (accroche marketing, téléphone \
dessiné), commence par « visuel App Store : » puis l'écran montré dans le téléphone. Pour une vidéo, \
les écrans traversés dans l'ordre.
- `shows` : ce qu'on voit concrètement, de haut en bas : éléments d'interface, données affichées, état \
(vide, rempli, erreur), style (couleurs dominantes, clair ou sombre). Deux à quatre phrases. Pour une \
vidéo : l'enchaînement des gestes et de ce qui change à l'écran.
- `feature` : la fonctionnalité illustrée, du point de vue de l'utilisateur (« voir sa série de jours », \
« être rappelé le soir »). Vide si l'image n'en montre aucune (logo, chargement).
- `on_screen_text` : les textes importants recopiés exactement, dans leur langue (titre, accroche, \
chiffres, boutons, prix). Jamais la barre d'état (heure, réseau, batterie). Douze au plus.
- `usable_in_video` : vrai seulement si l'image peut être montrée telle quelle dans une vidéo publique : \
lisible, nette, sans donnée personnelle réelle (nom, photo, e-mail, numéro, message privé), sans bug \
visible, sans contenu de test.
- `caution` : ce qui pose problème, précisément (« prénom et photo d'une vraie personne en haut à \
droite », « texte de test "Lorem ipsum" », « capture floue »). Signale aussi un prix, une promotion ou \
une date visibles : ils vieilliront. Vide si rien.
- Écris en français, sauf les textes recopiés."""

_ROLE = """\
Tu es un stratège marketing senior, spécialiste de la croissance des apps mobiles par le contenu court \
(TikTok, Instagram Reels). Tu as fait grandir des apps grand public avec des comptes organiques : tu sais \
qu'une vidéo marche quand elle part d'une situation que le spectateur reconnaît en deux secondes, et \
qu'une app se vend par un bénéfice concret montré à l'écran, pas par une liste de fonctionnalités.

Tu travailles pour une petite équipe qui fait connaître ses propres apps : des vidéos publiées chaque \
jour, en français et en anglais, depuis cinq iPhones (un compte TikTok et un compte Instagram par \
téléphone, chacun avec sa voix). Les vidéos montrent de vraies captures de l'app, des formats animés \
(note qui s'écrit, conversation, carrousel) et parfois de la vidéo générée. Avant la moindre vidéo, il \
faut comprendre le produit mieux que personne : c'est le rôle de la fiche produit, la source de vérité \
de la stratégie et de chaque script."""

_GOLDEN_RULE = """\
## Règle d'or : des faits sourcés, jamais inventés
- Chaque affirmation vient des éléments fournis : description de l'équipe, réponses de l'équipe, fiches \
App Store et Google Play, site, textes, documents, captures. Tu peux reformuler et déduire l'évident \
(une app d'habitudes sert à tenir des habitudes) ; tu n'inventes ni fonctionnalité, ni chiffre, ni \
note, ni avis, ni nombre d'utilisateurs ou de téléchargements, ni prix, ni récompense, ni témoignage, \
ni partenariat, ni étude.
- `proof_points` : uniquement des faits vérifiables, chacun avec sa source entre parenthèses, par exemple \
« Note de 4,7/5 sur 1 240 notes (App Store FR, relevée le 29/10/2026) » ou « Gratuit sans publicité \
(réponse de l'équipe) ». Rien de vérifiable : liste vide.
- Ce qui manque va dans `unknowns`, formulé comme un manque (« Prix de l'abonnement premium ») ; si la \
réponse change la stratégie, c'est aussi une question.
- Contradiction entre sources : les réponses de l'équipe priment, puis sa description, puis la fiche \
App Store la plus récente, puis le site. Signale la contradiction dans `unknowns`.
- Une fonctionnalité n'entre dans `features` que si une source ou une capture la montre : ce que l'app \
pourrait faire n'existe pas."""

_BRIEF_GUIDE = """\
## Ce qui fait une bonne fiche pour la vidéo courte
- `one_liner` : la promesse en une phrase qu'on pourrait dire face caméra, concrète et désirable, pas un \
slogan creux (« Tiens 3 habitudes sans y penser : une coche par soir », pas « L'app qui change ta vie »).
- `category` : la catégorie telle qu'un utilisateur la nommerait (« suivi d'habitudes »).
- `problem` : le problème tel que l'utilisateur le vit et le dirait, dans une situation précise. \
`solution` : comment l'app le règle, concrètement.
- `value_props` : 3 à 5 bénéfices, du plus fort au plus faible, formulés comme ce que l'utilisateur \
gagne (pas comme des fonctionnalités).
- `features` : les fonctionnalités qui comptent pour la vidéo, chacune avec son bénéfice et sa preuve à \
l'écran (`proof` : quel écran montrer, quel geste filmer). `asset_ids` : uniquement des ids de la liste \
des fichiers fournie, ceux qui la montrent le mieux ; liste vide sinon.
- `personas` : 2 ou 3 profils vraiment différents, nommés de façon parlante (« Étudiante qui révise la \
veille »), avec leurs douleurs, leurs envies et surtout leurs `triggers` : les moments précis où l'app \
leur sert (ce sont les futures accroches). `langs` : les marchés visés où ce profil existe.
- `differentiators` : ce qui distingue l'app des alternatives, vérifiable dans le produit. \
`competitors` : les alternatives que l'utilisateur envisage vraiment (apps connues de la catégorie, \
celles citées dans les sources, mais aussi « un carnet papier », « les rappels de l'iPhone ») ; aucune \
affirmation chiffrée sur elles.
- `objections` : les vraies raisons de ne pas télécharger (« encore une app de plus », « c'est payant », \
« pas le temps ») et une réponse appuyée sur le produit.
- `pricing` : exactement ce qu'on sait (« Gratuit au téléchargement ; achats intégrés : prix non \
précisé »). Jamais deviné. Une fiche App Store ne dit pas s'il y a un abonnement : ne le suppose pas.
- `tone` : la voix de la marque, d'après l'équipe ou les textes de l'app.
- `do_not_say` : ce qu'on ne promet ni ne montre jamais : résultat garanti, allégation de santé ou \
financière, « gratuit » s'il y a un paywall, chiffre non sourcé, faux avis ou faux témoignage, \
dénigrement d'un concurrent, données personnelles visibles sur une capture, fonctionnalité pas encore \
sortie.
- `cta` : l'appel à l'action de fin de vidéo, court et naturel.
- `keywords` : ce que les gens tapent dans la recherche TikTok ou App Store, séparés par des virgules.
- `confidence` : sois calibré. Vers 0,3 avec une simple description, 0,6 avec une fiche App Store et des \
captures décrites, 0,8 et plus quand l'équipe a répondu aux questions bloquantes.

## Langues
- `one_liner`, `cta` et `keywords` sont écrits dans la langue de chaque marché visé, comme un natif \
l'écrirait sur TikTok (pas une traduction mot à mot) ; pour un marché non visé, chaîne vide.
- Tous les autres champs sont en français : c'est la langue de travail de l'équipe."""

_QUESTIONS_GUIDE = """\
## Les questions à l'équipe
- Seulement celles dont la réponse change le positionnement, la promesse, la cible, le ton, ce qu'on a le \
droit de dire ou de montrer. Idéalement 3 à 5, jamais plus de 8 ; aucune si la fiche est solide.
- Jamais une question dont la réponse est dans les éléments fournis, ni une question déjà posée (qu'elle \
ait été répondue ou passée). Jamais de question générique (« Quels sont vos objectifs ? »).
- Une question = un seul sujet, précise, à laquelle on répond en une ligne. Donne ton hypothèse quand \
tu en as une (« Le public principal est-il bien les étudiants de 18 à 25 ans ? »). Préfère `choice` (une \
réponse) ou `multi` (plusieurs) avec des `options` concrètes quand les réponses possibles sont connues ; \
sinon `text`, avec `options` vide.
- `why` : ce que la réponse change concrètement dans les vidéos.
- `priority` : « bloquante » si, sans la réponse, on risque une promesse fausse, une vidéo interdite ou \
une cible ratée ; « utile » sinon. Les bloquantes d'abord."""

ANALYZE_SYSTEM = f"""{_ROLE}

## Ta mission
À partir de tout ce qu'on te donne sur une app, rédiger sa fiche produit et poser les quelques questions \
dont les réponses changeraient vraiment la stratégie. Si une fiche existe déjà, tu la reprends et la \
corriges avec les nouveaux éléments : ce que l'équipe y a modifié à la main fait foi.

{_GOLDEN_RULE}

{_BRIEF_GUIDE}

{_QUESTIONS_GUIDE}"""

REFINE_SYSTEM = f"""{_ROLE}

## Ta mission
L'équipe vient de répondre à tes questions. Tu mets la fiche produit à jour avec ses réponses.
- Les réponses de l'équipe font foi : elles priment sur les sources et sur la version précédente. \
Intègre chacune partout où elle compte (une réponse sur le prix change `pricing`, souvent `objections` \
et `do_not_say`, parfois `one_liner`).
- Garde tout ce que la version précédente avait de juste ; ce que l'équipe y a modifié à la main fait foi \
aussi. Ne réécris pas pour le plaisir de réécrire.
- Retire de `unknowns` ce qui est résolu et mets `confidence` à jour.
- Une question passée par l'équipe n'est pas reposée : le point reste dans `unknowns` et la fiche adopte \
l'hypothèse la plus prudente.
- Une réponse de l'équipe est une source : un fait qu'elle donne peut entrer dans `proof_points` avec \
« (réponse de l'équipe) ».
- De nouvelles questions seulement si une information bloquante manque encore, dans la limite donnée \
avec le message ; sinon `questions` est vide.

{_GOLDEN_RULE}

{_BRIEF_GUIDE}

{_QUESTIONS_GUIDE}"""


def playbook(max_chars: int = 40_000) -> str:
    """Le savoir-faire partagé (écrit à part), lu à chaque appel ; vide s'il n'existe pas encore."""
    try:
        text = PLAYBOOK.read_text().strip()
    except OSError:
        return ""
    return cut(text, max_chars)


def system_prompt(task: str) -> str:
    base = {"asset.describe": DESCRIBE_SYSTEM, "app.analyze": ANALYZE_SYSTEM, "app.refine": REFINE_SYSTEM}[task]
    know = playbook() if task != "asset.describe" else ""
    if not know:
        return base
    return f"{base}\n\n## Savoir-faire de l'équipe (à appliquer)\n<playbook>\n{know}\n</playbook>"


# --- Ce qu'on sait de l'app ------------------------------------------------------------------------------

@dataclass
class Material:
    app: dict
    sources: list[dict] = field(default_factory=list)      # sources lisibles (avec du texte)
    assets: list[dict] = field(default_factory=list)       # tous les fichiers, analyse décodée
    questions: list[dict] = field(default_factory=list)    # toutes les questions déjà posées
    brief: dict | None = None                              # dernière version de la fiche

    @property
    def asset_ids(self) -> list[int]:
        return [a["id"] for a in self.assets]


def cut(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    return text[: cut if cut > limit * 0.8 else limit].rstrip() + "\n[…]"


def _attr(value: object) -> str:
    return str(value).replace('"', "'").replace("\n", " ")


def app_block(app: dict) -> str:
    brand = app.get("brand") or {}
    look = []
    if brand.get("accent"):
        look.append(f"couleur d'accent {brand['accent']}")
    if brand.get("handle"):
        look.append(f"compte {brand['handle']}")
    for lang, line in (brand.get("storeLine") or {}).items():
        look.append(f"mention de fin ({lang}) « {line} »")
    lines = [
        f"Identifiant : {app['id']}",
        f"Nom : {app['name']}",
        f"Marchés visés : {' ; '.join(MARKETS.get(lang, lang) for lang in app['langs'])}",
        f"Lien App Store : {app.get('store_url_ios') or '(aucun)'}",
        f"Lien Google Play : {app.get('store_url_android') or '(aucun)'}",
        f"Site : {app.get('website_url') or '(aucun)'}",
    ]
    if look:
        lines.append(f"Identité : {', '.join(look)}")
    return "<app>\n" + "\n".join(lines) + "\n</app>"


def team_block(app: dict) -> str:
    text = (app.get("description") or "").strip() or "(l'équipe n'a pas encore écrit de description)"
    return f"<team_description>\n{text}\n</team_description>"


def sources_block(sources: list[dict], *, max_total: int) -> str:
    if not sources:
        return "<sources>\n(aucune source lue)\n</sources>"
    share = max(2_000, max_total // len(sources))
    parts = []
    for s in sources:
        attrs = [f'id="{s["id"]}"', f'type="{SOURCE_LABELS.get(s["kind"], s["kind"])}"']
        if s.get("url"):
            attrs.append(f'url="{_attr(s["url"])}"')
        if s.get("kind") == "text" and s.get("title"):
            attrs.append(f'titre="{_attr(s["title"])}"')
        if s.get("fetched_at"):
            attrs.append(f'lue_le="{s["fetched_at"][:10]}"')
        parts.append(f"<source {' '.join(attrs)}>\n{cut(s.get('content') or '', share)}\n</source>")
    return "<sources>\n" + "\n".join(parts) + "\n</sources>"


def asset_line(a: dict) -> str:
    head = [f"#{a['id']}", KIND_LABELS.get(a["kind"], a["kind"]), ORIGIN_LABELS.get(a.get("origin") or "upload", "")]
    if a.get("width"):
        head.append(f"{a['width']}×{a['height']}")
    if a.get("duration_s"):
        head.append(f"{a['duration_s']:.0f} s")
    if a.get("filename") and a["kind"] in ("document", "demo_video", "other"):
        head.append(f"« {a['filename']} »")
    lines = [" · ".join(h for h in head if h)]
    if a.get("caption"):
        lines.append(f"  légende : {a['caption']}")
    an = a.get("analysis")
    if an:
        lines.append(f"  écran : {an.get('screen', '')} — {an.get('shows', '')}")
        if an.get("feature"):
            lines.append(f"  fonctionnalité : {an['feature']}")
        if an.get("on_screen_text"):
            lines.append(f"  textes : {' | '.join(an['on_screen_text'][:12])}")
        usable = "oui" if an.get("usable_in_video") else "non"
        lines.append(f"  montrable telle quelle : {usable}" + (f" — attention : {an['caution']}" if an.get("caution") else ""))
    elif a["kind"] in ("screenshot", "demo_video"):
        lines.append("  (pas encore décrite)")
    return "\n".join(lines)


def assets_block(assets: list[dict]) -> str:
    if not assets:
        return "<assets>\n(aucun fichier fourni)\n</assets>"
    return "<assets>\n" + "\n".join(asset_line(a) for a in assets) + "\n</assets>"


def qa_lines(questions: list[dict]) -> list[str]:
    lines = []
    for q in questions:
        lines.append(f"Q{q['id']} (tour {q['round']}, {q['priority']}) : {q['question']}")
        if q["status"] == "answered":
            lines.append(f"R : {q['answer']}")
        elif q["status"] == "skipped":
            lines.append("R : (passée par l'équipe : ne pas la reposer)")
        else:
            lines.append("R : (pas encore de réponse : ne pas la reposer)")
    return lines


def answers_block(questions: list[dict], tag: str = "team_answers") -> str:
    if not questions:
        return ""
    return f"<{tag}>\n" + "\n".join(qa_lines(questions)) + f"\n</{tag}>"


def brief_block(row: dict) -> str:
    attrs = (f'version="{row["version"]}" origine="{BRIEF_ORIGINS.get(row.get("origin") or "analyze", "")}" '
             f'approuvee="{"oui" if row.get("approved_at") else "non"}"')
    return f"<current_brief {attrs}>\n{json.dumps(row['brief'], ensure_ascii=False, indent=1)}\n</current_brief>"


def _language_rule(langs: list[str]) -> str:
    targeted = [lang for lang in ("fr", "en") if lang in langs]
    other = [lang for lang in ("fr", "en") if lang not in langs]
    rule = (f"Marchés visés : {', '.join(targeted)}. `one_liner`, `cta` et `keywords` sont écrits nativement en "
            f"{' et en '.join(LANG_NAMES[lang] for lang in targeted)}")
    if other:
        rule += f" ; leur champ `{other[0]}` reste vide (marché non visé)"
    return rule + ". Tous les autres champs sont en français."


def _asset_rule(m: Material) -> str:
    ids = ", ".join(f"#{i}" for i in m.asset_ids)
    return f"`asset_ids` : uniquement parmi {ids}." if ids else "Aucun fichier fourni : `asset_ids` restent vides."


# --- Messages -----------------------------------------------------------------------------------------------

def describe_content(app: dict, asset: dict, images: list[dict], frame_times: list[float] | None = None) -> list[dict]:
    """Le message pour décrire un asset : contexte, image(s), consigne."""
    context = [f"App : {app['name']} (marchés : {', '.join(app['langs'])})"]
    if (app.get("description") or "").strip():
        context.append(f"Ce que l'équipe dit de l'app : {cut(app['description'], 1_500)}")
    size = f", {asset['width']}×{asset['height']}" if asset.get("width") else ""
    context.append(f"Fichier : asset #{asset['id']}, {KIND_LABELS.get(asset['kind'], asset['kind'])}, "
                   f"{ORIGIN_LABELS.get(asset.get('origin') or 'upload', '')}{size}")
    if asset.get("caption"):
        context.append(f"Légende : {asset['caption']}")
    if frame_times:
        times = ", ".join(f"{t:.1f}".replace(".", ",") for t in frame_times)
        ask = (f"Ces {len(frame_times)} images sont extraites, dans l'ordre, d'une vidéo de démo de "
               f"{asset.get('duration_s') or 0:.0f} s (à {times} s). Décris le parcours qu'elle montre.")
    else:
        ask = "Décris cette image."
    return [text_block("\n".join(context)), *images, text_block(ask)]


def analysis_content(m: Material, *, images: list[tuple[dict, dict]], documents: list[tuple[dict, dict | str]],
                     max_source_chars: int, max_questions: int = 8) -> list[dict]:
    """Le message de l'analyse : tout ce qu'on sait, une sélection de captures, les documents."""
    parts = ["Voici tout ce que nous savons de l'app.", app_block(m.app), team_block(m.app),
             sources_block(m.sources, max_total=max_source_chars * 3)]
    asked = [q for q in m.questions if q["status"] in ("answered", "skipped")]
    if asked:
        parts.append(answers_block(asked))
    if m.brief:
        parts.append("Une fiche existe déjà : reprends-la, garde ce qui reste juste (surtout ce que l'équipe a "
                     "modifié à la main) et corrige-la avec les éléments ci-dessus.\n" + brief_block(m.brief))
    parts.append(assets_block(m.assets))
    blocks = [text_block("\n\n".join(parts))]
    if images:
        blocks.append(text_block(f"Les {len(images)} captures les plus parlantes, chacune précédée de son id :"))
        for asset, image in images:
            screen = (asset.get("analysis") or {}).get("screen")
            blocks.append(text_block(f"Capture #{asset['id']}" + (f" ({screen})" if screen else "")))
            blocks.append(image)
    for asset, doc in documents:
        if isinstance(doc, str):
            blocks.append(text_block(f'<document id="{asset["id"]}" nom="{_attr(asset["filename"])}">\n{doc}\n</document>'))
        else:
            blocks.append(text_block(f"Document #{asset['id']} « {asset['filename']} » :"))
            blocks.append(doc)
    rules = [
        "Rédige maintenant la fiche produit et les questions.",
        f"- {_language_rule(m.app['langs'])}",
        f"- {_asset_rule(m)}",
        f"- Au plus {max_questions} questions, les bloquantes d'abord ; aucune déjà posée.",
        "- Rien d'inventé : ce qui manque va dans `unknowns`.",
    ]
    blocks.append(text_block("\n".join(rules)))
    return blocks


def refine_content(m: Material, *, base: dict, round_questions: list[dict], round_no: int, max_rounds: int,
                   max_new: int, max_source_chars: int) -> list[dict]:
    """Le message d'affinage : la fiche, les réponses du tour, le contexte utile (sans les images)."""
    round_ids = {q["id"] for q in round_questions}
    earlier = [q for q in m.questions if q["id"] not in round_ids and q["status"] in ("answered", "skipped")]
    parts = [f"L'équipe vient de répondre au tour de questions n°{round_no}. Mets la fiche produit à jour.",
             app_block(m.app), brief_block(base), answers_block(round_questions, "new_answers")]
    if earlier:
        parts.append(answers_block(earlier, "earlier_answers"))
    parts += [team_block(m.app), sources_block(m.sources, max_total=max_source_chars), assets_block(m.assets)]
    if max_new > 0:
        ask = (f"- Tour {round_no} sur {max_rounds} : au plus {max_new} nouvelles questions, uniquement bloquantes "
               "et jamais déjà posées ; si rien de bloquant ne manque, `questions` est vide.")
    else:
        ask = (f"- C'était le dernier tour ({round_no} sur {max_rounds}) : `questions` est vide ; ce qui manque "
               "encore reste dans `unknowns`, avec l'hypothèse la plus prudente dans la fiche.")
    rules = ["Rends la fiche complète, mise à jour.", f"- {_language_rule(m.app['langs'])}", f"- {_asset_rule(m)}", ask]
    return [text_block("\n\n".join(parts)), text_block("\n".join(rules))]
