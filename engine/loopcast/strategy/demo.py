"""Réponses de démo (serve --demo, sans clé Claude) : stratégie, idées, réparations, variations.

Elles relisent les sections que les prompts envoient (<telephones>, <compte>, <captures>, <commande>…)
pour rendre des réponses plausibles ET valides : formats Remotion du catalogue, props qui passent
formats.validate, vraies captures quand il y en a, et des accroches nouvelles à chaque appel (sinon
l'anti-doublon écarterait tout dès le deuxième lot).
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from loopcast import formats, llm
from loopcast.schemas import AccountVoice, Experiment, FormatPlan, Hook, Idea, IdeaBatch, Pillar, Strategy
from loopcast.strategy import prompts, validate

PREFERRED = ("hook-demo", "notes-app", "chat-story", "slideshow")
SHARES = {"hook-demo": 40, "notes-app": 25, "chat-story": 20, "slideshow": 15}

PILLARS = [
    ("Le problème vécu", "Faire dire « c'est tellement moi »",
     "Les galères du quotidien que l'app règle, racontées sans filtre et sans la nommer tout de suite.", 40),
    ("La démo qui prouve", "Montrer l'app qui règle le problème en quelques secondes",
     "Une situation, une fonction, la vraie app à l'écran.", 35),
    ("Les idées reçues", "Faire changer d'avis",
     "Un conseil répandu, démonté preuve à l'appui ; l'app comme méthode plus simple.", 25),
]
PATTERNS = ["POV", "question", "contre-intuitif", "confession", "liste", "avant/après", "erreur à éviter", "défi"]

ANGLES = {
    "notes-app": "Une liste de petits gestes concrets dont le dernier amène l'app.",
    "chat-story": "Une conversation entre amis : le problème, puis l'app comme réponse.",
    "hook-demo": "L'accroche, puis la vraie app à l'écran, fonction par fonction.",
    "slideshow": "Un carrousel à enregistrer : un conseil par slide, l'app en dernier.",
}
WHY = {
    "notes-app": "Le format note se lit comme le post d'un ami et la liste tient jusqu'au dernier point.",
    "chat-story": "On lit une conversation jusqu'au bout pour connaître la chute.",
    "hook-demo": "La tension de l'accroche est résolue par la vraie app, sous les yeux du spectateur.",
    "slideshow": "Un carrousel utile s'enregistre et se partage, ce qui pousse sa diffusion.",
}

LANG: dict[str, dict[str, Any]] = {
    "fr": {
        "templates": ["POV : {x}", "Parlons-en : {x}", "Le sujet dont personne ne parle : {x}",
                      "« {x} » : la vraie solution", "Toi aussi : {x} ?", "L'astuce qui règle « {x} »",
                      "Arrête de subir « {x} »", "Ce que j'aurais aimé savoir sur « {x} »"],
        "topics": ["les matins qui démarrent mal", "la motivation qui lâche le mercredi", "trop d'apps compliquées",
                   "le manque de temps", "les résolutions oubliées", "le soir devant l'écran",
                   "la to-do qui déborde", "les objectifs trop flous"],
        "tips": ["Commencer par une seule chose", "Le faire au même moment chaque jour", "Le noter dès que c'est fait",
                 "Garder l'objectif ridiculement petit", "Préparer la veille ce qui coince le matin",
                 "Regarder ses progrès une fois par semaine", "Ne jamais rater deux fois de suite"],
        "bodies": ["Une seule. Le reste attendra.", "Le cerveau adore les rendez-vous fixes.",
                   "Une coche, et c'est acté.", "Si ça prend plus de deux minutes, c'est trop gros.",
                   "Moins de décisions au réveil.", "Les progrès se voient sur la durée, pas en un jour.",
                   "Rater une fois arrive. Deux fois, c'est une nouvelle habitude."],
        "payoff": "Et {name} pour ne rien lâcher",
        "contacts": ["Léa", "Inès", "Hugo", "Sami"],
        "chat": [("them", "T'as réussi à tenir ton truc cette semaine ?"),
                 ("me", "Franchement non… le grand classique : {topic}"),
                 ("them", "Pareil avant. Maintenant j'utilise {name}"), ("me", "Ça fait quoi exactement ?"),
                 ("them", "{one_liner}")],
        "screens": ["Choisis ce qui compte", "Coche dès que c'est fait", "Regarde tes progrès"],
        "today": "Aujourd'hui", "week": "Cette semaine", "days": ["L", "M", "M", "J", "V", "S", "D"],
        "slide_app": "Le plus simple : {name}",
        "caption": "{one_liner} Tu commencerais par quoi ?",
        "cta": "Lien en bio",
        "tags": ["#astuces", "#organisation", "#routine"],
        "voices": [
            ("La grande sœur qui a tout testé", "Partage sans filtre ce qui marche vraiment au quotidien, avec humour. "
             "Parle face caméra comme à une amie et montre l'app en situation.",
             "Ce qui marche vraiment, testé pour toi · {name}"),
            ("Le démonteur d'idées reçues", "Prend un conseil répandu et le démonte en vingt secondes, preuve à "
             "l'écran. Ton direct, un brin provocateur, jamais moqueur.", "Les conseils bidon, démontés en 20 s"),
            ("Le carnet de bord", "Raconte les petites routines du quotidien en notes et en listes. Ton calme, "
             "précis, rassurant.", "Mes routines, une note à la fois"),
        ],
    },
    "en": {
        "templates": ["POV: {x}", "Can we talk about \"{x}\"?", "Nobody talks about \"{x}\"",
                      "\"{x}\": the actual fix", "You too? {x}", "The trick that fixes \"{x}\"",
                      "Stop putting up with \"{x}\"", "What I wish I knew about \"{x}\""],
        "topics": ["mornings that start wrong", "motivation that dies by Wednesday", "too many complicated apps",
                   "never having enough time", "forgotten resolutions", "late-night doomscrolling",
                   "the to-do list that never ends", "goals that are way too vague"],
        "tips": ["Start with just one thing", "Do it at the same time every day", "Write it down the second it's done",
                 "Keep the goal ridiculously small", "Prep tonight what slows you down tomorrow",
                 "Check your progress once a week", "Never miss twice in a row"],
        "bodies": ["Just one. The rest can wait.", "Your brain loves a fixed appointment.", "One check and it counts.",
                   "If it takes more than two minutes, it's too big.", "Fewer decisions when you wake up.",
                   "Progress shows up over weeks, not days.", "Missing once happens. Twice is a new habit."],
        "payoff": "And {name} so nothing slips",
        "contacts": ["Sam", "Maya", "Jordan", "Alex"],
        "chat": [("them", "Did you stick with your thing this week?"), ("me", "Honestly no… the classic: {topic}"),
                 ("them", "Same here before. Now I use {name}"), ("me", "Wait, what does it do?"),
                 ("them", "{one_liner}")],
        "screens": ["Pick what matters", "Check it off", "Watch it add up"],
        "today": "Today", "week": "This week", "days": ["M", "T", "W", "T", "F", "S", "S"],
        "slide_app": "The easy way: {name}",
        "caption": "{one_liner} Where would you start?",
        "cta": "Link in bio",
        "tags": ["#productivitytips", "#routine", "#selfimprovement"],
        "voices": [
            ("L'ami qui teste tout (public anglophone)", "Essaie les méthodes à la place du spectateur et dit ce qui "
             "marche, en anglais naturel et drôle. Démo de l'app en situation réelle.",
             "I test it so you don't have to · {name}"),
            ("Le briseur de mythes (public anglophone)", "Démonte en vingt secondes les conseils qui tournent en "
             "boucle, preuves à l'écran. Direct, malin, jamais condescendant.", "Busting the advice everyone repeats"),
            ("Le journal de bord (public anglophone)", "Partage routines et petites victoires du quotidien en notes "
             "et en listes. Calme, concret, rassurant.", "Small routines, one note at a time"),
        ],
    },
}


def clip(text: str, n: int) -> str:
    """Coupe proprement à n caractères au plus (mot entier, points de suspension)."""
    text = " ".join(str(text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") or text[:n - 1]
    return cut + "…"


def _text(req: llm.LLMRequest) -> str:
    return "\n".join(b.get("text", "") for b in req.content if isinstance(b, dict) and b.get("type") == "text")


def _remotion_formats() -> list[str]:
    ids = [s.id for s in formats.catalog() if s.engine == "remotion"]
    return [f for f in PREFERRED if f in ids] + [f for f in ids if f not in PREFERRED]


def _localized(brief: dict, key: str, lang: str) -> str:
    value = brief.get(key) or {}
    return (value.get(lang) or "").strip() if isinstance(value, dict) else ""


def _topics(brief: dict, lang: str) -> list[str]:
    """Des sujets d'accroche dans la langue du compte : mots-clés de la fiche, puis des sujets génériques."""
    found = [k.strip() for k in _localized(brief, "keywords", lang).split(",")]
    if lang == "fr":
        for persona in brief.get("personas") or []:
            found += list(persona.get("pains") or [])
    found += LANG[lang]["topics"]
    out, seen = [], set()
    for topic in found:
        key = validate.fold(topic)
        if key and key not in seen and len(topic) <= 40:
            seen.add(key)
            out.append(topic.strip().rstrip("."))
    return out


