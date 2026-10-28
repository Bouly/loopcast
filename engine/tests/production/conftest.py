"""Outils des tests du module production : vrais petits fichiers (ffmpeg, Pillow), faux moteur de rendu,
et un « pipeline » de test qui fait tourner la file de tâches avec une horloge injectable."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from loopcast import db, jobs
from loopcast.config import Config, FarmSettings
from loopcast.production import options, renderer, store
from loopcast.production import tasks  # noqa: F401  (tâches content.* et formats à plans)
from loopcast.schemas import Idea, Localized, ProductBrief, Shot

FFMPEG = options.ffmpeg_bin()
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and options.ffprobe_bin()), reason="ffmpeg/ffprobe absents")


# --- Vrais petits fichiers --------------------------------------------------------------------------------

def make_video(path: Path, seconds: float = 7.0, size: tuple[int, int] = (1080, 1920), *, source: str = "motion",
               audio: str | None = None, black: tuple[float, float] | None = None, fps: int = 10) -> Path:
    """Vidéo H.264 réelle. source : motion (mire animée) | still (image fixe) | black.
    audio : None | tone | silent | speech (voix simulée de 0,7 à 4,6 s, silence autour)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    video = {"motion": f"testsrc2=s={w}x{h}:r={fps}", "still": f"color=c=0x3366AA:s={w}x{h}:r={fps}",
             "black": f"color=c=black:s={w}x{h}:r={fps}"}[source]
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", video]
    if audio:
        sound = {"tone": f"sine=frequency=220:sample_rate=48000:duration={seconds}",
                 "silent": f"anullsrc=r=48000:cl=mono:d={seconds}",
                 "speech": f"aevalsrc='if(between(t\\,0.7\\,4.6)\\,0.5*sin(2*PI*190*t)\\,0)':s=48000:d={seconds}"}[audio]
        cmd += ["-f", "lavfi", "-i", sound]
    filters = "format=yuv420p"
    if black:
        filters = f"drawbox=c=black:t=fill:enable='between(t\\,{black[0]}\\,{black[1]})'," + filters
    cmd += ["-t", str(seconds), "-vf", filters, "-c:v", "libx264", "-preset", "ultrafast"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    subprocess.run([*cmd, str(path)], check=True, capture_output=True)
    return path


def make_png(path: Path, size: tuple[int, int] = (1080, 1920), *, blank: bool = False, label: str = "Loopcast") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, (91, 91, 247))
    if not blank:
        d = ImageDraw.Draw(img)
        d.rectangle((size[0] // 8, size[1] // 3, size[0] * 7 // 8, size[1] // 2), fill=(255, 255, 255))
        d.text((size[0] // 4, size[1] // 3 + 20), label, fill=(10, 10, 10))
    img.save(path)
    return path


class FakeRenderer:
    """Fabrique de vrais fichiers à la place de Remotion : la durée suit les plans (story) ou vaut 8 s."""

    def __init__(self, *, fail: str | None = None, seconds: float | None = None,
                 size: tuple[int, int] = (1080, 1920), **video_kw):
        self.fail, self.seconds, self.size, self.video_kw = fail, seconds, size, video_kw
        self.calls: list[renderer.RenderJob] = []

    def render(self, render_jobs: list[renderer.RenderJob]) -> dict[str, renderer.RenderResult]:
        out = {}
        for j in render_jobs:
            self.calls.append(j)
            if self.fail:
                out[j.id] = renderer.RenderResult(j.id, False, error=self.fail)
                continue
            if j.stills:
                files = [str(make_png(j.out_dir / f"{i + 1:02d}.png", self.size, label=f"slide {i}"))
                         for i in range(j.stills)]
            else:
                seconds = self.seconds or (sum(s["duration"] for s in j.props["shots"])
                                           if j.composition == "story" else 8.0)
                files = [str(make_video(j.out, seconds, self.size, **self.video_kw))]
            out[j.id] = renderer.RenderResult(j.id, True, files, seconds=0.1)
        return out


# --- Le pipeline de test ---------------------------------------------------------------------------------

class Pipeline:
    def __init__(self, root: Path, clock):
        self.root = root
        self.clock = clock
        (root / "render" / "public").mkdir(parents=True, exist_ok=True)
        self.config = Config(root=root, settings={}, farm=FarmSettings(backend="fake"))
        self.conn = db.connect(self.config.db_path)
        self.app_id = "habitudo"

    def now(self) -> str:
        return jobs.iso(self.clock())

    def seed_app(self, brand: dict | None = None, cta: str = "Lance ta série ce soir") -> None:
        brand = brand if brand is not None else {"accent": "#5B5BF7", "handle": "@habitudo",
                                                 "storeLine": {"fr": "Gratuit sur l'App Store", "en": "Free on the App Store"}}
        self.conn.execute("INSERT INTO apps(id, name, brand, status, created_at) VALUES (?,?,?,?,?)",
                          (self.app_id, "Habitudo", json.dumps(brand), "active", self.now()))
        brief = ProductBrief(app_name="Habitudo", one_liner=Localized(fr="3 habitudes", en="3 habits"),
                             category="habitudes", problem="p", solution="s", value_props=["v"], features=[],
                             personas=[], differentiators=[], competitors=[], objections=[], proof_points=[],
                             pricing="gratuit", tone="direct", do_not_say=[], cta=Localized(fr=cta, en="Start tonight"),
                             keywords=Localized(fr="habitudes", en="habits"), unknowns=[], confidence=0.8)
        self.conn.execute("INSERT INTO app_briefs(app_id, version, brief, created_at, approved_at) VALUES (?,?,?,?,?)",
                          (self.app_id, 1, brief.model_dump_json(), self.now(), self.now()))

    def asset(self, kind: str, path: Path, analysis: dict | None = None, **meta) -> int:
        rel = f"assets/{path.name}"
        dest = self.config.data_dir / "apps" / self.app_id / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path != dest:
            dest.write_bytes(path.read_bytes())
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        mime = "video/mp4" if path.suffix == ".mp4" else "image/png"
        cur = self.conn.execute(
            """INSERT INTO app_assets(app_id, kind, path, filename, mime, bytes, width, height, duration_s, sha256,
                                      analysis, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (self.app_id, kind, rel, path.name, mime, dest.stat().st_size, meta.get("width"), meta.get("height"),
             meta.get("duration_s"), sha, json.dumps(analysis) if analysis else None, self.now()))
        return cur.lastrowid

    def screenshot(self, name: str = "today.png", **kw) -> int:
        return self.asset("screenshot", make_png(self.root / "src" / name, (1290, 2796), label=name), width=1290,
                          height=2796, **kw)

    def recording(self, seconds: float = 12.0) -> int:
        path = make_video(self.root / "src" / "demo.mp4", seconds, (888, 1920))
        return self.asset("demo_video", path, width=888, height=1920, duration_s=seconds)

    def idea(self, fmt: str, *, props: dict | None = None, shots: list[Shot] | None = None, lang: str = "fr",
             phone: str = "phone-1", hook: str = "Arrête de compter sur ta motivation", ai_label: bool = False,
             idea_id: str | None = None, hashtags: list[str] | None = None, props_json: str | None = None) -> str:
        idea = Idea(title="Idée de test", lang=lang, phone_id=phone, pillar="routines", format=fmt, hook=hook,
                    angle="", why_it_works="", shots=shots or [],
                    props_json=props_json if props_json is not None else (json.dumps(props) if props else ""),
                    caption="Ta routine en 3 habitudes",
                    hashtags=hashtags if hashtags is not None else ["habitudes", "#Routine", "routine"], ai_label=ai_label)
        idea_id = idea_id or f"{self.app_id}-{lang}-{fmt}-{self.conn.execute('SELECT COUNT(*) FROM ideas').fetchone()[0]:04d}"
        self.conn.execute("""INSERT INTO ideas(id, app_id, lang, format, pillar, hook, idea, status, created_at)
                             VALUES (?,?,?,?,?,?,?,?,?)""",
                          (idea_id, self.app_id, lang, fmt, "routines", hook, idea.model_dump_json(), "approved",
                           self.now()))
        return idea_id

    def produce(self, idea_id: str) -> int:
        return jobs.enqueue(self.conn, "content.produce", {"idea_id": idea_id}, key=f"content.produce:{idea_id}",
                            app_id=self.app_id, clock=self.clock)

    def run(self, renderer_=None, max_steps: int = 60) -> list[jobs.Job]:
        """Exécute les tâches content.* prêtes ; avance l'horloge jusqu'à la prochaine si besoin.
        Les tâches video.generate (module providers) ne sont pas exécutées : les tests les terminent à la main."""
        services = {"renderer": renderer_} if renderer_ is not None else {}
        done: list[jobs.Job] = []
        for _ in range(max_steps):
            job = jobs.run_one(self.conn, self.config, "test", clock=self.clock, services=services,
                               kinds=["content."])
            if job is not None:
                done.append(job)
                continue
            nxt = self.conn.execute("SELECT MIN(run_after) FROM jobs WHERE status='queued' AND kind LIKE 'content.%'"
                                    ).fetchone()[0]
            if nxt is None:
                break
            when = datetime.fromisoformat(nxt)
            if when <= self.clock():
                break                       # prête mais refusée (limite) : rien de plus à faire ici
            self.clock.now = when
        return done

    def content(self, content_id: str):
        return store.get_content(self.conn, content_id)

    def idea_row(self, idea_id: str):
        return store.get_idea(self.conn, idea_id)

    def jobs(self, kind: str) -> list:
        return self.conn.execute("SELECT * FROM jobs WHERE kind=? ORDER BY id", (kind,)).fetchall()

    def finish_generation(self, job_id: int, path: Path, cost: float = 0.5) -> None:
        """Ce que fait le module providers : la tâche video.generate se termine avec {path, cost_usd, model}."""
        self.conn.execute("UPDATE jobs SET status='done', result=?, updated_at=?, finished_at=? WHERE id=?",
                          (json.dumps({"path": str(path), "cost_usd": cost, "model": "fake-veo"}), self.now(),
                           self.now(), job_id))

    def kill_generation(self, job_id: int, error: str) -> None:
        self.conn.execute("UPDATE jobs SET status='dead', last_error=?, updated_at=? WHERE id=?",
                          (error, self.now(), job_id))

    def advance(self, **kw) -> None:
        self.clock.now += timedelta(**kw)


@pytest.fixture
def pipe(tmp_path, clock) -> Pipeline:
    p = Pipeline(tmp_path / "root", clock)
    p.seed_app()
    return p


def story_shots(asset_today: int, asset_stats: int) -> list[Shot]:
    """Une idée ai-hook-demo valide : accroche IA puis deux vraies captures."""
    return [
        Shot(kind="ai_video", duration_s=3.0, visual="une étudiante sur son lit le soir",
             prompt="A young woman on her bed at night looking at her phone, warm lamp light, cinematic",
             asset_id=None, on_screen_text="POV : jour 3 de ta **nouvelle routine**", voiceover=""),
        Shot(kind="app_screenshot", duration_s=3.0, visual="liste du jour", prompt="", asset_id=asset_today,
             on_screen_text="Choisis 3 habitudes, pas 15", voiceover=""),
        Shot(kind="app_screenshot", duration_s=3.0, visual="série", prompt="", asset_id=asset_stats,
             on_screen_text="Coche-les chaque soir", voiceover="Un geste le soir, c'est tout."),
    ]
