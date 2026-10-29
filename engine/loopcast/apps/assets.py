"""Les fichiers de l'app : captures, logo, vidéos de démo enregistrées sur iPhone, documents.

Rangés sous data/apps/<app_id>/<sha256><ext> : un même fichier n'est gardé qu'une fois par app
(UNIQUE(app_id, sha256)). Miniatures JPEG sous data/apps/<app_id>/thumbs/ (image de couverture pour
les vidéos). Dimensions avec Pillow (orientation EXIF comprise) ; durée et dimensions des vidéos avec
ffprobe (rotation comprise) ; image de couverture et images extraites avec ffmpeg.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from loopcast import jobs
from loopcast.apps.settings import apps_settings
from loopcast.apps.store import AppError, Conflict, NotFound, dumps, get_app, iso, loads, tx

log = logging.getLogger(__name__)

ASSET_KINDS = ("screenshot", "logo", "demo_video", "document", "other")
THUMB_BOX = (480, 960)
_CHUNK = 1 << 20
# Format Pillow → (extension, type MIME). Les JPEG d'iPhone sont souvent lus comme « MPO ».
_IMAGE_FORMATS = {"PNG": (".png", "image/png"), "JPEG": (".jpg", "image/jpeg"), "MPO": (".jpg", "image/jpeg"),
                  "WEBP": (".webp", "image/webp"), "GIF": (".gif", "image/gif"), "BMP": (".bmp", "image/bmp"),
                  "TIFF": (".tif", "image/tiff")}
_VIDEO_EXT = {".mov": "video/quicktime", ".mp4": "video/mp4", ".m4v": "video/x-m4v", ".webm": "video/webm"}
_DOC_EXT = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
            ".json": "application/json", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".key": "application/x-iwork-keynote-sffkey", ".pages": "application/x-iwork-pages-sffpages",
            ".rtf": "application/rtf"}
TEXT_MIMES = ("text/plain", "text/markdown", "text/csv", "application/json")
# Affichés dans le navigateur : seulement les images matricielles et les vidéos, qui ne peuvent pas exécuter de
# script. Le reste (HTML, SVG, PDF, textes…) part en téléchargement : servi sur la même origine que l'API, un
# .html ou un .svg téléversé pourrait sinon agir dans le dashboard à la place de l'équipe.
INLINE_MIMES = frozenset(mime for _ext, mime in _IMAGE_FORMATS.values()) | frozenset(_VIDEO_EXT.values())


def served_inline(mime: str | None) -> bool:
    """Ce type de fichier peut-il s'afficher dans le navigateur (sinon : Content-Disposition: attachment) ?"""
    return (mime or "").split(";")[0].strip().lower() in INLINE_MIMES


# --- Emplacements --------------------------------------------------------------------------------------

def apps_root(config: Any) -> Path:
    return Path(config.data_dir) / "apps"


def app_dir(config: Any, app_id: str) -> Path:
    return apps_root(config) / app_id


def safe_path(config: Any, app_id: str, rel: str) -> Path:
    """Le chemin d'un fichier de l'app, refusé s'il sort de data/apps/<app_id>/."""
    root = app_dir(config, app_id).resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise AppError("chemin refusé : hors de data/apps/", 403)
    return path


def find_tool(name: str) -> str | None:
    """ffmpeg / ffprobe : chemin réglé, PATH, puis Homebrew (launchd lance avec un PATH réduit)."""
    if os.sep in name:
        return name if os.access(name, os.X_OK) else None
    found = shutil.which(name)
    if found:
        return found
    for folder in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidate = Path(folder) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


# --- Lecture des fichiers ------------------------------------------------------------------------------------

@dataclass
class FileInfo:
    media: str                  # image | video | document | other
    mime: str
    ext: str
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None


def probe_image(path: Path) -> FileInfo | None:
    from PIL import Image

    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            fmt, (w, h) = im.format, im.size
            orientation = im.getexif().get(0x0112)
    except Exception:  # noqa: BLE001 : tout échec de Pillow veut dire « pas une image lisible »
        return None
    if fmt not in _IMAGE_FORMATS:
        return None
    if orientation in (5, 6, 7, 8):            # photo tournée de 90° : on donne les dimensions affichées
        w, h = h, w
    ext, mime = _IMAGE_FORMATS[fmt]
    return FileInfo("image", mime, ext, w, h)


