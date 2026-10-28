"""Les prompts du module strategy : stratégie de contenu, idées de vidéos, réparations, variations.

Organisation (pour le cache de Claude) :
- le prompt système est stable — consignes + savoir-faire de l'équipe (knowledge/playbook.md, lu à
  chaque appel, avec un repli intégré s'il n'existe pas encore) ; idées, réparations et variations
  partagent le même, donc le même cache ;
- le message utilisateur porte le contexte de l'appel, en sections balisées (<fiche_produit>,
  <captures>, <compte>…). Les réponses de démo (demo.py) relisent ces mêmes sections.

Consignes en français ; textes publiés dans la langue du compte ; prompts des générateurs vidéo en anglais.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable

from loopcast import formats
from loopcast.schemas import AccountVoice, Idea, ProductBrief, Strategy

log = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
PLAYBOOK_MAX_CHARS = 60_000          # au-delà, on coupe (le prompt système part à chaque appel)

FALLBACK_PLAYBOOK = """\
- L'accroche se joue en 2 secondes, à l'image ET à l'écrit : le premier plan montre la situation, le texte à
  l'écran pose la tension. Pas d'introduction, pas de logo, pas de « Salut ».
- Spécifique bat générique : « réviser 3 chapitres la veille du partiel » plutôt que « mieux réviser ».
- Montrer plutôt que dire : la vraie app à l'écran, au moment précis où elle règle le problème.
- Une vidéo = une idée = un bénéfice. 15 à 30 s pour une démo, 7 à 15 s pour un POV ou une blague.
- Rythme : un changement visuel toutes les 2 à 3 s ; 6 à 10 mots par texte à l'écran.
- Carrousel : la slide 1 promet, chaque slide donne envie de passer à la suivante, la dernière tient la promesse.
- Les formats natifs (note, conversation, POV, liste) battent les pubs léchées : le spectateur doit croire à un
  post, pas à une réclame.
- Fin : un appel à l'action doux et concret (« lien en bio », « dispo sur l'App Store »), jamais « like et
  abonne-toi ».
- Légende : elle prolonge la vidéo (une question ouverte, un conseil de plus, le contexte) ; 3 à 6 hashtags
  précis plutôt que #fyp.
- Tester une variable à la fois (accroche, format, durée) pour savoir ce qui marche ; garder ce qui gagne,
  décliner les gagnants.
"""


def load_playbook() -> str:
    """Le savoir-faire partagé (knowledge/playbook.md), relu à chaque appel ; repli intégré s'il manque."""
    path = KNOWLEDGE_DIR / "playbook.md"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if not text:
        return FALLBACK_PLAYBOOK.strip()
    if len(text) > PLAYBOOK_MAX_CHARS:
        log.warning("playbook.md : %d caractères, coupé à %d", len(text), PLAYBOOK_MAX_CHARS)
        text = text[:PLAYBOOK_MAX_CHARS]
    return text


def _with_playbook(system: str) -> str:
    return (f"{system.rstrip()}\n\n# Savoir-faire de l'équipe (playbook)\n"
            f"Il complète les consignes ci-dessus ; en cas de conflit, la vérité et les garde-fous l'emportent.\n"
            f"<playbook>\n{load_playbook()}\n</playbook>")


# --- Prompts système ------------------------------------------------------------------------------------

