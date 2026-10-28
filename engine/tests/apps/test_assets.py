"""Fichiers de l'app : envoi, dédoublonnage, dimensions, miniatures, vidéos, Range, suppression."""

import shutil
import subprocess

import pytest

from loopcast.apps import assets

from .helpers import job_row, png

HAS_FFMPEG = bool(assets.find_tool("ffmpeg") and assets.find_tool("ffprobe"))


@pytest.fixture
def app_id(api):
    assert api.post("/api/apps", json={"id": "habitudo", "name": "Habitudo"}).status_code == 201
    return "habitudo"


def upload(api, app_id, name, data, **form):
    return api.post(f"/api/apps/{app_id}/assets", files=[("files", (name, data))], data=form)


def test_upload_screenshot_dedup_and_thumbnail(api, app_id, aconn, cfg):
    data = png()
    r = upload(api, app_id, "accueil.png", data, caption="Écran du jour")
    assert r.status_code == 201
    body = r.json()
    asset = body["assets"][0]
    assert body["created"] == 1 and not asset["duplicate"]
    assert asset["kind"] == "screenshot" and asset["mime"] == "image/png"
    assert (asset["width"], asset["height"], asset["bytes"]) == (1290, 2796, len(data))
    assert asset["path"] == f"{asset['sha256']}.png" and asset["caption"] == "Écran du jour"
    folder = cfg.data_dir / "apps" / app_id
    assert (folder / asset["path"]).read_bytes() == data
    assert asset["thumb_url"] and (folder / asset["thumb"]).is_file()
    assert job_row(aconn, f"apps.describe_asset:{asset['id']}")["status"] == "queued"

    again = upload(api, app_id, "copie.png", data).json()
    assert again["created"] == 0 and again["duplicates"] == 1
    assert again["assets"][0]["id"] == asset["id"] and again["assets"][0]["duplicate"]
    assert aconn.execute("SELECT COUNT(*) FROM app_assets").fetchone()[0] == 1

    file = api.get(asset["url"])
    assert file.status_code == 200 and file.content == data
    assert file.headers["accept-ranges"] == "bytes" and file.headers["content-type"] == "image/png"
    thumb = api.get(asset["thumb_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    assert api.get(f"/api/apps/{app_id}/assets").json()[0]["id"] == asset["id"]
    assert ("apps", {"id": app_id, "change": "assets"}) in api.bus.events


def test_range_requests(api, app_id):
    data = bytes(range(256)) * 40                                    # 10 240 octets
    asset = upload(api, app_id, "notes.txt", data).json()["assets"][0]
    assert asset["kind"] == "document" and asset["thumb_url"] is None
    r = api.get(asset["url"], headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == data[100:200]
    assert r.headers["content-range"] == f"bytes 100-199/{len(data)}"
    tail = api.get(asset["url"], headers={"Range": "bytes=-16"})
    assert tail.status_code == 206 and tail.content == data[-16:]
    assert api.get(asset["url"], headers={"Range": f"bytes={len(data) + 10}-"}).status_code == 416


def test_files_are_served_from_data_apps_only(api, app_id, aconn, cfg):
    asset = upload(api, app_id, "a.png", png(100, 200)).json()["assets"][0]
    (cfg.data_dir / "secret.txt").write_text("à ne pas servir")
    aconn.execute("UPDATE app_assets SET path='../../secret.txt' WHERE id=?", (asset["id"],))
    r = api.get(asset["url"])
    assert r.status_code == 403 and "hors de data/apps" in r.json()["detail"]
    assert api.get(f"/api/apps/{app_id}/assets/999/file").status_code == 404
    assert api.get(f"/api/apps/autre/assets/{asset['id']}/file").status_code == 404


def test_wrong_kind_is_refused_and_a_batch_keeps_the_good_files(api, app_id):
    r = upload(api, app_id, "notes.txt", b"du texte", kind="screenshot")
    assert r.status_code == 400 and "n'est pas une image" in r.json()["detail"]
    r = api.post(f"/api/apps/{app_id}/assets", data={"kind": "screenshot"},
                 files=[("files", ("a.png", png(10, 20))), ("files", ("b.txt", b"texte"))])
    body = r.json()
    assert r.status_code == 201 and body["created"] == 1
    assert body["errors"] == [{"filename": "b.txt", "error": "« b.txt » n'est pas une image lisible (PNG, JPEG, WebP…)"}]
    assert upload(api, "inconnue", "a.png", png(10, 20)).status_code == 404


def test_caption_kind_and_delete(api, app_id, aconn, cfg):
    asset = upload(api, app_id, "icone.png", png(512, 512, (10, 10, 10))).json()["assets"][0]
    r = api.patch(asset["url"].removesuffix("/file"), json={"caption": "Notre icône", "kind": "logo"})
    assert r.status_code == 200 and r.json()["kind"] == "logo" and r.json()["caption"] == "Notre icône"
    assert api.get(f"/api/apps/{app_id}").json()["brand"]["icon"] == asset["id"]

    folder = cfg.data_dir / "apps" / app_id
    assert api.delete(asset["url"].removesuffix("/file")).json() == {"ok": True}
    assert not (folder / asset["path"]).exists() and not (folder / asset["thumb"]).exists()
    assert "icon" not in api.get(f"/api/apps/{app_id}").json()["brand"]
    assert aconn.execute("SELECT COUNT(*) FROM app_assets").fetchone()[0] == 0


def test_new_caption_asks_for_a_new_description(api, app_id, aconn, run):
    asset = upload(api, app_id, "a.png", png(100, 200)).json()["assets"][0]
    run(kinds=["apps.describe_asset"])
    api.patch(asset["url"].removesuffix("/file"), json={"caption": "La liste du jour"})
    job = job_row(aconn, f"apps.describe_asset:{asset['id']}:2")
    assert job["status"] == "queued" and '"force": true' in job["payload"]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe absents")
def test_demo_video_duration_size_and_poster(api, app_id, aconn, cfg, tmp_path):
    video = tmp_path / "demo.mp4"
    subprocess.run([shutil.which("ffmpeg") or assets.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc=duration=2:size=360x640:rate=10", "-pix_fmt", "yuv420p", str(video)], check=True)
    r = upload(api, app_id, "Enregistrement de l’écran.mp4", video.read_bytes())
    asset = r.json()["assets"][0]
    assert asset["kind"] == "demo_video" and asset["mime"] == "video/mp4"
    assert (asset["width"], asset["height"]) == (360, 640) and asset["duration_s"] == pytest.approx(2.0, abs=0.2)
    assert asset["thumb"] and (cfg.data_dir / "apps" / app_id / asset["thumb"]).is_file()
    assert job_row(aconn, f"apps.describe_asset:{asset['id']}")["status"] == "queued"
    head = api.get(asset["url"], headers={"Range": "bytes=0-1"})
    assert head.status_code == 206 and head.headers["content-type"] == "video/mp4"
