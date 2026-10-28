"""Catalogue (prix, paramètres, surcharges par settings.yaml) et routage (qualité, contraintes, budget)."""

from datetime import timedelta

import pytest
from providers_testkit import video_model, video_router

from loopcast import costs
from loopcast.providers import catalog
from loopcast.providers.base import NoModel, OverBudget, VideoRequest


def vreq(**kw):
    kw.setdefault("prompt", "A barista pours latte art, close-up")
    kw.setdefault("duration_s", 5)
    return VideoRequest(**kw)


# --- Catalogue ------------------------------------------------------------------------------------------

def test_default_catalog_prices_and_durations():
    models = {m.id: m for m in catalog.video_models()}
    veo = models["veo31-fast-1080p"]
    assert veo.billed_duration(5) == 6 and veo.billed_duration(10) is None
    assert veo.price(vreq(duration_s=5)) == pytest.approx(0.60)                 # 6 s × 0,10 $
    assert veo.price(vreq(duration_s=5, audio=True)) == pytest.approx(0.90)     # 6 s × 0,15 $
    assert models["kling3-std"].price(vreq(duration_s=10, audio=True)) == pytest.approx(1.26)
    assert models["h3-max-768p"].price(vreq(duration_s=7.5)) == pytest.approx(0.60)
    assert models["seedance2-720p"].billed_duration(2) == 4                      # minimum du modèle
    assert not models["seedance25-720p"].enabled                                 # fourni mais désactivé
    assert all(m.source.startswith("https://fal.ai/models/") and m.verified == "2026-10-29"
               for m in catalog.video_models() + catalog.image_models())
    flux = catalog.find(catalog.image_models(), "flux2-pro")
    assert flux.price(catalog.ImageRequest(prompt="x")) == pytest.approx(0.045)  # 0,03 $ + 1 Mpx à 0,015 $


def test_call_parameters_follow_each_model():
    models = {m.id: m for m in catalog.video_models()}
    veo = models["veo31-fast-1080p"].inputs(vreq(audio=True, seed=3, negative_prompt="blur"))
    assert veo == {"prompt": vreq().prompt, "duration": "6s", "aspect_ratio": "9:16", "resolution": "1080p",
                   "generate_audio": True, "seed": 3, "negative_prompt": "blur"}
    kling = models["kling3-std"].inputs(vreq(seed=3), image_url="data:image/jpeg;base64,AAA")
    assert kling["start_image_url"].startswith("data:") and kling["duration"] == "5"
    assert "seed" not in kling and "aspect_ratio" not in kling                  # absents en image→vidéo Kling
    h3 = models["h3-max-768p"].inputs(vreq(duration_s=5.2, audio=True))
    assert h3["duration"] == 5.2 and h3["resolution"] == "768P" and "generate_audio" not in h3
    assert h3["prompt_expansion_mode"] == "balanced"
    wan = models["wan3-720p"].inputs(vreq(duration_s=4.5))
    assert wan["duration"] == 5 and wan["audio"] is False
    omni = models["omni-flash-720p"].inputs(vreq(seed=1, negative_prompt="blur"))
    assert omni == {"prompt": vreq().prompt, "duration": 5, "aspect_ratio": "9:16", "resolution": "720p"}


def test_settings_override_merge_and_errors():
    settings = {"providers": {"video": {
        "models": [{"id": "h3-max-768p", "usd_per_s": 0.06},
                   {"id": "seedance25-720p", "enabled": True},
                   {"id": "new-model", "label": "Nouveau", "provider": "fal", "tier": "eco",
                    "endpoint": "acme/new/text-to-video", "usd_per_s": 0.02, "durations": [5, 10]}],
        "disabled": ["kling3-pro"]}}}
    models = {m.id: m for m in catalog.video_models(settings)}
    assert models["h3-max-768p"].usd_per_s == 0.06 and models["h3-max-768p"].tier == "standard"
    assert models["seedance25-720p"].enabled and not models["kling3-pro"].enabled
    assert models["new-model"].durations == (5, 10) and models["new-model"].price(vreq()) == pytest.approx(0.10)
    with pytest.raises(catalog.CatalogError, match="usd_par_s"):
        catalog.video_models({"providers": {"video": {"models": [{"id": "h3-max-768p", "usd_par_s": 1}]}}})
    with pytest.raises(catalog.CatalogError, match="tier"):
        catalog.video_models({"providers": {"video": {"models": [{"id": "h3-max-768p", "tier": "luxe"}]}}})
    only = catalog.video_models({"providers": {"video": {"replace_defaults": True, "models": [
        {"id": "solo", "label": "Solo", "provider": "fake", "tier": "standard", "endpoint": "x/y"}]}}})
    assert [m.id for m in only] == ["solo"]