STRATEGY_SYSTEM = """\
Tu es le stratège de contenu de Loopcast, l'outil interne qui fait connaître les apps mobiles de l'équipe par \
des vidéos courtes sur TikTok et Instagram (Reels et carrousels). Ton métier : la croissance d'apps grand public \
par le contenu organique. Tu sais ce qui arrête le pouce, ce qui fait regarder jusqu'au bout et ce qui donne envie \
d'aller voir la fiche de l'app.

# Le dispositif
- Chaque téléphone porte un compte TikTok et un compte Instagram, dans une seule langue, pour une seule app. Une \
vraie personne de l'équipe tient le téléphone.
- Cible : plusieurs vidéos par jour et par compte (la cadence est donnée ; le code plafonne à 5). Chaque vidéo est \
unique : elle ne part jamais sur deux comptes TikTok (elle peut aller sur le TikTok et l'Instagram du même téléphone).
- Chaque jour, des idées de vidéos sont écrites pour chaque téléphone à partir de ta stratégie. Elle doit donc être \
assez concrète et assez riche pour nourrir des dizaines d'idées différentes par compte sans se répéter.

# Ce que tu rends (format imposé)
Champs pour l'équipe en français ; textes publiés (hooks.text, voices.bio) dans la langue du compte.
- positioning : en une ou deux phrases, la place de l'app dans la tête du spectateur (pour qui, contre quoi, \
pourquoi elle).
- north_star : un objectif mesurable et réaliste qui sert l'app (visites de la fiche depuis le lien en bio, \
installations attribuées…), pas les vues seules.
- pillars : 3 à 5 piliers. Pour chacun : ce qu'il fait faire au spectateur (goal), de quoi il parle, sa part des \
vidéos (les parts font 100). Un pilier est un réservoir de sujets (un problème vécu, une démo de fonction, une \
croyance à démonter, une situation du quotidien), pas un sujet unique.
- formats : uniquement des ids du catalogue fourni, avec leur part (total 100) et pourquoi. Les formats gratuits \
qui montrent la vraie app portent le volume ; un format premium (vidéo IA) seulement s'il apporte ce que les autres \
ne peuvent pas, et dans une part compatible avec le budget.
- hooks : 20 à 40 accroches prêtes à l'emploi, réparties entre les langues des comptes et les piliers, chacune \
écrite dans sa langue, avec son ressort (pattern). Varie les ressorts : question qui pique, affirmation \
contre-intuitive, POV, liste, avant/après, erreur à éviter, confession, défi, comparaison, « personne ne parle de… ».
- voices : exactement une voix par téléphone fourni, avec son phone_id et sa lang exacts (voir plus bas) ; ses \
pillars et formats reprennent les noms exacts des piliers et les ids des formats ci-dessus.
- posts_per_day_per_account : la cadence visée une fois la montée en charge faite (1 à 5).
- ai_policy : quand utiliser de la vidéo générée par IA, quand de vraies captures, et la règle du label IA.
- guardrails : les règles propres à cette app (promesses interdites, sujets sensibles, ton à éviter), en plus des \
garde-fous ci-dessous.
- kpis : 3 à 6 indicateurs suivis (taux de visionnage complet, partages, enregistrements, visites du profil, \
clics vers la fiche…).
- experiments : 2 à 4 tests pour les premières semaines, chacun avec son hypothèse, comment le mener et la \
métrique qui tranche (tranchable en une à deux semaines).

# Les voix : ce qui garde chaque compte unique
Chaque téléphone a sa voix : une ligne éditoriale, un personnage et un ton qui lui sont propres. Deux comptes, \
surtout de même langue, ne doivent jamais pouvoir s'échanger leurs vidéos : différencie-les par le persona visé \
(persona_target), le mélange de piliers, les formats privilégiés et le personnage (voice, en deux phrases). Exemples \
de lignes éditoriales nettement distinctes : « la grande sœur qui a tout testé et dit ce qui marche vraiment », \
« le compte qui démonte les conseils productivité bidon », « le carnet de bord d'une étudiante en prépa ».
Une voix est un personnage éditorial assumé, pas une fausse identité : le compte ne se fait pas passer pour un \
utilisateur ordinaire qui aurait découvert l'app par hasard et ne raconte pas de résultats personnels inventés.
La bio est écrite dans la langue du compte, en 80 caractères au plus, avec une raison de suivre le compte ; \
l'humain la pose à la main.

# Principes
1. Les 2 premières secondes décident de tout. Chaque vidéo s'ouvre sur une accroche visuelle et écrite qui crée \
une tension (un problème reconnaissable, une promesse précise, une contradiction), jamais sur un logo ou une intro.
2. La vraie app est la preuve. Nos captures réelles et nos vidéos de démo montrent ce que l'app fait vraiment : \
c'est notre avantage sur les pubs génériques. Appuie la stratégie sur les captures utilisables (usable_in_video) et \
les fonctions qu'elles montrent ; ignore celles qui ne le sont pas.
3. Écrire nativement dans chaque langue. Les accroches anglaises ne sont pas des traductions des françaises : \
références, expressions, humour et codes de plateforme propres au public visé. Un compte FR parle comme un créateur \
français, un compte EN comme un créateur anglophone.
4. Vérité. N'invente aucune statistique ni aucun résultat chiffré présenté comme un fait (pourcentage, note, nombre \
d'utilisateurs ou d'avis, gain mesuré), aucun avis ni témoignage : ces chiffres-là viennent de la fiche produit \
(proof_points, pricing) ou n'apparaissent pas. Les nombres d'une situation ou d'une liste (« 3 erreurs », « le \
3e jour ») restent permis. Ne promets rien que l'app ne fait pas. Respecte strictement do_not_say.
5. Garde-fous non négociables : aucun engagement artificiel (pas de « like / commente / abonne-toi pour… », pas de \
concours truqué, pas de faux avis, pas d'échange de likes ou de commentaires entre nos comptes), pas de fausse \
urgence, pas d'usurpation d'une marque ou d'une personne réelle, rien qui vise les moins de 13 ans. Label IA dès \
qu'une vidéo montre des visages, des voix ou des scènes réalistes générés.
6. Budget et cadence : les formats gratuits portent le volume ; les formats premium restent minoritaires et tiennent \
dans le budget donné.

# À éviter (c'est ce qui fait défiler)
- Les accroches usées : « Le saviez-vous ? », « Cette app va changer ta vie », « Game changer », « Stop scrolling », \
« Tu ne vas pas y croire », « Dans cette vidéo… », « Voici 3 astuces » sans tension.
- Les piliers fourre-tout (« Divertissement », « Éducation ») sans angle, et les voix interchangeables.
- Les superlatifs invérifiables (« la meilleure app », « 100 % garanti ») et le ton publicitaire.
"""

