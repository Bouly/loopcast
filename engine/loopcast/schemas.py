"""Contrats partagés du pipeline : ce que Claude produit, ce que les modules s'échangent.

Ces modèles servent aussi de format imposé aux réponses de Claude (sorties structurées) : pas de
dict libre (non supporté par les sorties structurées), des listes et des champs explicites. Les
textes destinés à l'équipe sont en français ; les textes publiés sont dans la langue du compte.

Les modules (apps/, strategy/, production/, diffusion/) n'en changent pas la forme sans le dire
dans leur rapport : c'est le contrat entre eux.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Lang = Literal["fr", "en"]


class Localized(BaseModel):
    fr: str = Field(description="Version française (vide si l'app ne vise pas ce marché)")
    en: str = Field(description="English version (empty if the app does not target this market)")


# --- Compréhension du produit (apps/) -----------------------------------------------------------

class AssetAnalysis(BaseModel):
    """Ce que Claude voit dans une capture d'écran ou une image fournie par l'équipe."""
    screen: str = Field(description="Quel écran de l'app, en quelques mots (« écran d'accueil », « paywall »…)")
    shows: str = Field(description="Ce que la capture montre concrètement, sans interpréter")
    feature: str = Field(description="La fonctionnalité qu'elle illustre, ou vide")
    on_screen_text: list[str] = Field(description="Textes lisibles importants (titres, chiffres, boutons)")
    usable_in_video: bool = Field(description="Peut-on la montrer telle quelle dans une vidéo (lisible, sans donnée privée) ?")
    caution: str = Field(description="Ce qui pose problème (données personnelles, bug visible, texte illisible), ou vide")


class Feature(BaseModel):
    name: str
    benefit: str = Field(description="Le bénéfice pour l'utilisateur, en une phrase concrète")
    proof: str = Field(description="Comment on le montre à l'écran")
    asset_ids: list[int] = Field(description="Ids des captures qui le montrent")


class Persona(BaseModel):
    name: str = Field(description="Nom parlant : « Lycéenne qui révise la veille »")
    description: str
    pains: list[str]
    desires: list[str]
    triggers: list[str] = Field(description="Situations où l'app lui sert vraiment")
    langs: list[Lang]


class Objection(BaseModel):
    objection: str
    answer: str


class ProductBrief(BaseModel):
    """La fiche produit : ce qu'il faut avoir compris avant de faire la moindre vidéo."""
    app_name: str
    one_liner: Localized = Field(description="La promesse en une phrase, dans chaque langue")
    category: str
    problem: str = Field(description="Le problème, vu par l'utilisateur")
    solution: str = Field(description="Comment l'app le résout")
    value_props: list[str] = Field(description="3 à 5 bénéfices, du plus fort au plus faible")
    features: list[Feature]
    personas: list[Persona]
    differentiators: list[str]
    competitors: list[str]
    objections: list[Objection]
    proof_points: list[str] = Field(description="Faits vérifiables et sourcés seulement (note App Store, prix…), jamais inventés")
    pricing: str
    tone: str = Field(description="Le ton de la marque en quelques mots")
    do_not_say: list[str] = Field(description="Ce qu'on ne promet ou ne montre jamais")
    cta: Localized = Field(description="L'appel à l'action de fin de vidéo")
    keywords: Localized = Field(description="Mots-clés de recherche, séparés par des virgules")
    unknowns: list[str] = Field(description="Ce qui manque encore pour être sûr de la stratégie")
    confidence: float = Field(description="Confiance globale dans cette fiche, de 0 à 1")


class Question(BaseModel):
    question: str = Field(description="Une question précise, en français, à laquelle l'équipe répond en une ligne")
    why: str = Field(description="Ce que la réponse change dans la stratégie")
    kind: Literal["text", "choice", "multi"]
    options: list[str] = Field(description="Réponses proposées (vide pour une question libre)")
    priority: Literal["bloquante", "utile"]


