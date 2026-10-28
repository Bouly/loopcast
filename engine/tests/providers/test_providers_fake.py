"""Faux fournisseur : de vrais fichiers (vérifiés par ffprobe / Pillow), déterministes, lenteur et échecs simulés."""

import hashlib

import pytest
from PIL import Image
from providers_testkit import TEST_SCALE, epoch, image_model, video_model

from loopcast.providers import catalog
from loopcast.providers.base import ImageRequest, ProviderError, VideoRequest, probe_video
from loopcast.providers.fake import FakeImageProvider, FakeVideoProvider


def _generate(provider, req, dest, **kw):
    handle = provider.submit(req)
    assert provider.poll(handle)["status"] == "done"
    return provider.download(handle, dest, **kw)


def test_real_vertical_mp4_at_requested_duration(tmp_path):
    """Taille réelle (1080 × 1920), durée exacte, son seulement si demandé."""
    model = catalog.find(catalog.video_models(), "h3-max-768p")
    fake = FakeVideoProvider(model)
    path = _generate(fake, VideoRequest(prompt="A runner at dawn, slow motion", duration_s=5, audio=True),
                     tmp_path, name="shot-00")
    info = probe_video(path)
    assert path.name == "shot-00.mp4"
    assert (info.width, info.height) == (1080, 1920)
    assert info.duration_s == pytest.approx(5.0, abs=0.05)
    assert info.has_audio and "mp4" in info.format
    assert fake.estimate(VideoRequest(prompt="x", duration_s=5)) == 0.0          # gratuit
    muted = _generate(FakeVideoProvider(model, scale=TEST_SCALE),
                      VideoRequest(prompt="Same, muted", duration_s=3.5), tmp_path, name="muted")
    assert not probe_video(muted).has_audio
    assert probe_video(muted).duration_s == pytest.approx(3.5, abs=0.05)


def test_fixed_durations_round_up(tmp_path):
    """Un modèle à durées fixes (4/6/8 s) rend 6 s pour 5 s demandées : la composition coupe."""
    veo_like = video_model("veo-like", durations=(4, 6, 8), duration_format="{n}s")
    path = _generate(FakeVideoProvider(veo_like, scale=TEST_SCALE), VideoRequest(prompt="Waves", duration_s=5),
                     tmp_path)
    assert probe_video(path).duration_s == pytest.approx(6.0, abs=0.05)
    assert (probe_video(path).width, probe_video(path).height) == (270, 480)


def test_deterministic_bytes(tmp_path):
    req = VideoRequest(prompt="A cat on a windowsill", duration_s=2, seed=7)
    a = _generate(FakeVideoProvider(video_model("m"), scale=TEST_SCALE), req, tmp_path / "a")
    b = _generate(FakeVideoProvider(video_model("m"), scale=TEST_SCALE), req, tmp_path / "b")
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
    assert digest(a) == digest(b)


def test_image_to_video_uses_the_start_image(tmp_path):
    start = tmp_path / "screen.png"
    Image.new("RGB", (1290, 2796), (20, 120, 200)).save(start)
    path = _generate(FakeVideoProvider(video_model("m"), scale=TEST_SCALE),
                     VideoRequest(prompt="App screen, slow zoom", duration_s=2, image_path=str(start)), tmp_path)
    info = probe_video(path)
    assert (info.width, info.height) == (270, 480) and info.duration_s == pytest.approx(2.0, abs=0.05)


def test_simulated_delay_and_failures(tmp_path, clock):
    fake = FakeVideoProvider(video_model("m"), scale=TEST_SCALE, delay_s=30, fail_first=1, clock=epoch(clock))
    req = VideoRequest(prompt="Rain on a window", duration_s=2)
    failing, ok = fake.submit(req), fake.submit(req)
    assert fake.poll(ok)["status"] == "queued"
    clock.advance(seconds=15)
    st = fake.poll(ok)
    assert st["status"] == "running" and st["progress"] == pytest.approx(0.5)
    clock.advance(seconds=16)
    assert fake.poll(ok)["status"] == "done"
    assert fake.poll(failing) == {"status": "failed", "error": "échec simulé par le faux fournisseur",
                                  "progress": None, "retryable": True}
    with pytest.raises(ProviderError):
        fake.download(failing, tmp_path)
    assert len(fake.submitted) == 2


def test_handle_survives_a_new_instance(tmp_path):
    """Après un redémarrage, un autre objet sait reprendre la génération (tout est dans l'identifiant)."""
    handle = FakeVideoProvider(video_model("m"), scale=TEST_SCALE).submit(VideoRequest(prompt="Dunes", duration_s=1))
    again = FakeVideoProvider(video_model("m"), scale=TEST_SCALE)
    assert again.poll(handle)["status"] == "done"
    assert probe_video(again.download(handle, tmp_path)).duration_s == pytest.approx(1.0, abs=0.05)


def test_billing_mode_reports_catalog_price():
    fake = FakeVideoProvider(video_model("m", usd_per_s=0.08), bill=True)
    handle = fake.submit(VideoRequest(prompt="x", duration_s=5))
    assert fake.estimate(VideoRequest(prompt="x", duration_s=5)) == pytest.approx(0.40)
    assert fake.cost(handle) == pytest.approx(0.40)
    assert FakeVideoProvider(video_model("m"), bill=True, report_cost=False).cost(handle) is None


def test_fake_image_is_a_vertical_png(tmp_path):
    fake = FakeImageProvider(image_model("img"), scale=TEST_SCALE)
    path = _generate(fake, ImageRequest(prompt="Pastel gradient background with a phone"), tmp_path, name="image-00")
    with Image.open(path) as img:
        assert img.format == "PNG" and img.size == (270, 480)