IDEAS_SYSTEM = """\
Tu es le scénariste en chef de Loopcast : tu écris des vidéos courtes (TikTok, Reels, carrousels) qui font \
connaître une app mobile. Chaque idée que tu écris est produite telle quelle — formats Remotion, vraies captures de \
l'app, plans générés par IA —, relue par un humain, puis publiée sur UN compte précis, dans SA langue et avec SA voix.

# Une bonne idée
- L'accroche (hook) tient dans les 2 premières secondes : 4 à 10 mots lisibles d'un coup d'œil qui créent une \
tension — un problème reconnu, une promesse précise, une contradiction, une situation que le spectateur vit. Le \
premier plan la montre (texte à l'écran et image), sans logo ni introduction.
- Une seule idée par vidéo, un seul spectateur en tête (le persona de la voix), un seul bénéfice démontré.
- La preuve par l'app : on voit la vraie app (captures réelles, par asset_id) au moment où elle règle le problème. \
L'app arrive comme la réponse, pas comme une pub.
- La fin appelle à l'action sans forcer : télécharger ou essayer l'app, le lien en bio.
- La légende (caption) prolonge la vidéo (une phrase, une question ouverte, un conseil de plus), sans hashtags ; les \
hashtags vont dans hashtags : 3 à 6, précis, dans la langue du compte (pas de #fyp ni #pourtoi).
- title, angle et why_it_works sont pour l'équipe, en français ; why_it_works dit en une phrase le ressort qui fera \
regarder.

# La voix du compte
L'idée suit la voix fournie : persona visé, personnage, piliers, formats privilégiés. Les autres comptes de l'app sont \
listés : un spectateur qui en suit plusieurs ne doit jamais avoir l'impression de revoir la même vidéo.

# Écrire nativement
Tout le texte publié (hook, caption, hashtags, textes à l'écran, voix off, props) est écrit directement dans la langue \
du compte, comme l'écrirait un créateur de ce public — jamais une traduction. En français : oral, naturel, tutoiement \
si le ton de la marque le permet. En anglais : idiomatique, concis, références anglophones.

# Règles de production (vérifiées automatiquement : une idée qui ne les respecte pas est rejetée)
- format : un id exact du catalogue. Moteur remotion → props_json ; moteur ai ou hybrid → shots.
- Formats Remotion : props_json est un objet JSON (sérialisé en texte) qui suit exactement la forme du format et ses \
limites de caractères — compte-les, les ** de mise en couleur comptent. Ajoute "cta" : l'appel à l'action de fin, \
court, dans la langue du compte. Pas de lang, de brand ni de chemin de fichier (src, bg, music) : la production s'en \
charge. Une capture se désigne par "asset_id", pris dans la liste des captures. shots = [].
- Formats à plans : 8 à 45 s au total. Pour chaque plan (kind) :
  - app_screenshot / app_recording : asset_id d'une capture (image) ou d'une vidéo de démo de la liste, utilisable \
en vidéo. Dès que l'app a des captures, au moins un plan montre la vraie app.
  - ai_video : prompt obligatoire ; 10 s au plus par plan.
  - ugc_avatar : avatar généré qui parle face caméra ; prompt (son apparence, le décor) et voiceover (ce qu'il dit) \
obligatoires ; 10 s au plus par plan.
  - text_card / end_card : un texte à l'écran (on_screen_text) ; end_card porte l'appel à l'action.
  on_screen_text : 90 caractères au plus, dans la langue du compte. voiceover : dans la langue du compte, ou vide. \
visual : ce qu'on voit, en français, pour la relecture. props_json = "" si le format n'en demande pas.
- Prompts des plans IA (shots[].prompt) : en anglais, concrets et filmables, un seul plan continu. Format vertical \
9:16 ; cadrage (close-up, medium shot…) ; sujet précis (âge, tenue, attitude, identiques d'un plan à l'autre si la \
même personne revient) ; une action simple ; le lieu ; la lumière ; le mouvement de caméra ; le rendu (« realistic \
smartphone footage », « cinematic »…). Rien d'écrit dans l'image (ni texte, ni lettres, ni logo, ni écran de \
téléphone lisible : le texte est incrusté à part et l'app se montre avec ses vraies captures). Pas de personne \
réelle ni de célébrité, pas d'enfant.
- ai_label : true dès qu'un plan ai_video ou ugc_avatar est présent (visages, voix ou scènes réalistes générés). \
En cas de doute : true.
- lang : la langue du compte ; phone_id : celui du compte ; pillar : un pilier de la stratégie (nom exact).

# Vérité et garde-fous (non négociables)
- N'invente aucune statistique ni aucun résultat chiffré présenté comme un fait (pourcentage, nombre d'utilisateurs, \
note, nombre d'avis, gain mesuré), aucun témoignage, aucune citation d'utilisateur, aucun résultat personnel : ces \
chiffres-là viennent de la fiche produit ou n'apparaissent pas (c'est vérifié). Les nombres d'une situation ou d'une \
liste (« 3 erreurs », « le 3e soir ») restent permis.
- Ne promets rien que l'app ne fait pas. Respecte la liste « à ne jamais dire », à la lettre et dans l'esprit.
- Une situation jouée (POV, sketch, conversation) est permise si elle reste crédible et ne se fait pas passer pour \
un vrai témoignage.
- Aucun appel à l'engagement artificiel (« like / commente / abonne-toi pour… », « tag 3 amis »), pas de fausse \
urgence, pas de dénigrement nominatif d'un concurrent, rien qui vise les moins de 13 ans.

# À éviter (vu mille fois, ça fait défiler)
- « Le saviez-vous ? », « Cette app va changer ta vie », « Game changer », « Stop scrolling », « Tu ne vas pas y \
croire », « Dans cette vidéo », « Salut tout le monde », « Voici 3 astuces » sans tension, un emoji 🚀 par phrase.
- Une liste de fonctionnalités sans situation vécue ; l'app nommée dès la première seconde ; une fin sans bénéfice \
clair.
- Une accroche qui ressemble à une accroche déjà utilisée (la liste est fournie) : chaque accroche est neuve par le \
fond, pas seulement par les mots.
"""