def hook_candidates(lang: str, brief: dict) -> list[str]:
    """Toutes les accroches possibles (60 caractères au plus, la limite de hook-demo), sujets alternés : deux
    voisines ne parlent pas de la même chose. Un sujet trop long pour un modèle est sauté, pas coupé."""
    templates = LANG[lang]["templates"]
    topics = _topics(brief, lang)
    out = []
    for k in range(len(templates)):
        for t, topic in enumerate(topics):
            template = templates[(t + k) % len(templates)]
            if len(template) - 3 + len(topic) <= 60:
                out.append(template.format(x=topic))
    return out


# --- Stratégie ---------------------------------------------------------------------------------------------

@llm.demo_responder("strategy.generate")
def demo_strategy(req: llm.LLMRequest) -> Strategy:
    text = _text(req)
    brief = prompts.section_json(text, "fiche_produit", {}) or {}
    phones = prompts.section_json(text, "telephones", []) or [{"phone_id": "phone-1", "lang": "fr"}]
    cadence = (prompts.section_json(text, "cadence_et_budget", {}) or {}).get("posts_par_jour_et_par_compte") or 3
    name = brief.get("app_name") or "l'app"
    fids = _remotion_formats()
    pillars = [Pillar(name=n, goal=g, description=d, share=s) for n, g, d, s in PILLARS]
    names = [p.name for p in pillars]
    langs = sorted({p.get("lang") if p.get("lang") in LANG else "en" for p in phones})

    hooks = []
    for lang in langs:
        for i, h in enumerate(hook_candidates(lang, brief)[:10]):
            hooks.append(Hook(text=h, lang=lang, pillar=names[i % len(names)], pattern=PATTERNS[i % len(PATTERNS)]))

    personas = [p.get("name") for p in brief.get("personas") or [] if p.get("name")] or ["Le public principal de l'app"]
    voices, rank = [], Counter()
    for i, phone in enumerate(phones):
        lang = phone.get("lang") if phone.get("lang") in LANG else "en"
        k = rank[lang]
        rank[lang] += 1
        title, character, bio = LANG[lang]["voices"][k % len(LANG[lang]["voices"])]
        voices.append(AccountVoice(
            phone_id=phone.get("phone_id") or f"phone-{i + 1}", lang=lang,
            persona_target=personas[i % len(personas)], voice=f"{title}. {character}",
            pillars=(names[k % 3:] + names[:k % 3])[:2],
            formats=(fids[k % len(fids):] + fids[:k % len(fids)])[:max(2, len(fids) - 1)],
            bio=clip(bio.format(name=name), 80)))

    one_liner = _localized(brief, "one_liner", "fr")
    return Strategy(
        positioning=f"{name} : {one_liner}" if one_liner else f"{name}, la solution simple au problème du quotidien "
                                                               f"de son public.",
        north_star="Visites de la fiche App Store depuis le lien en bio, suivies chaque semaine.",
        pillars=pillars,
        formats=[FormatPlan(format=f, share=SHARES.get(f, 10), why=ANGLES.get(f, "Format du catalogue."))
                 for f in fids],
        hooks=hooks,
        voices=voices,
        posts_per_day_per_account=int(cadence),
        ai_policy="Formats Remotion et vraies captures d'abord (coût nul, preuve réelle). Vidéo IA seulement pour un "
                  "plan d'ambiance impossible à filmer, avec le label IA dès qu'une personne ou une scène réaliste "
                  "est générée.",
        guardrails=["Aucun chiffre hors de la fiche produit", "Pas de faux témoignage ni de résultat inventé",
                    *list(brief.get("do_not_say") or [])[:3]],
        kpis=["Taux de visionnage complet", "Partages et enregistrements pour 1 000 vues", "Visites du profil",
              "Clics vers la fiche App Store (lien en bio)"],
        experiments=[
            Experiment(hypothesis="Les vidéos sur vraies captures retiennent mieux que les écrans factices",
                       how="Même accroche en deux versions, sur deux semaines", metric="Taux de visionnage complet"),
            Experiment(hypothesis="Une accroche en question amène plus de visites du profil qu'une affirmation",
                       how="Alterner les deux ressorts sur dix vidéos par compte",
                       metric="Visites du profil pour 1 000 vues"),
        ],
    )


