"""Faux fournisseur : de vrais fichiers fabriqués sur la machine, sans clé, sans réseau, sans coût.

- Vidéo : mire animée (teinte tirée du prompt) avec le texte du prompt incrusté, à la durée et au format
  demandés, muette ou avec un bip par seconde. Avec une image de départ, l'image sert de fond et un carré
  la traverse (une vidéo figée serait refusée par le contrôle qualité de la production).
- Image : dégradé (couleurs tirées du prompt) avec le texte.

Déterministe (même requête → mêmes octets) et gratuit : c'est ce qui tourne en mode démo, sans clé fal.ai,
et dans les tests. `delay_s` simule la lenteur, `fail_first` / `fail_rate` des échecs du fournisseur.
L'identifiant renvoyé par submit() contient toute la requête : il survit à un redémarrage du Mac.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import textwrap
import threading
import time
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from loopcast.providers.base import (TARGET_SIZE, ImageRequest, ProviderError, VideoRequest, check_image,
                                     check_video, find_tool, status)

FONT = Path(__file__).resolve().parents[3] / "render" / "public" / "fonts" / "Inter-Bold.otf"
FPS = 30


def _encode(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(handle: str) -> dict:
    if not handle.startswith("fake-"):
        raise ProviderError(f"identifiant inconnu du faux fournisseur : {handle[:40]}")
    data = handle[5:]
    try:
        return json.loads(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)))
    except ValueError as e:
        raise ProviderError("identifiant du faux fournisseur illisible") from e


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode()).digest()


def _fraction(text: str) -> float:
    return int.from_bytes(_digest(text)[:4], "big") / 2 ** 32


class _FakeProvider:
    name = "fake"
    kind = ""
    request_cls: type = VideoRequest

    def __init__(self, model=None, *, delay_s: float = 0.0, fail_first: int = 0, fail_rate: float = 0.0,
                 scale: float = 1.0, bill: bool = False, report_cost: bool = True,
                 clock: Callable[[], float] = time.time, font: Path | None = None):
        """`bill` : facturer le prix catalogue du modèle (tests de budget) ; sinon tout est gratuit.
        `report_cost=False` : se comporter comme fal.ai, qui ne renvoie pas le coût réel."""
        self.model = model
        self.delay_s = float(delay_s)
        self.fail_first = int(fail_first)
        self.fail_rate = float(fail_rate)
        self.scale = float(scale)
        self.bill = bill
        self.report_cost = report_cost
        self.clock = clock
        self.font = font or FONT
        self.submitted: list = []            # les requêtes reçues (les tests comptent les soumissions)
        self._lock = threading.Lock()

    # --- contrat VideoProvider / ImageProvider ---------------------------------------------------------

    def estimate(self, req) -> float:
        return self.model.price(req) if self.bill and self.model else 0.0

    def submit(self, req) -> str:
        with self._lock:
            n = len(self.submitted)
            self.submitted.append(req)
        fail = n < self.fail_first or (self.fail_rate > 0 and _fraction(f"{req.prompt}|{req.seed}|{n}") < self.fail_rate)
        payload = {"k": self.kind, "m": self.model.id if self.model else None,
                   "r": req.model_dump(exclude_none=True), "t": round(self.clock(), 3), "n": n, "f": fail}
        return "fake-" + _encode(payload)

    def poll(self, handle: str) -> dict:
        p = _decode(handle)
        elapsed = max(0.0, self.clock() - p["t"])
        if elapsed < self.delay_s:
            progress = round(elapsed / self.delay_s, 2)
            return status("queued" if progress < 0.2 else "running", progress=progress)
        if p["f"]:
            return status("failed", error="échec simulé par le faux fournisseur", retryable=True)
        return status("done", progress=1.0)

    def download(self, handle: str, dest_dir: Path, *, name: str | None = None, expect: dict | None = None) -> Path:
        p = _decode(handle)
        if p["f"]:
            raise ProviderError("rien à télécharger : la génération a échoué")
        req = self.request_cls.model_validate(p["r"])
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{name or 'fake-' + hashlib.sha1(handle.encode()).hexdigest()[:12]}{self.suffix}"
        tmp = dest_dir / f".{dest.stem}.part{self.suffix}"
        try:
            self._render(req, tmp)
            self._check(tmp, req, expect or {})
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
        return dest

    def cancel(self, handle: str) -> None:
        return None                          # rien ne tourne ailleurs : rien à annuler

    def cost(self, handle: str) -> float | None:
        """Le coût réel : 0 (ou le prix catalogue si `bill`), None si on imite fal.ai."""
        if not self.report_cost:
            return None
        p = _decode(handle)
        if not self.bill or not self.model or p["f"]:
            return 0.0
        return self.model.price(self.request_cls.model_validate(p["r"]))

    # --- rendu -------------------------------------------------------------------------------------------

    suffix = ""

    def _render(self, req, out: Path) -> None:
        raise NotImplementedError

    def _check(self, path: Path, req, expect: dict) -> None:
        raise NotImplementedError

    def _size(self, aspect: str) -> tuple[int, int]:
        w, h = TARGET_SIZE[aspect]
        return max(2, int(w * self.scale) // 2 * 2), max(2, int(h * self.scale) // 2 * 2)

    def _font(self, size: int) -> ImageFont.ImageFont:
        try:
            return ImageFont.truetype(str(self.font), size)
        except OSError:
            return ImageFont.load_default(size=size)

    def _caption(self, size: tuple[int, int], title: str, subtitle: str, prompt: str) -> Image.Image:
        """Le cartouche transparent : « FAUX FOURNISSEUR », le modèle imité, le prompt."""
        w, h = size
        img = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        big, small = max(10, int(w * 0.05)), max(8, int(w * 0.04))
        per_line = max(12, int(w * 0.84 / (small * 0.55)))
        wrapped = textwrap.wrap(prompt, per_line)
        lines = wrapped[:9]
        if len(wrapped) > 9:
            lines[-1] = lines[-1][: per_line - 1] + "…"
        top = int(h * 0.56)
        pad = int(w * 0.05)
        bottom = top + pad * 2 + big + small + (small + small // 3) * (len(lines) + 1)
        draw.rounded_rectangle((pad, top, w - pad, min(h - pad, bottom)), radius=pad // 2, fill=(0, 0, 0, 175))
        x, y = pad * 2, top + pad
        draw.text((x, y), title, font=self._font(big), fill=(255, 255, 255, 255))
        y += big + small // 2
        draw.text((x, y), subtitle, font=self._font(small), fill=(255, 214, 102, 255))
        y += small * 2
        draw.multiline_text((x, y), "\n".join(lines), font=self._font(small), fill=(255, 255, 255, 255),
                            spacing=small // 3)
        return img


class FakeVideoProvider(_FakeProvider):
    kind = "video"
    request_cls = VideoRequest
    suffix = ".mp4"

    def _duration(self, req: VideoRequest) -> float:
        billed = self.model.billed_duration(req.duration_s) if self.model else None
        return billed or req.duration_s

    def _render(self, req: VideoRequest, out: Path) -> None:
        w, h = self._size(req.aspect)
        seconds = self._duration(req)
        hue = int.from_bytes(_digest(f"{req.prompt}|{req.seed}")[:2], "big") % 360
        label = self.model.id if self.model else "vidéo"
        sound = "son" if req.audio else "muet"
        with tempfile.TemporaryDirectory(prefix="loopcast-fake-") as tmp:
            caption = Path(tmp) / "caption.png"
            self._caption((w, h), "FAUX FOURNISSEUR", f"{label} · {seconds:g} s · {req.aspect} · {sound}",
                          req.prompt).save(caption)
            cmd = [find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y"]
            if req.image_path:
                square = max(8, w // 12)
                cmd += ["-loop", "1", "-framerate", str(FPS), "-i", str(req.image_path),
                        "-loop", "1", "-framerate", str(FPS), "-i", str(caption),
                        "-f", "lavfi", "-i", f"color=c=white:s={square}x{square}:r={FPS}"]
                graph = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[bg];"
                         f"[bg][1:v]overlay=0:0:format=auto[cap];"
                         f"[cap][2:v]overlay=x='mod(t*{w // 3},W-w)':y={h // 10},format=yuv420p[v]")
                audio_input = 3
            else:
                cmd += ["-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={FPS}",
                        "-loop", "1", "-framerate", str(FPS), "-i", str(caption)]
                graph = f"[0:v]hue=h={hue}[bg];[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
                audio_input = 2
            if req.audio:            # un bip de 0,15 s par seconde
                cmd += ["-f", "lavfi", "-i", "aevalsrc=0.2*sin(2*PI*880*t)*lt(mod(t\\,1)\\,0.15):s=48000:c=mono"]
            cmd += ["-filter_complex", graph, "-map", "[v]"]
            if req.audio:
                cmd += ["-map", f"{audio_input}:a", "-c:a", "aac", "-b:a", "64k"]
            cmd += ["-t", f"{seconds:g}", "-r", str(FPS), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                    "-movflags", "+faststart", "-map_metadata", "-1",
                    "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact", str(out)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            raise ProviderError(f"ffmpeg en échec (faux fournisseur) : {proc.stderr.strip()[-300:]}", retryable=True)

    def _check(self, path: Path, req: VideoRequest, expect: dict) -> None:
        check_video(path, duration_s=expect.get("duration_s") or self._duration(req),
                    aspect=expect.get("aspect") or req.aspect, min_bytes=1_000)


class FakeImageProvider(_FakeProvider):
    kind = "image"
    request_cls = ImageRequest
    suffix = ".png"

    def _render(self, req: ImageRequest, out: Path) -> None:
        w, h = self._size(req.aspect)
        d = _digest(f"{req.prompt}|{req.seed}")
        top, bottom = (d[0], d[1], d[2]), (d[3] // 2, d[4] // 2, d[5] // 2)
        if req.image_path:
            with Image.open(req.image_path) as src:
                bg = src.convert("RGB")
                scale = max(w / bg.width, h / bg.height)
                bg = bg.resize((max(w, round(bg.width * scale)), max(h, round(bg.height * scale))))
                left, upper = (bg.width - w) // 2, (bg.height - h) // 2
                img = bg.crop((left, upper, left + w, upper + h)).convert("RGBA")
        else:
            gradient = Image.linear_gradient("L").resize((w, h))
            img = Image.composite(Image.new("RGB", (w, h), bottom), Image.new("RGB", (w, h), top),
                                  gradient).convert("RGBA")
        label = self.model.id if self.model else "image"
        caption = self._caption((w, h), "FAUX FOURNISSEUR", f"{label} · {req.aspect}", req.prompt)
        Image.alpha_composite(img, caption).convert("RGB").save(out, "PNG")

    def _check(self, path: Path, req: ImageRequest, expect: dict) -> None:
        check_image(path, aspect=expect.get("aspect") or req.aspect)