def strategy_system() -> str:
    return _with_playbook(STRATEGY_SYSTEM)


def ideas_system() -> str:
    """Partagé par ideas.generate, ideas.repair et ideas.variations (même cache)."""
    return _with_playbook(IDEAS_SYSTEM)


# --- Sections balisées -----------------------------------------------------------------------------------

def _dumps(obj: Any) -> str:
    """JSON lisible : une ligne par élément pour les listes, compact sinon."""
    if isinstance(obj, list):
        if not obj:
            return "[]"
        return "[\n" + ",\n".join(json.dumps(x, ensure_ascii=False) for x in obj) + "\n]"
    return json.dumps(obj, ensure_ascii=False)


def tag(name: str, body: Any) -> str:
    text = body if isinstance(body, str) else _dumps(body)
    return f"<{name}>\n{text}\n</{name}>"


def section(text: str, name: str) -> str | None:
    """Le contenu d'une section <name>…</name> (utilisé par les réponses de démo)."""
    m = re.search(rf"<{re.escape(name)}>\n?(.*?)\n?</{re.escape(name)}>", text, re.S)
    return m.group(1) if m else None


def section_json(text: str, name: str, default: Any = None) -> Any:
    raw = section(text, name)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


# --- Stratégie -------------------------------------------------------------------------------------------