# --- Idées ------------------------------------------------------------------------------------------------------

class _Account:
    """Le compte tel que le décrit le message : langue, voix, captures, accroches déjà prises."""

    def __init__(self, text: str):
        compte = prompts.section_json(text, "compte", {}) or {}
        self.lang = compte.get("lang") if compte.get("lang") in LANG else "en"
        self.phone_id = compte.get("phone_id") or "phone-1"
        self.brief = prompts.section_json(text, "fiche_produit", {}) or {}
        self.name = self.brief.get("app_name") or "l'app"
        voice = prompts.section_json(text, "voix", {}) or {}
        strategy = prompts.section_json(text, "strategie", {}) or {}
        self.pillars = (voice.get("pillars") or [p.get("name") for p in strategy.get("pillars") or []]
                        or [PILLARS[0][0]])
        self.all_formats = _remotion_formats()
        self.formats = [f for f in voice.get("formats") or [] if f in self.all_formats] or self.all_formats
        captures = prompts.section_json(text, "captures", [])
        self.captures = [(c["asset_id"], c.get("feature") or c.get("screen") or "")
                         for c in (captures if isinstance(captures, list) else [])
                         if isinstance(c, dict) and c.get("usable_in_video") and c.get("kind") != "demo_video"]
        used = prompts.section_json(text, "accroches_deja_utilisees", [])
        self.index = validate.HookIndex(used if isinstance(used, list) else [])
        self.seed = len(self.index)
        self.t = LANG[self.lang]

    def fresh_hooks(self, n: int) -> list[str]:
        out = []
        for hook in hook_candidates(self.lang, self.brief):
            if len(out) == n:
                break
            if self.index.find(hook) is None:
                self.index.add(hook)
                out.append(hook)
        return out

    def ideas(self, n: int, fids: list[str] | None = None) -> list[Idea]:
        out = []
        for i, hook in enumerate(self.fresh_hooks(n)):
            fid = fids[i] if fids and i < len(fids) else self.formats[(self.seed + i) % len(self.formats)]
            out.append(self.idea(fid, hook, self.seed + i))
        return out

    def one_liner(self) -> str:
        return _localized(self.brief, "one_liner", self.lang) or self.name

    def cta(self) -> str:
        return clip(_localized(self.brief, "cta", self.lang) or self.t["cta"], 40)

    def tips(self, k: int, n: int) -> list[tuple[str, str]]:
        pairs = list(zip(self.t["tips"], self.t["bodies"], strict=True))
        return [pairs[(k + j) % len(pairs)] for j in range(n)]

    def idea(self, fid: str, hook: str, k: int) -> Idea:
        build = {"notes-app": self.notes, "chat-story": self.chat, "hook-demo": self.demo, "slideshow": self.slides}
        props = build.get(fid, self.notes)(hook, k)
        if fid not in build:
            fid = "notes-app"
        keywords = [w.strip() for w in _localized(self.brief, "keywords", self.lang).split(",") if w.strip()]
        return Idea(
            title=clip(f"{formats.get(fid).title} · {hook}", 90), lang=self.lang, phone_id=self.phone_id,
            pillar=self.pillars[k % len(self.pillars)], format=fid, hook=hook, angle=ANGLES[fid], why_it_works=WHY[fid],
            shots=[], props_json=json.dumps(props, ensure_ascii=False),
            caption=clip(self.t["caption"].format(one_liner=self.one_liner().rstrip(".") + "."), 220),
            hashtags=validate.normalize_hashtags([*keywords[:3], *self.t["tags"]])[:5], ai_label=False)

    def notes(self, hook: str, k: int) -> dict:
        items = [clip(tip, 70) for tip, _ in self.tips(k, 3)] + [clip(self.t["payoff"].format(name=self.name), 70)]
        return {"title": clip(hook, 60), "items": items, "highlightLast": True, "numbered": True, "cta": self.cta()}

    def chat(self, hook: str, k: int) -> dict:
        topics = _topics(self.brief, self.lang)
        values = {"name": self.name, "one_liner": self.one_liner(), "topic": topics[k % len(topics)]}
        return {"contactName": self.t["contacts"][k % len(self.t["contacts"])],
                "messages": [{"from": who, "text": clip(line.format(**values), 120)} for who, line in self.t["chat"]],
                "cta": self.cta()}

    def demo(self, hook: str, k: int) -> dict:
        screens = []
        for j in range(min(3, len(self.captures))):
            asset_id, feature = self.captures[(k + j) % len(self.captures)]
            caption = feature.capitalize() if self.lang == "fr" and feature else self.t["screens"][j]
            screens.append({"caption": clip(caption, 45), "asset_id": asset_id})
        if len(screens) < 2:
            screens.append({"caption": self.t["screens"][0], "mock": {
                "kind": "list", "title": self.t["today"],
                "items": [{"label": clip(tip, 30), "done": j < 2} for j, (tip, _) in enumerate(self.tips(k, 3))]}})
        if len(screens) < 2:
            screens.append({"caption": self.t["screens"][2], "mock": {
                "kind": "chart", "title": self.t["week"], "bars": [0.3, 0.45, 0.5, 0.7, 0.65, 0.85, 1.0],
                "labels": self.t["days"]}})
        return {"hook": clip(hook, 60), "screens": screens, "cta": self.cta()}

    def slides(self, hook: str, k: int) -> dict:
        slides = [{"title": clip(hook, 70), "emoji": "✨"}]
        slides += [{"title": clip(tip, 70), "body": clip(body, 140)} for tip, body in self.tips(k, 3)]
        slides.append({"title": clip(self.t["slide_app"].format(name=self.name), 70),
                       "body": clip(self.one_liner(), 140)})
        return {"slides": slides, "cta": self.cta()}


