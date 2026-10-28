"""Contrôles des idées et des stratégies (validate.py) : sans base ni Claude."""

import json

import pytest

from loopcast import formats
from loopcast.schemas import Shot
from loopcast.strategy import validate
from loopcast.strategy.validate import AssetRef, HookIndex, IdeaContext

from .helpers import PHONES, make_idea, make_strategy


@pytest.fixture
def ctx():
    return IdeaContext(
        lang="fr", phone_id="phone-1",
        assets={1: AssetRef(1, "screenshot", "image/png", True),
                2: AssetRef(2, "screenshot", "image/png", False, "adresse e-mail visible"),
                3: AssetRef(3, "demo_video", "video/mp4", True)},
        pillars=["Le problème vécu", "La démo", "Les idées reçues"],
        do_not_say=["garanti", "meilleure app du monde"],
        sources="Note App Store 4,8 (1 200 avis). Gratuit, premium à 2,99 € par mois.")


@pytest.fixture
def ai_format(monkeypatch):
    """Un format à plans, comme ceux que la production enregistrera."""
    spec = formats.FormatSpec("broll-test", "video", "ai", None, "B-roll IA", "Plans IA + captures", "shots",
                              "premium")
    monkeypatch.setitem(formats.CATALOG, spec.id, spec)
    return spec.id


def check(idea, ctx):
    return validate.validate_idea(validate.normalize_idea(idea, ctx), ctx)


def shot(kind, duration, **over):
    data = dict(kind=kind, duration_s=duration, visual="…", prompt="", asset_id=None, on_screen_text="", voiceover="")
    data.update(over)
    return Shot(**data)


PROMPT = ("Vertical 9:16 medium shot of a young woman in a grey hoodie closing a laptop at night in a small "
          "student room, warm desk lamp, slow push-in, realistic smartphone footage")


def test_a_good_idea_passes(ctx):
    for fmt in ("hook-demo", "notes-app", "chat-story", "slideshow"):
        assert check(make_idea(fmt=fmt), ctx) == [], fmt


def test_props_errors_are_explicit(ctx):
    props = {"hook": "x" * 70, "screens": [{"caption": "a", "asset_id": 1}]}
    errors = check(make_idea(props_json=json.dumps(props)), ctx)
    assert "props_json.hook : 70 caractères, 60 au plus" in errors
    assert any(e.startswith("props_json.screens : 1 éléments") for e in errors)
    assert check(make_idea(props_json="{pas du json"), ctx)[0].startswith("props_json n'est pas du JSON valide")
    assert "vide" in check(make_idea(props_json=""), ctx)[0]


def test_asset_references_are_checked(ctx):
    def screens(*ids):
        return json.dumps({"hook": "Ta série", "screens": [{"caption": "c", "asset_id": i} for i in ids]})

    assert any("asset_id 9 inconnu (ids disponibles : 1)" in e for e in check(make_idea(props_json=screens(1, 9)), ctx))
    assert any("adresse e-mail visible" in e for e in check(make_idea(props_json=screens(1, 2)), ctx))
    assert any("est une vidéo" in e for e in check(make_idea(props_json=screens(1, 3)), ctx))
    mocks = json.dumps({"hook": "Ta série", "screens": [{"caption": "c", "mock": {"kind": "list"}}] * 2})
    assert any("au moins une vraie capture" in e for e in check(make_idea(props_json=mocks), ctx))
    ctx.assets = {}
    assert check(make_idea(props_json=mocks), ctx) == []          # pas de captures : les écrans factices suffisent


def test_language_hook_caption(ctx):
    assert any("ce compte publie en « fr »" in e for e in check(make_idea(lang="en"), ctx))
    assert any("90 au plus" in e for e in check(make_idea(hook="mot " * 30), ctx))
    assert "caption : légende obligatoire" in check(make_idea(caption=" "), ctx)
    assert check(make_idea(fmt="inconnu"), ctx)[0].startswith("format inconnu : « inconnu » (formats possibles :")


def test_normalization_fixes_form_not_substance(ctx):
    props = {"hook": "Ta série", "lang": "en", "brand": {"accent": "#000"},
             "screens": [{"caption": "a", "asset_id": 1, "src": "brands/x.png"}, {"caption": "b", "asset_id": 1}]}
    raw = make_idea(phone="phone-9", props_json=json.dumps(props), caption="Tu tiens ? #habitudes #Routine",
                    hashtags=["routine", "#motivation du soir"], pillar="la demo",
                    shots=[shot("text_card", 3)])
    idea = validate.normalize_idea(raw, ctx)
    clean = json.loads(idea.props_json)
    assert "lang" not in clean and "brand" not in clean and "src" not in clean["screens"][0]
    assert idea.phone_id == "phone-1" and idea.shots == [] and idea.pillar == "La démo"
    assert idea.caption == "Tu tiens ?"
    assert idea.hashtags == ["#routine", "#motivationdusoir", "#habitudes"]   # #Routine : déjà là