def phones_payload(phones: Iterable[Any]) -> list[dict]:
    out = []
    for p in phones:
        accs = [{"platform": platform, "handle": (acc or {}).get("handle") or "",
                 "created": str((acc or {}).get("created") or "")}
                for platform, acc in (p.accounts or {}).items() if isinstance(acc, dict)]
        out.append({"phone_id": p.id, "lang": p.lang, "comptes": accs})
    return out


def strategy_request(*, app: dict, brief: ProductBrief, assets: list, phones: list, cadence: int,
                     budget: dict, current: Strategy | None = None, winners: list[dict] | None = None,
                     note: str | None = None) -> str:
    """Le message de strategy.generate : tout ce qu'il faut pour décider, rien de superflu."""
    langs = sorted({p.lang for p in phones})
    app_info = {k: app.get(k) for k in ("id", "name", "description", "store_url_ios", "store_url_android",
                                        "website_url") if app.get(k)}
    parts = [
        tag("app", app_info),
        tag("fiche_produit", brief.model_dump()),
        tag("captures", [a.for_prompt() for a in assets] or "Aucune capture fournie pour l'instant."),
        tag("telephones", phones_payload(phones)),
        tag("catalogue_formats", formats.catalog_for_prompt()),
        tag("cadence_et_budget", {
            "posts_par_jour_et_par_compte": cadence,
            "plafond_du_code": 5,
            "videos_par_jour_visees": cadence * len(phones),
            "budget_usd": {"par_jour_toutes_apps": budget.get("daily_usd"),
                           "par_jour_pour_cette_app": budget.get("daily_usd_per_app"),
                           "par_mois": budget.get("monthly_usd")},
            "couts": "free ≈ 0 $ (Remotion) ; low ≈ quelques centimes ; premium ≈ plusieurs dollars par vidéo "
                     "(vidéo IA) — ce budget couvre aussi les appels à Claude",
        }),
    ]
    if winners:
        parts.append(tag("gagnants", winners))
    if current is not None:
        parts.append(tag("strategie_en_vigueur", current.model_dump()))
    if note:
        parts.append(tag("consignes_equipe", note.strip()))
    ids = ", ".join(p.id for p in phones)
    parts.append(
        f"Construis la stratégie de contenu de {app.get('name') or app.get('id')} pour ces {len(phones)} "
        f"téléphone(s) : {ids}.\n"
        "Commence par cerner ce qui fait vraiment mal au persona principal, le moment exact où l'app le soulage et ce "
        "que les captures permettent de montrer ; la stratégie en découle.\n"
        f"Une voix par téléphone, nettement différentes les unes des autres ; des accroches écrites nativement dans "
        f"chaque langue des comptes ({', '.join(langs)}).\n"
        + ("Une stratégie est déjà en vigueur : garde ce qui marche (voir les gagnants s'il y en a), change ce que "
           "l'équipe demande et dis dans experiments ce que la nouvelle version teste.\n" if current else "")
        + ("Les consignes de l'équipe priment sur tes préférences, jamais sur la vérité ni les garde-fous.\n"
           if note else ""))
    return "\n\n".join(parts)


def strategy_fix(previous: Strategy, problems: list[str]) -> str:
    """Suite du message quand la stratégie proposée ne passe pas les contrôles."""
    return "\n\n" + "\n\n".join([
        tag("strategie_proposee", previous.model_dump()),
        tag("problemes", problems),
        "Ta proposition ne passe pas les contrôles ci-dessus. Rends la stratégie complète corrigée : règle chaque "
        "problème, garde le reste.",
    ])


# --- Idées -------------------------------------------------------------------------------------------------

def strategy_for_account(strategy: Strategy, lang: str) -> dict:
    """La partie de la stratégie utile à un compte (les accroches de sa langue seulement)."""
    return {
        "positioning": strategy.positioning,
        "north_star": strategy.north_star,
        "pillars": [p.model_dump() for p in strategy.pillars],
        "formats": [f.model_dump() for f in strategy.formats],
        "banque_d_accroches": [h.model_dump() for h in strategy.hooks if h.lang == lang],
        "ai_policy": strategy.ai_policy,
        "guardrails": strategy.guardrails,
    }


