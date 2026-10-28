"""Contrôle qualité sur de vrais petits fichiers générés par ffmpeg."""

import pytest

from loopcast.production import qa

from .conftest import make_png, make_video, needs_ffmpeg

pytestmark = needs_ffmpeg


def test_good_video_passes(tmp_path):
    report = qa.check_video(make_video(tmp_path / "ok.mp4", 7))
    assert report.ok, report.reasons
    probe = report.details["probe"]
    assert (probe["width"], probe["height"], probe["codec"], probe["pix_fmt"]) == (1080, 1920, "h264", "yuv420p")
    assert probe["duration_s"] == pytest.approx(7, abs=0.2) and probe["audio"] is False
    assert report.as_dict()["ok"] is True


def test_too_short_and_wrong_size_are_permanent(tmp_path):
    short = qa.check_video(make_video(tmp_path / "short.mp4", 3))
    assert not short.ok and short.reasons == ["Trop courte : 3,0 s, 6 s au minimum."] and not short.transient
    small = qa.check_video(make_video(tmp_path / "small.mp4", 7, (720, 1280)))
    assert any("Mauvaise taille : 720×1280, 1080×1920 attendu" in r for r in small.reasons)


def test_black_frames_fail(tmp_path):
    report = qa.check_video(make_video(tmp_path / "black.mp4", 8, black=(2.0, 4.0)))
    assert not report.ok
    assert any(r.startswith("Image noire de 2,0 à 4,") for r in report.reasons), report.reasons
    assert report.details["black"] and not report.transient


def test_frozen_video_fails(tmp_path):
    report = qa.check_video(make_video(tmp_path / "still.mp4", 7, source="still"))
    assert any(r.startswith("Image figée pendant") for r in report.reasons), report.reasons


def test_defect_in_an_ai_shot_is_transient(tmp_path):
    """Un passage noir dans un plan IA : nouvelle tentative possible, en régénérant ce plan seulement."""
    timeline = [{"index": 0, "kind": "ai_video", "ai": True, "start": 0.0, "end": 3.0},
                {"index": 1, "kind": "app_screenshot", "ai": False, "start": 3.0, "end": 8.0}]
    report = qa.check_video(make_video(tmp_path / "ai.mp4", 8, black=(0.5, 2.5)), timeline=timeline)
    assert report.transient and report.regenerate == [0]
    assert "(plan IA 1)" in report.reasons[0]
    mixed = qa.check_video(make_video(tmp_path / "mixed.mp4", 4, black=(0.5, 2.5)), timeline=timeline)
    assert not mixed.transient                       # trop courte en plus : un défaut déterministe l'emporte


def test_audio_expectations(tmp_path):
    ugc = [{"index": 0, "kind": "ugc_avatar", "ai": True, "start": 0.0, "end": 7.0}]
    missing = qa.check_video(make_video(tmp_path / "mute.mp4", 7), expect_audio=True, timeline=ugc)
    assert "Pas de piste audio alors que la vidéo doit parler." in missing.reasons
    assert missing.transient and missing.regenerate == [0]
    silent = qa.check_video(make_video(tmp_path / "silent.mp4", 7, audio="silent"), expect_audio=True)
    assert any(r.startswith("Piste audio muette") for r in silent.reasons) and not silent.transient
    voiced = qa.check_video(make_video(tmp_path / "tone.mp4", 7, audio="tone"), expect_audio=True)
    assert voiced.ok, voiced.reasons
    assert voiced.details["max_db"] > -20


def test_unreadable_file_is_transient(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"pas une video")
    report = qa.check_video(broken)
    assert report.transient and report.reasons[0].startswith("Fichier illisible")
    assert qa.check_video(tmp_path / "absent.mp4").transient


def test_speech_bounds_cut_silences(tmp_path):
    clip = make_video(tmp_path / "ugc.mp4", 6, audio="speech")
    start, end = qa.speech_bounds(clip, 6.0)
    assert start == pytest.approx(0.7, abs=0.15) and end == pytest.approx(4.6, abs=0.15)
    assert qa.speech_bounds(make_video(tmp_path / "silent.mp4", 6, audio="silent"), 6.0) is None


def test_carousel_checks(tmp_path):
    good = [make_png(tmp_path / f"{i}.png") for i in range(4)]
    assert qa.check_carousel(good, expected=4).ok
    report = qa.check_carousel([*good[:2], make_png(tmp_path / "small.png", (720, 1280)),
                                make_png(tmp_path / "blank.png", blank=True)], expected=5)
    assert "4 images au lieu de 5." in report.reasons
    assert "Image 3 : 720×1280, 1080×1920 attendu." in report.reasons
    assert "Image 4 vide (une seule couleur)." in report.reasons
    assert any("un carrousel en compte de 2 à 10" in r for r in qa.check_carousel(good[:1]).reasons)


def test_poster(tmp_path):
    poster = qa.make_poster(make_video(tmp_path / "v.mp4", 7), tmp_path / "poster.jpg", is_video=True, at_s=1)
    from PIL import Image

    with Image.open(poster) as img:
        assert img.format == "JPEG" and img.size[0] == 540
    still = qa.make_poster(make_png(tmp_path / "s.png"), tmp_path / "p2.jpg", is_video=False)
    assert still.exists()