def test_shot_formats(ctx, ai_format):
    good = [shot("ai_video", 4, prompt=PROMPT), shot("app_screenshot", 5, asset_id=1, on_screen_text="Une coche"),
            shot("app_recording", 6, asset_id=3), shot("end_card", 3, on_screen_text="Télécharge Habitudo")]
    idea = validate.normalize_idea(make_idea(fmt=ai_format, shots=good), ctx)
    assert validate.validate_idea(idea, ctx) == []
    assert idea.ai_label is True                                   # scène réaliste générée

    def errors_for(shots):
        return check(make_idea(fmt=ai_format, shots=shots), ctx)

    assert "aucun n'est fourni" in errors_for([])[0]
    assert any("4 s au total" in e for e in errors_for([shot("app_screenshot", 4, asset_id=1)]))
    assert any("10 s au plus" in e for e in errors_for([shot("ai_video", 12, prompt=PROMPT),
                                                        shot("app_screenshot", 3, asset_id=1)]))
    assert any("asset_id : obligatoire" in e for e in errors_for([shot("app_screenshot", 9)]))
    assert any("pas une vidéo de démo" in e for e in errors_for([shot("app_recording", 9, asset_id=1)]))
    assert any("prompt du générateur obligatoire" in e for e in errors_for([shot("ai_video", 5),
                                                                            shot("app_screenshot", 5, asset_id=1)]))
    french = "Une jeune femme ferme son ordinateur dans une chambre d'étudiante éclairée par une lampe"
    assert any("à écrire en anglais" in e for e in errors_for([shot("ai_video", 5, prompt=french),
                                                               shot("app_screenshot", 5, asset_id=1)]))
    assert any("voiceover : ce que dit l'avatar" in e for e in errors_for([shot("ugc_avatar", 6, prompt=PROMPT),
                                                                           shot("app_screenshot", 4, asset_id=1)]))
    assert any("montrer la vraie app" in e for e in errors_for([shot("ai_video", 5, prompt=PROMPT),
                                                                shot("end_card", 4, on_screen_text="Fin")]))


def test_ai_label_is_forced_for_generated_humans(ctx, ai_format):
    avatar = make_idea(fmt=ai_format, ai_label=False, shots=[
        shot("ugc_avatar", 6, prompt=PROMPT, voiceover="Franchement, j'ai enfin tenu."),
        shot("app_screenshot", 4, asset_id=1)])
    assert validate.normalize_idea(avatar, ctx).ai_label is True
    assert validate.normalize_idea(make_idea(), ctx).ai_label is False


def test_numbers_must_come_from_the_brief(ctx):
    def claims(**texts):
        return [e for e in check(make_idea(**texts), ctx) if e.startswith("chiffre non sourcé")]

    assert claims(caption="93 % des étudiants abandonnent en février") == [
        "chiffre non sourcé « 93 % » : n'utiliser que les chiffres de la fiche produit (proof_points), "
        "sinon reformuler sans chiffre"]
    assert claims(caption="Déjà 10k+ utilisateurs") and claims(caption="Noté 4.9 étoiles")
    assert claims(caption="Noté 4,8 étoiles par 1 200 avis") == []      # dans la fiche
    assert claims(caption="100 % gratuit, 21 jours de série") == []      # tournure, pas une statistique


def test_do_not_say_is_enforced_literally(ctx):
    assert any("do_not_say" in e for e in check(make_idea(caption="Résultat garanti !"), ctx))
    assert not any("do_not_say" in e for e in check(make_idea(caption="Rien n'est gratuit"), ctx))


def test_hook_index_catches_near_duplicates():
    index = HookIndex(["Arrête de compter sur ta **motivation**", "POV : tu tiens enfin tes résolutions"])
    assert index.find("arrête de compter sur ta motivation !!! 🚀") == "Arrête de compter sur ta **motivation**"
    assert index.find("Arrête de compter sur la motivation") is not None
    assert index.find("Pourquoi tes résolutions meurent le 3 janvier") is None
    assert index.find("") is None
    assert validate.fold("Élève — déjà prêt·e ?") == "eleve deja pret e"


def test_strategy_check_normalizes_and_reports():
    phones = [type("P", (), {"id": pid, "lang": lang})() for pid, lang in PHONES]
    s = make_strategy()
    s.formats[0] = s.formats[0].model_copy(update={"format": "inconnu"})
    s.voices[0] = s.voices[0].model_copy(update={"formats": ["inconnu"], "pillars": ["le probleme vecu", "Autre"]})
    fixed, blocking, warnings = validate.check_strategy(s, phones)
    assert blocking == [] and any("« inconnu » n'est pas dans le catalogue" in w for w in warnings)
    assert sum(f.share for f in fixed.formats) == 100 and sum(p.share for p in fixed.pillars) == 100
    assert fixed.voices[0].formats == ["notes-app", "chat-story", "slideshow"]     # repli : formats de la stratégie
    assert fixed.voices[0].pillars == ["Le problème vécu"]

    s = make_strategy(posts_per_day_per_account=9)
    s.voices = [s.voices[0], s.voices[1].model_copy(update={"lang": "fr"})]
    fixed, blocking, _ = validate.check_strategy(s, phones)
    assert fixed.posts_per_day_per_account == 5
    assert any("phone-2 publie en « en »" in b for b in blocking)
    assert any("il manque la voix de phone-3" in b for b in blocking)


def test_voices_must_differ():
    s = make_strategy()
    twin = s.voices[0].model_copy(update={"phone_id": "phone-3"})
    out = validate.voice_overlaps([s.voices[0], twin, s.voices[1]])
    assert len(out) == 1 and "phone-1 et phone-3" in out[0] and "même personnage" in out[0] and "même bio" in out[0]
    assert validate.voice_overlaps(s.voices) == []
