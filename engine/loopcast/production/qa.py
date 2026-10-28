"""Contrôle qualité des rendus : rien de bâclé ne doit atteindre la validation humaine.

Vidéo : ffprobe (durée 6 à 60 s, 1080×1920, H.264 en yuv420p, ≤ 50 Mo, piste audio si attendue), puis une
seule passe ffmpeg pour les passages noirs (blackdetect), les images figées (freezedetect) et le volume
(volumedetect). Carrousel : nombre d'images, taille 1080×1920, image vide.

Chaque raison d'échec est écrite en français, pour l'équipe. Un échec est « transitoire » quand une
nouvelle production a des chances de le corriger : fichier illisible, ou défaut situé dans un plan
généré par IA (on régénère ce plan). Un défaut de rendu Remotion, déterministe, ne l'est pas.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loopcast.production import options

WIDTH, HEIGHT = 1080, 1920
CAROUSEL_RANGE = (2, 10)          # Instagram : 10 images au plus par carrousel
IMAGE_MAX_MB = 8.0                # Instagram refuse les images plus lourdes (converties en JPEG à la publication)
DETECT_BLACK_S = 0.25             # passages noirs relevés (échec au-delà de qa.black_min_s)
DETECT_FREEZE_S = 2.0             # images figées relevées (échec au-delà de qa.freeze_min_s)
BLACK_PIXEL = 0.02                # un pixel est noir sous 2 % de luminance (les fonds sombres des formats passent)


class QAError(RuntimeError):
    """Le fichier n'a pas pu être analysé (illisible, outil absent, délai dépassé)."""


def fr(x: float, digits: int = 1) -> str:
    """4.25 → « 4,3 » (affichage pour l'équipe)."""
    return f"{x:.{digits}f}".replace(".", ",")


@dataclass
class Failure:
    reason: str
    transient: bool = False
    shots: list[int] = field(default_factory=list)   # plans IA en cause


@dataclass
class Report:
    kind: str                                         # video | carousel
    failures: list[Failure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def fail(self, reason: str, *, transient: bool = False, shots: list[int] | None = None) -> None:
        self.failures.append(Failure(reason, transient, list(shots or [])))

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def reasons(self) -> list[str]:
        return [f.reason for f in self.failures]

    @property
    def transient(self) -> bool:
        """Transitoire seulement si TOUTES les raisons le sont : un défaut déterministe reviendrait."""
        return bool(self.failures) and all(f.transient for f in self.failures)

    @property
    def regenerate(self) -> list[int]:
        return sorted({i for f in self.failures for i in f.shots})

    def as_dict(self) -> dict:
        return {"ok": self.ok, "kind": self.kind, "reasons": self.reasons, "warnings": self.warnings,
                "transient": self.transient, "regenerate": self.regenerate, **self.details}


# --- Outils --------------------------------------------------------------------------------------------

def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise QAError(f"{Path(cmd[0]).name} : délai de {timeout:.0f} s dépassé") from e
    except OSError as e:
        raise QAError(f"{Path(cmd[0]).name} introuvable : {e}") from e


def _need(path: str | None, name: str) -> str:
    if not path:
        raise QAError(f"{name} introuvable : installer ffmpeg (brew install ffmpeg) ou régler production.{name}")
    return path


def probe(path: Path | str, ffprobe: str | None = None, timeout: float = 60) -> dict:
    """ffprobe en JSON ; QAError si le fichier est absent ou illisible."""
    path = Path(path)
    if not path.is_file():
        raise QAError(f"fichier absent : {path.name}")
    cmd = [_need(ffprobe or options.ffprobe_bin(), "ffprobe"), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    out = _run(cmd, timeout)
    if out.returncode != 0:
        raise QAError(f"fichier illisible ({path.name}) : {out.stderr.strip()[-300:]}")
    try:
        return json.loads(out.stdout)
    except ValueError as e:
        raise QAError(f"ffprobe : réponse illisible pour {path.name}") from e


def duration_of(info: dict) -> float:
    try:
        return float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError) as e:
        raise QAError("durée inconnue") from e


def has_audio(info: dict) -> bool:
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))


def video_stream(info: dict) -> dict | None:
    return next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)


def _fps(rate: str | None) -> float:
    num, _, den = (rate or "0/1").partition("/")
    try:
        return round(float(num) / float(den or 1), 2) if float(den or 1) else 0.0
    except ValueError:
        return 0.0


_BLACK = re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)")
_FREEZE_START = re.compile(r"freeze_start:\s*([\d.]+)")
_FREEZE_END = re.compile(r"freeze_end:\s*([\d.]+)")
_MAX_VOLUME = re.compile(r"max_volume:\s*(-?[\d.]+|-inf) dB")
_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([\d.]+)")