# --- Routage --------------------------------------------------------------------------------------------

@pytest.fixture
def models():
    return [
        video_model("eco-a", "eco", 0.04),
        video_model("std-a", "standard", 0.10, endpoint_i2v=None),
        video_model("std-b", "standard", 0.08, audio="always", voice_langs=("fr", "en")),
        video_model("std-zh", "standard", 0.05, voice_langs=("zh", "en")),
        video_model("pre-a", "premium", 0.30, max_s=8),
    ]


def test_route_by_quality_and_constraints(models, clock):
    router = video_router(models, clock)
    assert router.route(vreq()).model.id == "std-a"                                  # le préféré du niveau
    assert router.route(vreq(quality="premium")).model.id == "pre-a"
    assert router.route(vreq(image_path="/tmp/x.png")).model.id == "std-b"         # std-a : pas d'image→vidéo
    ugc_fr = vreq(audio=True, humans=True, lang="fr")
    assert router.route(ugc_fr, exclude=("std-a",)).model.id == "std-b"             # std-zh ne parle pas français
    long_premium = router.route(vreq(quality="premium", duration_s=9.5))
    assert long_premium.model.id == "std-a" and long_premium.downgraded            # pre-a : 8 s au plus
    assert "aucun modèle premium ne convient" in long_premium.reason
    assert router.route(vreq(model="std-zh")).model.id == "std-zh"
    with pytest.raises(NoModel, match="eco-a"):
        router.route(vreq(quality="eco", humans=True), exclude=("eco-a",))


def test_budget_downgrade_then_over_budget(models, clock, conn):
    """Premium trop cher pour le reste du jour → standard ; plus rien ne passe → OverBudget jusqu'à demain."""
    router = video_router(models, clock)
    settings = {"budget": {"daily_usd": 1.0, "daily_usd_per_app": 1.0, "monthly_usd": 100}}

    def fits(estimate):
        return costs.check_budget(conn, settings, clock(), estimate, app_id="habitudo")

    route = router.route(vreq(quality="premium"), fits=fits)                     # pre-a : 1,50 $ > 1 $
    assert route.model.id == "std-a" and route.downgraded and route.reason.startswith("budget")
    costs.record(conn, at=clock(), provider="fal", kind="video", cost_usd=0.6, app_id="habitudo")
    # Reste 0,40 $ : std-a (0,50 $) ne passe pas ; le moins cher du même niveau, std-zh (0,25 $), si.
    assert router.route(vreq(), fits=fits).model.id == "std-zh"
    costs.record(conn, at=clock(), provider="fal", kind="video", cost_usd=0.2, app_id="habitudo")
    with pytest.raises(OverBudget) as e:
        router.route(vreq(quality="premium"), fits=fits)
    assert "plafond du jour" in e.value.reason
    assert e.value.retry_at == costs.day_start(clock()) + timedelta(days=1)
    assert router.route(vreq(quality="eco"), fits=fits).model.id == "eco-a"      # 0,20 $ passe encore


def test_router_contract_dispatches_to_the_model(models, clock, tmp_path):
    router = video_router(models, clock)
    req = vreq(duration_s=2)
    assert router.estimate(req) == pytest.approx(0.20)
    handle = router.submit(req)
    assert handle.startswith("std-a|fake-")
    assert router.poll(handle)["status"] == "done" and router.cost(handle) == pytest.approx(0.20)
    assert router.download(handle, tmp_path, name="x").name == "x.mp4"
    router.cancel(handle)
    described = router.describe()
    assert described["mode"] == "fake" and {m["id"] for m in described["models"]} >= {"std-a", "pre-a"}
