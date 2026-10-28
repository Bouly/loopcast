"""Appel du moteur Remotion : manifest → `node render/render.mjs manifest.json` → fichiers.

Contrat (REPRISE §4) : stdout = une ligne JSON par job {"id", "ok", "files" | "error"}, journal sur stderr.
Le rendu est lourd (Chrome headless + encodage) : un seul à la fois sur la machine (verrou de fichier,
en plus de la limite de la file `jobs.limits`), avec un délai maximal au-delà duquel le processus est tué.

Les tâches reçoivent le moteur par `services["renderer"]` (les tests y mettent un faux) ou, à défaut,
le vrai (`NodeRenderer.from_config`).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol

from loopcast.production import options

log = logging.getLogger(__name__)


@dataclass
class RenderJob:
    id: str
    composition: str
    props: dict
    out: Path | None = None          # vidéo : fichier .mp4
    out_dir: Path | None = None      # images fixes : dossier
    stills: int | None = None

    def manifest(self) -> dict:
        job: dict = {"id": self.id, "composition": self.composition, "props": self.props}
        if self.stills:
            job.update(outDir=str(self.out_dir), stills=self.stills)
        else:
            job["out"] = str(self.out)
        return job


@dataclass
class RenderResult:
    id: str
    ok: bool
    files: list[str] = field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0


class Renderer(Protocol):
    def render(self, jobs: list[RenderJob]) -> dict[str, RenderResult]: ...


class RenderUnavailable(RuntimeError):
    """Node ou render.mjs absents : inutile de réessayer tant que la machine n'est pas installée."""


class NodeRenderer:
    """Le vrai moteur. `cmd` = la commande sans le manifest (les tests passent un faux script)."""

    def __init__(self, cmd: list[str], cwd: Path, timeout_s: float = 900, env: dict[str, str] | None = None):
        self.cmd = cmd
        self.cwd = cwd
        self.timeout_s = timeout_s
        self.env = env or {}

    @classmethod
    def from_config(cls, config: Any) -> "NodeRenderer":
        settings = config.settings or {}
        render_dir = Path(config.root) / "render"
        script = render_dir / "render.mjs"
        node = options.node_bin(settings)
        if not node:
            raise RenderUnavailable("Node introuvable : l'installer (voir docs/ferme-iphone.md) ou régler render.node")
        if not script.exists():
            raise RenderUnavailable(f"moteur de rendu absent : {script}")
        if not (render_dir / "node_modules").exists():
            raise RenderUnavailable("dépendances du rendu absentes : cd render && npm ci")
        env = {}
        browser = options.remotion_browser(settings)
        if browser:
            env["REMOTION_BROWSER"] = str(browser)
        return cls([node, str(script)], render_dir, options.render_timeout_s(settings), env)

    def render(self, jobs: list[RenderJob]) -> dict[str, RenderResult]:
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="loopcast-render-") as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps({"jobs": [j.manifest() for j in jobs]}, ensure_ascii=False))
            proc = subprocess.Popen([*self.cmd, str(manifest)], cwd=self.cwd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, env={**os.environ, **self.env},
                                    start_new_session=True)       # groupe à part : on tue aussi Chrome
            try:
                stdout, stderr = proc.communicate(timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                _kill(proc)
                stdout, stderr = proc.communicate()
                return {j.id: RenderResult(j.id, False, error=f"rendu interrompu après {self.timeout_s:.0f} s "
                                                                f"(render.timeout_s)") for j in jobs}
        elapsed = time.monotonic() - started
        results = parse_output(stdout)
        tail = " / ".join(line for line in stderr.strip().splitlines()[-4:] if line.strip())
        for j in jobs:
            if j.id not in results:
                results[j.id] = RenderResult(j.id, False, error=f"aucun résultat du moteur (code {proc.returncode})"
                                                                 + (f" : {tail[-600:]}" if tail else ""))
            results[j.id].seconds = round(elapsed, 1)
        if proc.returncode not in (0, None):
            log.warning("render.mjs : code %s ; %s", proc.returncode, tail[-600:])
        return results


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def parse_output(stdout: str) -> dict[str, RenderResult]:
    """Les lignes JSON de render.mjs (les autres lignes éventuelles sont ignorées)."""
    out: dict[str, RenderResult] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if "id" not in d:
            continue
        out[str(d["id"])] = RenderResult(str(d["id"]), bool(d.get("ok")), [str(f) for f in d.get("files") or []],
                                         d.get("error"))
    return out


def get(services: dict, config: Any) -> Renderer:
    return services.get("renderer") or NodeRenderer.from_config(config)


# --- Un seul rendu à la fois sur la machine -------------------------------------------------------------

class Busy(RuntimeError):
    pass


@contextmanager
def exclusive(lock_path: Path) -> Iterator[None]:
    """Verrou non bloquant, partagé entre threads et processus (serve + worker) : lève Busy s'il est pris."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise Busy("un autre rendu est en cours") from e
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