def scan(path: Path | str, duration_s: float, *, audio: bool, ffmpeg: str | None = None) -> dict:
    """Une passe ffmpeg : passages noirs, images figées, volume max. Intervalles en secondes."""
    cmd = [_need(ffmpeg or options.ffmpeg_bin(), "ffmpeg"), "-hide_banner", "-nostats", "-v", "info",
           "-i", str(path), "-map", "0:v:0",
           "-vf", f"blackdetect=d={DETECT_BLACK_S}:pix_th={BLACK_PIXEL},freezedetect=n=-60dB:d={DETECT_FREEZE_S}"]
    if audio:
        cmd += ["-map", "0:a:0", "-af", "volumedetect"]
    cmd += ["-f", "null", "-"]
    out = _run(cmd, timeout=max(120.0, duration_s * 10))
    if out.returncode != 0:
        raise QAError(f"analyse ffmpeg impossible : {out.stderr.strip()[-300:]}")
    log = out.stderr
    black = [[float(a), float(b)] for a, b in _BLACK.findall(log)]
    starts = [float(x) for x in _FREEZE_START.findall(log)]
    ends = [float(x) for x in _FREEZE_END.findall(log)]
    freeze = [[s, ends[i] if i < len(ends) else round(duration_s, 3)] for i, s in enumerate(starts)]
    vol = _MAX_VOLUME.search(log)
    max_db = None
    if vol:
        max_db = float("-inf") if vol.group(1) == "-inf" else float(vol.group(1))
    return {"black": black, "freeze": freeze, "max_db": max_db}


def speech_bounds(path: Path | str, duration_s: float, ffmpeg: str | None = None,
                  noise_db: float = -35.0) -> tuple[float, float] | None:
    """Début et fin de la parole dans un clip (silences du début et de la fin coupés) ; None sans voix."""
    cmd = [_need(ffmpeg or options.ffmpeg_bin(), "ffmpeg"), "-hide_banner", "-nostats", "-v", "info",
           "-i", str(path), "-map", "0:a:0", "-af", f"silencedetect=noise={noise_db}dB:d=0.3", "-f", "null", "-"]
    out = _run(cmd, timeout=max(60.0, duration_s * 5))
    if out.returncode != 0:
        return None
    starts = [max(0.0, float(x)) for x in _SILENCE_START.findall(out.stderr)]
    ends = [float(x) for x in _SILENCE_END.findall(out.stderr)]
    silences = [(s, ends[i] if i < len(ends) else duration_s) for i, s in enumerate(starts)]
    begin, end = 0.0, duration_s
    if silences and silences[0][0] <= 0.05:
        begin = silences[0][1]
    if silences and silences[-1][1] >= duration_s - 0.05:
        end = silences[-1][0]
    if end - begin < 0.5:
        return None                      # rien d'audible
    return begin, end


def _overlaps(interval: list[float], timeline: list[dict], min_overlap: float = 0.1) -> list[dict]:
    a, b = interval
    return [s for s in timeline if min(b, s["end"]) - max(a, s["start"]) >= min_overlap]


def _shot_list(shots: list[dict]) -> str:
    return ", ".join(str(s["index"] + 1) for s in shots)


# --- Contrôles -------------------------------------------------------------------------------------------

