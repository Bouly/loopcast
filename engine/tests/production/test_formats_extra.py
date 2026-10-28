"""Formats à plans : enregistrement dans le catalogue et validation des plans (messages renvoyables à Claude)."""

from loopcast import formats
from loopcast.production import formats_extra
from loopcast.schemas import Idea, Shot


def s(kind, d, *, asset=None, text="", voice="", prompt=""):
    if kind in ("ai_video", "ugc_avatar") and not prompt:
        prompt = "A young woman talking to the camera in her kitchen, morning light, natural selfie video"
    if kind in ("app_screenshot", "app_recording") and asset is None:
        asset = 12
    return {"kind": kind, "duration_s": d, "visual": "", "prompt": prompt, "asset_id": asset,
            "on_screen_text": text, "voiceover": voice}


def errors(fmt, shots):
    return formats.validate(fmt, {"shots": shots})


def test_formats_are_in_the_catalog():
    text = formats.catalog_for_prompt()
    for fmt in formats_extra.SHOT_FORMATS:
        spec = formats.get(fmt)
        assert spec.composition == "story" and formats_extra.uses_shots(spec)
        assert f"`{fmt}`" in text
    assert formats.get("ugc-ai").ai_label_required and "label IA obligatoire" in text
    assert formats.get("app-story").cost_class == "free" and formats.get("ai-hook-demo").cost_class == "premium"
    assert not formats_extra.uses_shots(formats.get("hook-demo"))


def test_valid_examples():
    assert errors("app-story", [s("app_screenshot", 3, text="Mon accroche"), s("app_recording", 5),
                                s("text_card", 2, text="Et le meilleur ?"), s("app_screenshot", 3),
                                s("end_card", 2.5, text="Lance ta série")]) == []
    assert errors("ai-hook-demo", [s("ai_video", 3, text="POV"), s("app_screenshot", 3), s("app_recording", 4)]) == []
    assert errors("ugc-ai", [s("ugc_avatar", 5, voice="J'ai enfin tenu mes habitudes."), s("app_screenshot", 3),
                             s("ugc_avatar", 4, voice="Essaie, c'est gratuit.")]) == []
    assert errors("demo-recording", [s("text_card", 2, text="Ma routine"), s("app_recording", 6),
                                     s("app_recording", 5)]) == []


def test_contract_with_strategy():
    """strategy valide un format à plans avec {**props_json, "shots": [...]} ; un plan IA dure 10 s au plus."""
    shots = [s("text_card", 2, text="Ma routine"), s("app_recording", 6), s("app_recording", 5)]
    assert formats.validate("demo-recording", {"shots": shots, "trims": {"2": 12.5}}) == []
    errs = formats.validate("demo-recording", {"shots": shots, "trims": {"0": 3, "1": -2, "x": 1}})
    assert any("trims[0] : le plan 0 n'est pas un passage de vidéo de démo" in e for e in errs)
    assert any("trims[1] : début en secondes" in e for e in errs) and any("« x »" in e for e in errs)
    assert formats.validate("demo-recording", {"shots": shots, "trims": [3]}) != []
    ugc = [s("ugc_avatar", 10, voice="Une phrase dite face caméra."), s("app_screenshot", 3)]
    assert errors("ugc-ai", ugc) == []
    assert any("entre 3 et 10 s" in e for e in errors("ugc-ai", [s("ugc_avatar", 11, voice="Une phrase."), s("app_screenshot", 3)]))


def test_whole_idea_is_accepted():
    idea = Idea(title="t", lang="fr", phone_id="phone-1", pillar="p", format="app-story", hook="h", angle="",
                why_it_works="", props_json="", caption="", hashtags=[], ai_label=False,
                shots=[Shot(**s("app_screenshot", 3)), Shot(**s("app_screenshot", 4))])
    assert formats.validate("app-story", idea.model_dump()) == []


def test_shot_errors_are_precise():
    errs = errors("app-story", [s("ai_video", 3), s("app_screenshot", 9), s("app_screenshot", 3, asset=None) | {"asset_id": None},
                                s("text_card", 2), s("app_screenshot", 2, voice="x" * 40)])
    joined = "\n".join(errs)
    assert "shots[0].kind : « ai_video » n'est pas permis" in joined
    assert "shots[1].duration_s : 9 s, entre 1,5 et 6 s" in joined.replace("1.5", "1,5") or "entre 1.5 et 6" in joined
    assert "shots[2].asset_id : id de la capture obligatoire" in joined
    assert "shots[3].on_screen_text : obligatoire pour une carte texte" in joined
    assert "shots[4].voiceover : 40 caractères pour 2 s, 32 au plus" in joined


def test_structure_rules():
    assert "shots : liste de plans obligatoire" in errors("app-story", None)[0]
    assert any("au moins 2 plans montrent l'app" in e for e in errors("app-story", [s("app_screenshot", 4), s("text_card", 4, text="x")]))
    assert any("une seule carte de fin" in e for e in errors("app-story", [s("end_card", 2), s("app_screenshot", 3), s("app_screenshot", 3)]))
    assert any("durée totale" in e for e in errors("app-story", [s("app_screenshot", 1.5), s("app_screenshot", 1.5)]))
    assert any("entre 2 et 10" in e for e in errors("app-story", [s("app_screenshot", 3)] * 11))


def test_ai_hook_demo_rules():
    joined = "\n".join(errors("ai-hook-demo", [s("app_screenshot", 3), s("ai_video", 3), s("ai_video", 3)]))
    assert "shots[0] : l'accroche est un plan ai_video" in joined
    assert "une seule vidéo IA" in joined and "au moins 2 plans de démo" in joined
    assert any("2 à 4 s" in e for e in errors("ai-hook-demo", [s("ai_video", 6), s("app_screenshot", 3), s("app_screenshot", 3)]))
    assert any("prompt du générateur obligatoire" in e
               for e in errors("ai-hook-demo", [s("ai_video", 3, prompt="trop court"), s("app_screenshot", 3), s("app_screenshot", 3)]))


def test_ugc_and_demo_rules():
    joined = "\n".join(errors("ugc-ai", [s("app_screenshot", 3), s("ugc_avatar", 4, voice="")]))
    assert "commence par la personne qui parle" in joined and "la phrase dite face caméra est obligatoire" in joined
    four = [s("ugc_avatar", 4, voice="Une phrase.")] * 4 + [s("app_screenshot", 3)]
    assert any("4 plans ugc_avatar, entre 1 et 3" in e for e in errors("ugc-ai", four))
    assert any("au moins un passage de la vidéo de démo" in e
               for e in errors("demo-recording", [s("text_card", 4, text="a"), s("text_card", 4, text="b")]))
    assert any("n'est pas permis" in e for e in errors("demo-recording", [s("app_screenshot", 3), s("app_recording", 5)]))