@llm.demo_responder("ideas.generate")
def demo_ideas(req: llm.LLMRequest) -> IdeaBatch:
    text = _text(req)
    order = prompts.section_json(text, "commande", {}) or {}
    return IdeaBatch(ideas=_Account(text).ideas(max(1, int(order.get("nombre") or 3))))


@llm.demo_responder("ideas.repair")
def demo_repair(req: llm.LLMRequest) -> IdeaBatch:
    text = _text(req)
    account = _Account(text)
    items = prompts.section_json(text, "idees_a_corriger", []) or []
    fids = [(it.get("idee") or {}).get("format") for it in items if isinstance(it, dict)]
    fids = [f if f in account.all_formats else account.formats[i % len(account.formats)] for i, f in enumerate(fids)]
    return IdeaBatch(ideas=account.ideas(len(fids), fids))


@llm.demo_responder("ideas.variations")
def demo_variations(req: llm.LLMRequest) -> IdeaBatch:
    text = _text(req)
    account = _Account(text)
    winner = prompts.section_json(text, "gagnant", {}) or {}
    same = winner.get("format") if winner.get("format") in account.all_formats else account.formats[0]
    other = next((f for f in account.formats + account.all_formats if f != same), same)
    return IdeaBatch(ideas=account.ideas(3, [same, same, other]))
