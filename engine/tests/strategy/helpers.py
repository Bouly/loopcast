"""Données de test du module strategy : app, fiche, captures, stratégie, idées, exécution de la file."""

from __future__ import annotations

import json
from datetime import datetime

from loopcast import jobs
from loopcast.config import Config, FarmSettings, PhoneConfig
from loopcast.schemas import (AccountVoice, AssetAnalysis, Experiment, Feature, FormatPlan, Hook, Idea, IdeaBatch,
                              Localized, Objection, Persona, Pillar, ProductBrief, Strategy)
from loopcast.strategy import store

APP = "habitudo"
PHONES = (("phone-1", "fr"), ("phone-2", "en"), ("phone-3", "fr"))


def make_config(root, settings: dict | None = None, phones=None) -> Config:
    phones = phones if phones is not None else [
        PhoneConfig("phone-1", "U1", lang="fr", slot=0, apps=[APP],
                    accounts={"tiktok": {"handle": "@habitudo.fr", "created": "2026-10-01", "channel": "api_draft"},
                              "instagram": {"handle": "@habitudo.fr", "created": "2026-10-01"}}),
        PhoneConfig("phone-2", "U2", lang="en", slot=1, apps=[APP],
                    accounts={"tiktok": {"handle": "@habitudo.app", "created": "2026-10-01"},
                              "instagram": {"handle": "@habitudo.app", "created": "2026-10-01"}}),
        PhoneConfig("phone-3", None, lang="fr", slot=2, apps=[APP],
                    accounts={"tiktok": {"handle": "@habitudo.routines", "created": "2026-10-20"}}),
        PhoneConfig("phone-4", None, lang="en", slot=3, apps=[], accounts={}),
    ]
    return Config(root=root, settings=settings if settings is not None else {}, farm=FarmSettings(backend="fake"),
                  phones=phones)


def make_brief(**over) -> ProductBrief:
    data = dict(
        app_name="Habitudo",
        one_liner=Localized(fr="Trois habitudes, une coche par soir, une série qu'on n'a pas envie de casser.",
                            en="Three habits, one check a night, a streak you won't want to break."),
        category="suivi d'habitudes",
        problem="On abandonne ses bonnes résolutions au bout de quelques jours.",
        solution="Trois habitudes au plus, une coche chaque soir, une série visible.",
        value_props=["Trois habitudes, pas quinze", "Une coche par soir", "Une série qui motive"],
        features=[Feature(name="Série", benefit="Voir sa série grandir donne envie de continuer",
                          proof="L'écran de série", asset_ids=[1])],
        personas=[Persona(name="Étudiante qui procrastine", description="20 ans, en licence",
                          pains=["abandonne au bout de trois jours"], desires=["tenir enfin"],
                          triggers=["la rentrée"], langs=["fr", "en"])],
        differentiators=["Limitée à trois habitudes"],
        competitors=["Habitica"],
        objections=[Objection(objection="Encore une app", answer="Trente secondes par soir")],
        proof_points=["Note App Store 4,8 (1 200 avis)"],
        pricing="Gratuit, premium à 2,99 € par mois",
        tone="direct, complice, tutoiement",
        do_not_say=["garanti", "meilleure app du monde"],
        cta=Localized(fr="Télécharge Habitudo", en="Get Habitudo"),
        keywords=Localized(fr="habitudes, routine, motivation", en="habits, routine, motivation"),
        unknowns=[],
        confidence=0.8,
    )
    data.update(over)
    return ProductBrief(**data)


def analysis(**over) -> str:
    data = dict(screen="Série", shows="Une série de jours cochés", feature="série", on_screen_text=["Série"],
                usable_in_video=True, caution="")
    data.update(over)
    return AssetAnalysis(**data).model_dump_json()