class AnalysisResult(BaseModel):
    brief: ProductBrief
    questions: list[Question] = Field(description="Les questions encore utiles, les bloquantes d'abord (0 à 8)")


# --- Stratégie (strategy/) ------------------------------------------------------------------------

class Pillar(BaseModel):
    name: str
    goal: str = Field(description="Ce que ce pilier fait faire au spectateur")
    description: str
    share: int = Field(description="Part des vidéos, en pourcentage")


class Hook(BaseModel):
    text: str = Field(description="L'accroche telle qu'elle sera dite ou écrite, dans sa langue")
    lang: Lang
    pillar: str
    pattern: str = Field(description="Le ressort : question, contre-intuitif, POV, liste, avant/après…")


class FormatPlan(BaseModel):
    format: str = Field(description="Id du catalogue de formats (formats.catalog())")
    share: int = Field(description="Part des vidéos, en pourcentage")
    why: str


class AccountVoice(BaseModel):
    """Chaque téléphone a sa propre voix : c'est ce qui garde les contenus uniques d'un compte à l'autre."""
    phone_id: str = Field(description="« phone-1 »")
    lang: Lang
    persona_target: str = Field(description="Le persona visé en priorité")
    voice: str = Field(description="Le personnage et le style du compte, en deux phrases")
    pillars: list[str]
    formats: list[str]
    bio: str = Field(description="Proposition de bio du compte, dans sa langue (l'humain la pose à la main)")


class Experiment(BaseModel):
    hypothesis: str
    how: str
    metric: str


class Strategy(BaseModel):
    positioning: str
    north_star: str = Field(description="L'objectif mesurable (installations, visites de la fiche…)")
    pillars: list[Pillar]
    formats: list[FormatPlan]
    hooks: list[Hook] = Field(description="Banque de 20 à 40 accroches, réparties par langue et pilier")
    voices: list[AccountVoice]
    posts_per_day_per_account: int = Field(description="Cadence cible une fois la montée en charge faite (le code plafonne à 5)")
    ai_policy: str = Field(description="Quand utiliser de la vidéo IA, quand de vraies captures, et le label IA")
    guardrails: list[str]
    kpis: list[str]
    experiments: list[Experiment]


# --- Idées de vidéos (strategy/ → production/) -----------------------------------------------------

ShotKind = Literal["ai_video", "ugc_avatar", "app_screenshot", "app_recording", "text_card", "end_card"]


class Shot(BaseModel):
    kind: ShotKind
    duration_s: float
    visual: str = Field(description="Ce qu'on voit, en français, pour la relecture humaine")
    prompt: str = Field(description="Pour ai_video / ugc_avatar : le prompt du générateur, en anglais, précis "
                                    "(sujet, action, cadrage, lumière, style). Vide sinon.")
    asset_id: int | None = Field(description="Pour app_screenshot / app_recording : l'id de l'asset de l'app")
    on_screen_text: str = Field(description="Texte incrusté, dans la langue du compte, court (ou vide)")
    voiceover: str = Field(description="Voix off, dans la langue du compte (ou vide)")


class Idea(BaseModel):
    title: str = Field(description="Titre interne, en français")
    lang: Lang
    phone_id: str = Field(description="Le téléphone (et donc la voix) auquel l'idée est destinée")
    pillar: str
    format: str = Field(description="Id du catalogue de formats")
    hook: str = Field(description="L'accroche des 2 premières secondes, dans la langue du compte")
    angle: str
    why_it_works: str = Field(description="Pourquoi ça devrait marcher, en une phrase (en français)")
    shots: list[Shot] = Field(description="Pour les formats à plans (IA, hybrides) ; vide pour les formats Remotion à props")
    props_json: str = Field(description="Pour les formats Remotion : les props en JSON (voir le format). Vide sinon.")
    caption: str = Field(description="Légende du post, dans la langue du compte")
    hashtags: list[str]
    ai_label: bool = Field(description="Vrai dès qu'on montre des visages, voix ou scènes réalistes générés")


class IdeaBatch(BaseModel):
    ideas: list[Idea]