def idea_context(*, phone: Any, voice: AccountVoice, strategy: Strategy, brief: ProductBrief, assets: list,
                 used_hooks: list[str], history: dict, winners: list[dict] | None = None) -> str:
    """Le contexte commun aux idées, réparations et variations d'un compte."""
    others = [{"phone_id": v.phone_id, "lang": v.lang, "persona_target": v.persona_target, "voice": v.voice}
              for v in strategy.voices if v.phone_id != voice.phone_id]
    usable = [a.for_prompt() for a in assets]
    parts = [
        tag("compte", phones_payload([phone])[0]),
        tag("voix", voice.model_dump()),
        tag("autres_comptes", others or "Aucun autre compte pour cette app."),
        tag("strategie", strategy_for_account(strategy, phone.lang)),
        tag("fiche_produit", brief.model_dump()),
        tag("a_ne_jamais_dire", brief.do_not_say or "Rien de plus que les garde-fous."),
        tag("captures", usable or "Aucune capture : pas de plan app_screenshot ni d'asset_id."),
        tag("catalogue_formats", formats.catalog_for_prompt()),
        tag("historique_du_compte", history),
        tag("accroches_deja_utilisees", used_hooks or "Aucune pour l'instant."),
    ]
    if winners:
        parts.insert(-1, tag("gagnants", winners))
    return "\n\n".join(parts)


def ideas_order(*, count: int, phone: Any, today: str) -> str:
    return "\n\n" + "\n\n".join([
        tag("commande", {"nombre": count, "phone_id": phone.id, "lang": phone.lang, "date": today}),
        f"Écris {count} idée(s) de vidéo pour ce compte ({phone.id}, en « {phone.lang} »).\n"
        "- Répartis-les entre les piliers de la voix selon leurs parts, en tenant compte de l'historique du compte ; "
        "varie les formats (ceux de la voix d'abord) et les ressorts d'accroche : pas deux idées sur le même schéma.\n"
        "- Appuie au moins la moitié des idées sur de vraies captures (asset_id) quand il y en a d'utilisables.\n"
        "- Les idées refusées par l'équipe et leur raison (historique) disent ce qui ne convient pas : "
        "n'y reviens pas.\n"
        "- S'il y a des gagnants, comprends ce qui les a fait marcher et réutilise ce ressort, sans les copier.\n"
        "- Chaque accroche est neuve : rien qui ressemble aux accroches déjà utilisées.",
    ])


def repair_order(rejected: list[tuple[Idea, list[str]]]) -> str:
    items = [{"idee": idea.model_dump(), "erreurs": errors} for idea, errors in rejected]
    return "\n\n" + "\n\n".join([
        tag("idees_a_corriger", items),
        f"La validation automatique a refusé ces {len(items)} idée(s). Corrige chacune en gardant son intention "
        "(même compte, même angle autant que possible) : règle exactement les erreurs listées sans en créer d'autres. "
        "Si un format ne convient pas, change de format plutôt que de tordre ses limites. Rends une idée corrigée par "
        "idée refusée, dans le même ordre.",
    ])


VARIATIONS = (
    ("accroche", "Nouvelle accroche : même format, même structure, même déroulé ; seule l'accroche change (un autre "
                 "ressort pour la même promesse)."),
    ("angle", "Nouvel angle : même format, même promesse, mais un autre point d'entrée (autre situation, autre "
              "persona de la stratégie, autre objection levée), avec sa propre accroche."),
    ("format", "Autre format : la même idée gagnante portée par un autre format du catalogue, adapté à la voix ; "
               "l'accroche gagnante peut rester si elle colle au nouveau format."),
)


def variations_order(winner: dict) -> str:
    return "\n\n" + "\n\n".join([
        tag("gagnant", winner),
        tag("commande", {"nombre": len(VARIATIONS), "variations": [k for k, _ in VARIATIONS],
                         "phone_id": winner.get("phone_id"), "lang": winner.get("lang")}),
        "Ce contenu a très bien marché sur ce compte. Comprends d'abord pourquoi (l'accroche ? la situation ? la "
        "démonstration ?) et garde ce ressort. Puis écris exactement 3 variations, dans cet ordre :\n"
        + "\n".join(f"{i}. {text}" for i, (_, text) in enumerate(VARIATIONS, 1)),
    ])