def seed_app(conn, now: datetime, *, status: str = "brief_ready", brief: ProductBrief | None = None) -> dict:
    """L'app habitudo, sa fiche v1 approuvée et trois assets : 1 = capture utilisable, 2 = capture avec
    une donnée privée, 3 = vidéo de démo."""
    t = jobs.iso(now)
    conn.execute("""INSERT INTO apps(id, name, description, status, created_at, updated_at)
                    VALUES (?,?,?,?,?,?)""", (APP, "Habitudo", "Suivi d'habitudes", status, t, t))
    cur = conn.execute("""INSERT INTO app_briefs(app_id, version, brief, model, created_at, approved_at)
                          VALUES (?,1,?,'claude-opus-5-5',?,?)""",
                       (APP, (brief or make_brief()).model_dump_json(), t, t))
    brief_id = cur.lastrowid
    assets = [
        (1, "screenshot", "image/png", analysis()),
        (2, "screenshot", "image/png", analysis(screen="Réglages", usable_in_video=False,
                                                  caution="adresse e-mail visible")),
        (3, "demo_video", "video/mp4", analysis(screen="Démo", shows="On coche une habitude", feature="coche")),
    ]
    for aid, kind, mime, data in assets:
        conn.execute("""INSERT INTO app_assets(id, app_id, kind, path, filename, mime, sha256, caption, analysis,
                                               created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (aid, APP, kind, f"a{aid}", f"a{aid}", mime, f"sha{aid}", "", data, t))
    return {"brief_id": brief_id}


def add_brief(conn, now: datetime, version: int, approved: bool = True) -> int:
    t = jobs.iso(now)
    return conn.execute("INSERT INTO app_briefs(app_id, version, brief, created_at, approved_at) VALUES (?,?,?,?,?)",
                        (APP, version, make_brief().model_dump_json(), t, t if approved else None)).lastrowid


def make_strategy(phones=PHONES, **over) -> Strategy:
    voices = {
        "phone-1": AccountVoice(phone_id="phone-1", lang="fr", persona_target="Étudiante qui procrastine",
                                voice="La grande sœur qui a tout testé : franche et drôle, elle montre l'app en "
                                      "situation réelle, face caméra.",
                                pillars=["Le problème vécu", "La démo"], formats=["hook-demo", "notes-app"],
                                bio="Ce qui marche vraiment, testé pour toi"),
        "phone-2": AccountVoice(phone_id="phone-2", lang="en", persona_target="Young professional",
                                voice="Le briseur de mythes anglophone : démonte en vingt secondes les conseils "
                                      "productivité qui tournent en boucle.",
                                pillars=["Les idées reçues", "La démo"], formats=["chat-story", "slideshow"],
                                bio="Busting the advice everyone repeats"),
        "phone-3": AccountVoice(phone_id="phone-3", lang="fr", persona_target="Jeune actif débordé",
                                voice="Le carnet de bord : calme et précis, il raconte des routines en notes et en "
                                      "listes, sans jamais faire la morale.",
                                pillars=["Les idées reçues", "Le problème vécu"], formats=["notes-app", "slideshow"],
                                bio="Mes routines, une note à la fois"),
    }
    hooks = [Hook(text=f"Accroche {lang} numéro {i}", lang=lang, pillar="La démo", pattern="question")
             for lang in ("fr", "en") for i in range(6)]
    data = dict(
        positioning="L'app d'habitudes qui tient en trente secondes par soir.",
        north_star="Visites de la fiche App Store depuis le lien en bio",
        pillars=[Pillar(name="Le problème vécu", goal="Se reconnaître", description="Les galères", share=40),
                 Pillar(name="La démo", goal="Voir l'app marcher", description="Démo", share=35),
                 Pillar(name="Les idées reçues", goal="Changer d'avis", description="Mythes", share=25)],
        formats=[FormatPlan(format="hook-demo", share=40, why="vraies captures"),
                 FormatPlan(format="notes-app", share=30, why="natif"),
                 FormatPlan(format="chat-story", share=15, why="histoire"),
                 FormatPlan(format="slideshow", share=15, why="à enregistrer")],
        hooks=hooks,
        voices=[voices[pid] for pid, _lang in phones if pid in voices],
        posts_per_day_per_account=3,
        ai_policy="Captures réelles d'abord.",
        guardrails=["Aucun chiffre inventé"],
        kpis=["Taux de visionnage complet"],
        experiments=[Experiment(hypothesis="Les captures retiennent", how="A/B", metric="Visionnage complet")],
    )
    data.update(over)
    return Strategy(**data)


def approve_strategy(conn, now: datetime, strategy: Strategy | None = None) -> store.StrategyRecord:
    """Une stratégie approuvée (l'app passe active) ; la tâche ensure_stock enfilée est retirée."""
    with store.transaction(conn):
        rec = store.insert_strategy(conn, app_id=APP, brief_id=1, strategy=strategy or make_strategy(),
                                    model="claude-opus-5-5", now=now)
    store.approve_strategy(conn, rec.id, now)
    conn.execute("DELETE FROM jobs WHERE kind='ideas.ensure_stock'")
    return store.strategy_by_id(conn, rec.id)


PROPS = {
    "hook-demo": lambda hook: {"hook": hook[:60], "screens": [{"caption": "Ta série, chaque soir", "asset_id": 1},
                                                              {"caption": "Une coche et c'est fait", "asset_id": 1}],
                               "cta": "Télécharge Habitudo"},
    "notes-app": lambda hook: {"title": hook[:60], "items": ["Téléphone hors de la chambre", "Un verre d'eau",
                                                             "Cocher mes habitudes dans Habitudo"]},
    "chat-story": lambda hook: {"contactName": "Léa", "messages": [
        {"from": "them", "text": "T'as tenu ?"}, {"from": "me", "text": "Non…"},
        {"from": "them", "text": "Essaie Habitudo"}, {"from": "me", "text": "Ok je teste"}]},
    "slideshow": lambda hook: {"slides": [{"title": hook[:70]}, {"title": "Une seule habitude"},
                                          {"title": "Le même moment"}, {"title": "Une coche"}]},
}


def make_idea(hook: str = "Arrête de compter sur ta motivation", fmt: str = "hook-demo", lang: str = "fr",
              phone: str = "phone-1", **over) -> Idea:
    data = dict(title="Démo de la série", lang=lang, phone_id=phone, pillar="La démo", format=fmt, hook=hook,
                angle="La série comme moteur", why_it_works="La tension se résout à l'écran.", shots=[],
                props_json=json.dumps(PROPS[fmt](hook), ensure_ascii=False) if fmt in PROPS else "",
                caption="Tu tiens combien de soirs d'affilée ?", hashtags=["habitudes", "#routine"], ai_label=False)
    data.update(over)
    return Idea(**data)


def batch(*ideas: Idea):
    """Un répondeur FakeLLM qui rend toujours ce lot."""
    return lambda req: IdeaBatch(ideas=list(ideas))


def sequence(*responses):
    """Un répondeur FakeLLM qui rend les réponses dans l'ordre (la dernière ensuite)."""
    state = {"n": 0}

    def respond(req):
        i = min(state["n"], len(responses) - 1)
        state["n"] += 1
        out = responses[i]
        return out(req) if callable(out) else out

    return respond


def run_jobs(conn, config, clock, services, kinds=("strategy.", "ideas.")) -> list[jobs.Job]:
    done = []
    for _ in range(100):
        job = jobs.run_one(conn, config, "test", clock=clock, services=services, kinds=list(kinds))
        if job is None:
            break
        done.append(job)
    return done


def job_row(conn, job_id: int):
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def text_of(req) -> str:
    return "\n".join(b["text"] for b in req.content if b.get("type") == "text")


def events(conn, kind: str) -> list[str]:
    return [r["message"] for r in conn.execute("SELECT message FROM events WHERE kind=? ORDER BY id", (kind,))]