def probe_video(path: Path, ffprobe: str | None) -> tuple[int, int, float | None] | None:
    """(largeur, hauteur affichées, durée) d'une vidéo, ou None si ce n'en est pas une."""
    if not ffprobe:
        return None
    try:
        out = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                              str(path)], capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout or "{}") if out.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        log.warning("ffprobe en échec sur %s : %s", path.name, e)
        return None
    stream = next((s for s in data.get("streams") or [] if s.get("codec_type") == "video"
                   and not (s.get("disposition") or {}).get("attached_pic")), None)
    if stream is None or not stream.get("width"):
        return None
    w, h = int(stream["width"]), int(stream["height"])
    rotation = 0.0
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = float(side["rotation"])
    if not rotation:
        rotation = float((stream.get("tags") or {}).get("rotate") or 0)
    if int(abs(rotation)) % 180 == 90:
        w, h = h, w
    duration = (data.get("format") or {}).get("duration") or stream.get("duration")
    return w, h, round(float(duration), 3) if duration else None


def inspect(path: Path, filename: str, *, ffprobe: str | None, want_video: bool = False) -> FileInfo:
    ext = Path(filename).suffix.lower()
    image = probe_image(path)
    if image is not None:
        return image
    guessed = mimetypes.guess_type(filename)[0] or ""
    if want_video or ext in _VIDEO_EXT or guessed.startswith("video/"):
        video = probe_video(path, ffprobe)
        if video is not None:
            return FileInfo("video", _VIDEO_EXT.get(ext) or guessed or "video/mp4",
                            ext if ext in _VIDEO_EXT else ".mp4", *video)
        if ffprobe is None and ext in _VIDEO_EXT:    # sans ffprobe : on garde la vidéo, sans dimensions
            log.warning("ffprobe introuvable : %s gardée sans durée ni dimensions", filename)
            return FileInfo("video", _VIDEO_EXT[ext], ext)
    if ext in _DOC_EXT:
        return FileInfo("document", _DOC_EXT[ext], ext)
    if guessed.startswith("text/"):
        return FileInfo("document", guessed, ext)
    return FileInfo("other", guessed or "application/octet-stream", ext if re.fullmatch(r"\.[a-z0-9]{1,8}", ext) else "")


def _default_kind(info: FileInfo) -> str:
    return {"image": "screenshot", "video": "demo_video", "document": "document"}.get(info.media, "other")


def _check_kind(kind: str, info: FileInfo, filename: str) -> None:
    if kind in ("screenshot", "logo") and info.media != "image":
        raise AppError(f"« {filename} » n'est pas une image lisible (PNG, JPEG, WebP…)")
    if kind == "demo_video" and info.media != "video":
        raise AppError(f"« {filename} » n'est pas une vidéo lisible (MOV, MP4…)")


# --- Miniatures et images extraites ------------------------------------------------------------------------------

def make_image_thumb(src: Path, dest: Path) -> None:
    from PIL import Image, ImageOps

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail(THUMB_BOX)
        if im.mode in ("RGBA", "LA", "P"):
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            im = flat
        im.convert("RGB").save(dest, "JPEG", quality=82, optimize=True)


def _ffmpeg_frame(ffmpeg: str, src: Path, at_s: float, dest: Path, box: tuple[int, int]) -> bool:
    scale = f"scale=w='min({box[0]},iw)':h='min({box[1]},ih)':force_original_aspect_ratio=decrease"
    try:
        out = subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{max(0.0, at_s):.3f}", "-i", str(src),
                              "-frames:v", "1", "-vf", scale, "-q:v", "3", str(dest)],
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("ffmpeg en échec sur %s : %s", src.name, e)
        return False
    return out.returncode == 0 and dest.exists() and dest.stat().st_size > 0


def make_video_poster(ffmpeg: str | None, src: Path, dest: Path, duration_s: float | None) -> bool:
    """Image de couverture : un peu après le début (la première image d'un enregistrement d'écran
    est souvent le centre de contrôle ou un écran noir)."""
    if not ffmpeg:
        return False
    at = min(1.0, (duration_s or 0) / 3)
    return _ffmpeg_frame(ffmpeg, src, at, dest, THUMB_BOX) or (at > 0 and _ffmpeg_frame(ffmpeg, src, 0, dest, THUMB_BOX))


def video_frames(config: Any, src: Path, duration_s: float | None, count: int, dest_dir: Path) -> list[tuple[float, Path]]:
    """`count` images réparties sur la vidéo (pour que Claude la « regarde ») : [(instant, fichier)]."""
    s = apps_settings(config)
    ffmpeg = find_tool(s.ffmpeg)
    if not ffmpeg:
        raise AppError("ffmpeg introuvable : l'installer (brew install ffmpeg) ou régler apps.ffmpeg")
    duration = duration_s or 0
    times = [duration * (i + 0.5) / count for i in range(count)] if duration else [0.0]
    out = []
    for i, at in enumerate(times):
        dest = dest_dir / f"frame-{i}.jpg"
        if _ffmpeg_frame(ffmpeg, src, at, dest, (1080, 1920)):
            out.append((round(at, 1), dest))
    return out


# --- Enregistrement ------------------------------------------------------------------------------------------------

