"""Ce que le rendu reçoit de l'app : captures et vidéos de démo copiées sous render/public/, marque, appel à l'action.

Les fichiers de l'équipe sont sous data/apps/<app_id>/ (table app_assets) ; Remotion ne lit que render/public/.
On y publie chaque asset sous un nom stable (id + empreinte) : render/public/apps/<app_id>/<id>-<sha>.<ext>,
référencé dans les props par son chemin relatif (« apps/habitudo/12-3fa9c1d2e4.png »).
Les clips générés d'un contenu vont dans render/public/content/<content_id>/, effacés après le rendu.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from loopcast.jobs import Permanent
from loopcast.production.store import loads
from loopcast.schemas import ProductBrief

DEFAULT_ACCENT = "#5B5BF7"
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
IMAGE_KINDS = ("screenshot", "logo", "other")
VIDEO_KINDS = ("demo_video",)


def render_dir(config: Any) -> Path:
    return Path(config.root) / "render"


def public_dir(config: Any) -> Path:
    return render_dir(config) / "public"


def app_dir(config: Any, app_id: str) -> Path:
    return Path(config.data_dir) / "apps" / app_id


def publish_file(src: Path, dest: Path) -> None:
    """Copie (lien physique si possible, instantané) sans jamais laisser un fichier à moitié écrit."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == src.stat().st_size:
        return
    tmp = dest.with_name(f".{dest.name}.tmp")
    tmp.unlink(missing_ok=True)
    try:
        os.link(src, tmp)
    except OSError:
        shutil.copy2(src, tmp)
    tmp.replace(dest)


def asset(conn: sqlite3.Connection, app_id: str, asset_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM app_assets WHERE id=? AND app_id=?", (asset_id, app_id)).fetchone()
    if row is None:
        raise Permanent(f"asset {asset_id} introuvable pour l'app {app_id}")
    return row


def check_usable(row: sqlite3.Row, *, video: bool, where: str) -> None:
    """La capture convient-elle à ce plan ? (type de fichier, avis de Claude sur la capture)"""
    is_video = row["kind"] in VIDEO_KINDS or str(row["mime"] or "").startswith("video/")
    if video and not is_video:
        raise Permanent(f"{where} : l'asset {row['id']} ({row['kind']}) n'est pas une vidéo de démo")
    if not video and is_video:
        raise Permanent(f"{where} : l'asset {row['id']} est une vidéo, une capture d'écran est attendue")
    analysis = loads(row["analysis"], {}) or {}
    if analysis.get("usable_in_video") is False:
        why = analysis.get("caution") or "jugée inutilisable telle quelle"
        raise Permanent(f"{where} : l'asset {row['id']} ne doit pas être montré en vidéo ({why})")


def publish_asset(conn: sqlite3.Connection, config: Any, app_id: str, asset_id: int, *, video: bool,
                  where: str) -> tuple[str, sqlite3.Row]:
    """Copie l'asset sous render/public/apps/<app_id>/ ; renvoie (chemin relatif à public/, ligne)."""
    row = asset(conn, app_id, asset_id)
    check_usable(row, video=video, where=where)
    src = app_dir(config, app_id) / row["path"]
    if not src.is_file():
        raise Permanent(f"{where} : fichier de l'asset {asset_id} absent ({src})")
    suffix = Path(row["path"]).suffix.lower() or (".mp4" if video else ".png")
    rel = f"apps/{app_id}/{asset_id}-{(row['sha256'] or 'x')[:10]}{suffix}"
    publish_file(src, public_dir(config) / rel)
    return rel, row


def _legacy_brand(config: Any, app_id: str) -> dict:
    """brands/<app_id>.json : valeur initiale tant que l'app n'a pas sa marque en base."""
    path = Path(config.root) / "brands" / f"{app_id}.json"
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        return {}


def brand(conn: sqlite3.Connection, config: Any, app_id: str, lang: str) -> tuple[dict, list[str]]:
    """La marque pour Remotion ({name, accent, accentInk?, handle?, icon?, storeLine?}) et des avertissements."""
    row = conn.execute("SELECT name, brand FROM apps WHERE id=?", (app_id,)).fetchone()
    if row is None:
        raise Permanent(f"app inconnue : {app_id}")
    raw = {**_legacy_brand(config, app_id), **(loads(row["brand"], {}) or {})}
    warnings: list[str] = []
    accent = raw.get("accent")
    if not isinstance(accent, str) or not _HEX.match(accent):
        warnings.append("couleur de marque absente ou invalide : couleur par défaut")
        accent = DEFAULT_ACCENT
    out: dict = {"name": row["name"] or raw.get("name") or app_id, "accent": accent}
    if isinstance(raw.get("accentInk"), str) and _HEX.match(raw["accentInk"]):
        out["accentInk"] = raw["accentInk"]
    if raw.get("handle"):
        out["handle"] = str(raw["handle"])
    store = raw.get("storeLine")
    if isinstance(store, dict) and store.get(lang):
        out["storeLine"] = str(store[lang])
    elif isinstance(store, str) and store:
        out["storeLine"] = store
    icon = raw.get("icon")
    if isinstance(icon, int) and not isinstance(icon, bool):
        try:
            out["icon"], _ = publish_asset(conn, config, app_id, icon, video=False, where="icône de la marque")
        except Permanent as e:
            warnings.append(f"icône non utilisée ({e})")
    return out, warnings


def approved_brief(conn: sqlite3.Connection, app_id: str) -> ProductBrief | None:
    row = conn.execute("SELECT brief FROM app_briefs WHERE app_id=? AND approved_at IS NOT NULL "
                       "ORDER BY version DESC LIMIT 1", (app_id,)).fetchone()
    if row is None:
        return None
    try:
        return ProductBrief.model_validate_json(row["brief"])
    except ValueError:
        return None


def cta(conn: sqlite3.Connection, app_id: str, lang: str, app_name: str, explicit: str | None = None) -> str:
    """L'appel à l'action : celui de l'idée, sinon celui de la fiche produit approuvée, sinon générique."""
    if explicit and explicit.strip():
        return explicit.strip()
    brief = approved_brief(conn, app_id)
    if brief is not None:
        text = getattr(brief.cta, lang, "") or ""
        if text.strip():
            return text.strip()
    return f"Télécharge {app_name}" if lang == "fr" else f"Get {app_name}"