def check_video(path: Path | str, settings: dict | None = None, *, expect_audio: bool = False,
                timeline: list[dict] | None = None) -> Report:
    """Contrôle complet d'une vidéo. `timeline` (plans rendus : index, kind, start, end, ai) rattache un
    défaut à un plan IA, donc dit quoi régénérer."""
    limits = options.qa_limits(settings or {})
    ffmpeg, ffprobe = options.ffmpeg_bin(settings), options.ffprobe_bin(settings)
    report = Report("video")
    path = Path(path)
    try:
        info = probe(path, ffprobe)
        duration = duration_of(info)
    except QAError as e:
        report.fail(f"Fichier illisible : {e}.", transient=True)
        return report
    size_mb = int(info.get("format", {}).get("size") or path.stat().st_size) / 1_000_000
    v = video_stream(info) or {}
    fps = _fps(v.get("avg_frame_rate") or v.get("r_frame_rate"))
    audio = has_audio(info)
    report.details["probe"] = {"duration_s": round(duration, 2), "width": v.get("width"), "height": v.get("height"),
                               "codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"), "fps": fps,
                               "size_mb": round(size_mb, 2), "audio": audio}
    if not v:
        report.fail("Aucune piste vidéo dans le fichier.")
        return report

    if duration < limits["min_duration_s"]:
        report.fail(f"Trop courte : {fr(duration)} s, {fr(limits['min_duration_s'], 0)} s au minimum.")
    elif duration > limits["max_duration_s"]:
        report.fail(f"Trop longue : {fr(duration)} s, {fr(limits['max_duration_s'], 0)} s au maximum.")
    if (v.get("width"), v.get("height")) != (WIDTH, HEIGHT):
        report.fail(f"Mauvaise taille : {v.get('width')}×{v.get('height')}, {WIDTH}×{HEIGHT} attendu (vertical 9:16).")
    if v.get("codec_name") != "h264":
        report.fail(f"Codec {v.get('codec_name')} : H.264 attendu (lu partout).")
    if v.get("pix_fmt") not in (None, "yuv420p"):
        report.fail(f"Format de pixels {v.get('pix_fmt')} : yuv420p attendu (sinon illisible sur certains iPhone).")
    if size_mb > limits["max_mb"]:
        report.fail(f"Trop lourde : {fr(size_mb)} Mo, {fr(limits['max_mb'], 0)} Mo au maximum.")
    if fps and not 23 <= fps <= 61:
        report.warnings.append(f"Cadence inhabituelle : {fr(fps)} images/s.")

    ai_shots = [s for s in (timeline or []) if s.get("ai")]
    ugc = [s["index"] for s in ai_shots if s.get("kind") == "ugc_avatar"]
    if expect_audio and not audio:
        report.fail("Pas de piste audio alors que la vidéo doit parler.", transient=bool(ugc), shots=ugc)

    try:
        found = scan(path, duration, audio=expect_audio and audio, ffmpeg=ffmpeg)
    except QAError as e:
        report.fail(f"Analyse impossible : {e}.", transient=True)
        return report
    max_db = found["max_db"]
    report.details.update(black=found["black"], freeze=found["freeze"],
                          max_db=None if max_db in (None, float("-inf")) else max_db)

    for interval in found["black"]:
        length = interval[1] - interval[0]
        hit = _overlaps(interval, ai_shots)
        if length >= limits["black_min_s"]:
            report.fail(f"Image noire de {fr(interval[0])} à {fr(interval[1])} s"
                        + (f" (plan IA {_shot_list(hit)})" if hit else "") + ".",
                        transient=bool(hit), shots=[s["index"] for s in hit])
        elif interval[0] <= 0.05:
            report.warnings.append(f"La vidéo s'ouvre sur du noir ({fr(length)} s).")
    for interval in found["freeze"]:
        length = interval[1] - interval[0]
        if length >= limits["freeze_min_s"]:
            hit = _overlaps(interval, ai_shots)
            report.fail(f"Image figée pendant {fr(length)} s, de {fr(interval[0])} à {fr(interval[1])} s"
                        + (f" (plan IA {_shot_list(hit)})" if hit else "") + ".",
                        transient=bool(hit), shots=[s["index"] for s in hit])
    if expect_audio and audio and (max_db is None or max_db < limits["silent_db"]):
        level = "silence total" if max_db in (None, float("-inf")) else f"{fr(max_db)} dB au plus"
        report.fail(f"Piste audio muette ({level}) alors que la vidéo doit parler.", transient=bool(ugc), shots=ugc)
    return report


def check_carousel(paths: list[Path | str], expected: int | None = None) -> Report:
    """Carrousel : nombre d'images, taille 1080×1920, poids, image vide."""
    from PIL import Image

    report = Report("carousel")
    report.details["files"] = len(paths)
    lo, hi = CAROUSEL_RANGE
    if expected is not None and len(paths) != expected:
        report.fail(f"{len(paths)} images au lieu de {expected}.")
    if not lo <= len(paths) <= hi:
        report.fail(f"{len(paths)} images : un carrousel en compte de {lo} à {hi}.")
    for n, p in enumerate(paths, 1):
        p = Path(p)
        try:
            with Image.open(p) as img:
                img.load()
                size = img.size
                low, high = img.convert("L").getextrema()
        except OSError:
            report.fail(f"Image {n} absente ou illisible.", transient=True)
            continue
        if size != (WIDTH, HEIGHT):
            report.fail(f"Image {n} : {size[0]}×{size[1]}, {WIDTH}×{HEIGHT} attendu.")
        if high - low < 8:
            report.fail(f"Image {n} vide (une seule couleur).")
        mb = p.stat().st_size / 1_000_000
        if mb > IMAGE_MAX_MB:
            report.warnings.append(f"Image {n} lourde : {fr(mb)} Mo (Instagram : {fr(IMAGE_MAX_MB, 0)} Mo au plus).")
    return report


def make_poster(source: Path | str, dest: Path | str, *, is_video: bool, ffmpeg: str | None = None,
                at_s: float = 1.0, width: int = 540) -> Path:
    """Image d'aperçu (JPEG) pour la file de validation : une image du début de la vidéo, ou la 1re slide."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".tmp.jpg")
    if is_video:
        cmd = [_need(ffmpeg or options.ffmpeg_bin(), "ffmpeg"), "-v", "error", "-y", "-ss", f"{at_s:.2f}",
               "-i", str(source), "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(tmp)]
        out = _run(cmd, timeout=60)
        if out.returncode != 0 or not tmp.exists():
            raise QAError(f"aperçu impossible : {out.stderr.strip()[-200:]}")
    else:
        from PIL import Image

        with Image.open(source) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((width, width * 4))
            rgb.save(tmp, "JPEG", quality=85)
    tmp.replace(dest)
    return dest