def asset_dict(r: sqlite3.Row | dict) -> dict:
    d = dict(r)
    d["analysis"] = loads(d.get("analysis"), None)
    base = f"/api/apps/{d['app_id']}/assets/{d['id']}"
    d["url"] = f"{base}/file"
    d["thumb_url"] = f"{base}/thumb" if d.get("thumb") else None
    return d


def describable(kind: str, mime: str | None) -> bool:
    """Ce que Claude regarde : captures et images, vidéos de démo. Pas le logo ni les documents."""
    if kind == "demo_video":
        return True
    return kind in ("screenshot", "other") and (mime or "").startswith("image/")


def store_asset(conn: sqlite3.Connection, config: Any, app_id: str, src: BinaryIO, filename: str, *, now: datetime,
                kind: str | None = None, caption: str = "", origin: str = "upload", source_url: str | None = None,
                parent_id: int | None = None) -> tuple[dict, bool]:
    """Range un fichier (lu par morceaux, borné) et l'inscrit. Renvoie (asset, créé ?) : un fichier déjà
    connu de l'app renvoie l'asset existant. Les captures et vidéos sont ensuite décrites par Claude."""
    app = get_app(conn, app_id)
    if kind is not None and kind not in ASSET_KINDS:
        raise AppError(f"type d'asset inconnu : « {kind} » ({', '.join(ASSET_KINDS)})")
    filename = Path(filename or "fichier").name[:200]
    s = apps_settings(config)
    limit = s.max_upload_mb * 1_000_000
    folder = app_dir(config, app_id)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".upload-{uuid.uuid4().hex}.part"
    try:
        digest, size = hashlib.sha256(), 0
        with tmp.open("wb") as out:
            while chunk := src.read(_CHUNK):
                size += len(chunk)
                if size > limit:
                    raise AppError(f"« {filename} » est trop lourd ({s.max_upload_mb} Mo au plus)", 413)
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise AppError(f"« {filename} » est vide")
        sha = digest.hexdigest()
        existing = conn.execute("SELECT * FROM app_assets WHERE app_id=? AND sha256=?", (app_id, sha)).fetchone()
        if existing is not None:
            path = safe_path(config, app_id, existing["path"])
            if not path.exists():                       # fichier perdu sur le disque : on le remet
                os.replace(tmp, path)
            return asset_dict(existing), False
        ffprobe = find_tool(s.ffprobe)
        info = inspect(tmp, filename, ffprobe=ffprobe, want_video=kind == "demo_video")
        kind = kind or _default_kind(info)
        _check_kind(kind, info, filename)
        rel = f"{sha}{info.ext}"
        final = folder / rel
        os.replace(tmp, final)
        thumb = _make_thumb(config, final, info, app_id, sha)
        with tx(conn):
            try:
                cur = conn.execute(
                    """INSERT INTO app_assets(app_id, kind, path, filename, mime, bytes, width, height, duration_s,
                                              sha256, caption, created_at, origin, source_url, thumb)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (app_id, kind, rel, filename, info.mime, size, info.width, info.height, info.duration_s, sha,
                     (caption or "").strip()[:1000], iso(now), origin, source_url, thumb))
            except sqlite3.IntegrityError:              # le même fichier envoyé deux fois en même temps
                row = conn.execute("SELECT * FROM app_assets WHERE app_id=? AND sha256=?", (app_id, sha)).fetchone()
                return asset_dict(row), False
            asset_id = cur.lastrowid
            if kind == "logo" and not app["brand"].get("icon"):
                _set_icon(conn, app, asset_id, now)
            if describable(kind, info.mime):
                jobs.enqueue(conn, "apps.describe_asset", {"asset_id": asset_id}, key=f"apps.describe_asset:{asset_id}",
                             app_id=app_id, parent_id=parent_id, clock=lambda: now)
        return get_asset(conn, app_id, asset_id), True
    finally:
        tmp.unlink(missing_ok=True)


def _make_thumb(config: Any, path: Path, info: FileInfo, app_id: str, sha: str) -> str | None:
    thumbs = app_dir(config, app_id) / "thumbs"
    thumbs.mkdir(exist_ok=True)
    dest = thumbs / f"{sha}.jpg"
    try:
        if info.media == "image":
            make_image_thumb(path, dest)
        elif info.media == "video":
            if not make_video_poster(find_tool(apps_settings(config).ffmpeg), path, dest, info.duration_s):
                return None
        else:
            return None
    except Exception as e:  # noqa: BLE001 : une miniature ratée n'empêche pas de garder le fichier
        log.warning("miniature impossible pour %s : %s", path.name, e)
        return None
    return f"thumbs/{dest.name}"


def _set_icon(conn: sqlite3.Connection, app: dict, asset_id: int | None, now: datetime) -> None:
    brand = {k: v for k, v in app["brand"].items() if k != "icon"}
    if asset_id is not None:
        brand["icon"] = asset_id
    conn.execute("UPDATE apps SET brand=?, updated_at=? WHERE id=?", (dumps(brand), iso(now), app["id"]))


def import_brand_files(conn: sqlite3.Connection, config: Any, app_id: str, data: dict, *, now: datetime) -> int:
    """Icône et captures citées par brands/<id>.json (chemins relatifs au dépôt ou à brands/)."""
    files = data.get("assets") or {}
    wanted = [("logo", files.get("icon"))] + [("screenshot", p) for p in files.get("screens") or []]
    imported = 0
    for kind, rel in wanted:
        if not isinstance(rel, str) or not rel:
            continue
        path = next((p for p in (Path(config.root) / rel, Path(config.root) / "brands" / rel) if p.is_file()), None)
        if path is None:
            log.warning("brands/%s.json : fichier introuvable : %s", app_id, rel)
            continue
        with path.open("rb") as f:
            _asset, created = store_asset(conn, config, app_id, f, path.name, now=now, kind=kind, origin="brand")
        imported += int(created)
    return imported


# --- Lecture, modification, suppression ------------------------------------------------------------------------------

def list_assets(conn: sqlite3.Connection, app_id: str, kind: str | None = None) -> list[dict]:
    get_app(conn, app_id)
    sql, args = "SELECT * FROM app_assets WHERE app_id=?", [app_id]
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    return [asset_dict(r) for r in conn.execute(sql + " ORDER BY kind, id", args)]


def get_asset(conn: sqlite3.Connection, app_id: str, asset_id: int) -> dict:
    r = conn.execute("SELECT * FROM app_assets WHERE id=? AND app_id=?", (asset_id, app_id)).fetchone()
    if r is None:
        raise NotFound(f"asset {asset_id} inconnu pour cette app")
    return asset_dict(r)


def update_asset(conn: sqlite3.Connection, app_id: str, asset_id: int, *, now: datetime, caption: str | None = None,
                 kind: str | None = None) -> dict:
    """Légende (ce que l'équipe en dit) et type. Une nouvelle légende fait redécrire la capture."""
    with tx(conn):
        asset = get_asset(conn, app_id, asset_id)
        if caption is not None:
            caption = caption.strip()[:1000]
            conn.execute("UPDATE app_assets SET caption=? WHERE id=?", (caption, asset_id))
        if kind is not None and kind != asset["kind"]:
            if kind not in ASSET_KINDS:
                raise AppError(f"type d'asset inconnu : « {kind} » ({', '.join(ASSET_KINDS)})")
            media = "video" if asset.get("duration_s") is not None or (asset["mime"] or "").startswith("video/") else (
                "image" if (asset["mime"] or "").startswith("image/") else "document")
            _check_kind(kind, FileInfo(media, asset["mime"] or "", ""), asset["filename"] or str(asset_id))
            conn.execute("UPDATE app_assets SET kind=? WHERE id=?", (kind, asset_id))
            app = get_app(conn, app_id)
            if kind == "logo" and not app["brand"].get("icon"):
                _set_icon(conn, app, asset_id, now)
    updated = get_asset(conn, app_id, asset_id)
    if caption is not None and caption != (asset.get("caption") or "") and describable(updated["kind"], updated["mime"]):
        request_description(conn, app_id, asset_id, now=now)
    return updated


def delete_asset(conn: sqlite3.Connection, config: Any, app_id: str, asset_id: int, *, now: datetime) -> None:
    with tx(conn):
        asset = get_asset(conn, app_id, asset_id)
        conn.execute("DELETE FROM app_assets WHERE id=?", (asset_id,))
        app = get_app(conn, app_id)
        if app["brand"].get("icon") == asset_id:
            _set_icon(conn, app, None, now)
    for rel in (asset["path"], asset.get("thumb")):
        if rel:
            safe_path(config, app_id, rel).unlink(missing_ok=True)


def request_description(conn: sqlite3.Connection, app_id: str, asset_id: int, *, now: datetime) -> int:
    """Redemande la description d'une capture (légende changée, description ratée)."""
    with tx(conn):
        asset = get_asset(conn, app_id, asset_id)
        if not describable(asset["kind"], asset["mime"]):
            raise Conflict("seules les captures, images et vidéos de démo sont décrites")
        keys = conn.execute("SELECT id, status FROM jobs WHERE key=? OR key LIKE ?",
                            (f"apps.describe_asset:{asset_id}", f"apps.describe_asset:{asset_id}:%")).fetchall()
        waiting = next((r["id"] for r in keys if r["status"] in ("queued", "running")), None)
        if waiting is not None:
            return waiting
        return jobs.enqueue(conn, "apps.describe_asset", {"asset_id": asset_id, "force": True},
                            key=f"apps.describe_asset:{asset_id}:{len(keys) + 1}", app_id=app_id, clock=lambda: now)
