"""Temps réel pour le dashboard : bus d'événements (SSE) et cache des captures d'écran.

Le front ne déclenche jamais de commande lente : les captures sont prises en tâche de fond,
en parallèle pour tous les iPhones, et servies depuis la mémoire. Le front est prévenu par SSE
quand une capture change, au lieu de recharger en boucle.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from loopcast.farm.backend import BackendError, DeviceBackend
from loopcast.farm.control import ControlError, PhoneController

log = logging.getLogger(__name__)


class EventBus:
    """Diffusion vers les clients SSE. `publish` peut être appelé depuis n'importe quel thread."""

    def __init__(self, max_queue: int = 200):
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max = max_queue

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(self._max)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, kind: str, data: dict) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        message = f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        self._loop.call_soon_threadsafe(self._fanout, message)

    def _fanout(self, message: str) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:   # client trop lent : on le laisse rattraper au prochain état complet
                pass


@dataclass
class Screen:
    png: bytes
    etag: str


class ScreenCache:
    def __init__(
        self,
        conn: sqlite3.Connection,
        backend: DeviceBackend,
        controller: PhoneController,
        bus: EventBus | None = None,
        workers: int = 5,
    ):
        self.conn = conn
        self.backend = backend
        self.controller = controller
        self.bus = bus
        self._screens: dict[str, Screen] = {}
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="capture")

    def get(self, udid: str) -> Screen | None:
        return self._screens.get(udid)

    def capture(self, udid: str, has_session: bool) -> Screen | None:
        try:
            png = self.controller.screenshot(udid) if has_session else self.backend.screenshot(udid)
        except (BackendError, ControlError) as e:
            log.debug("%s : capture impossible : %s", udid, e)
            return None
        etag = hashlib.blake2b(png, digest_size=8).hexdigest()
        prev = self._screens.get(udid)
        self._screens[udid] = Screen(png, etag)
        if self.bus and (prev is None or prev.etag != etag):
            self.bus.publish("screen", {"udid": udid, "etag": etag})
        return self._screens[udid]

    def capture_all(self) -> int:
        rows = self.conn.execute(
            "SELECT udid, session_id FROM phones WHERE status != 'offline'").fetchall()
        # Un iPhone piloté a déjà son flux vidéo en direct : inutile de le capturer en plus.
        jobs = [self._pool.submit(self.capture, r["udid"], False) for r in rows if not r["session_id"]]
        return sum(1 for j in jobs if j.result() is not None)

    def run_forever(self, stop: threading.Event, every_seconds: float) -> None:
        while not stop.is_set():
            try:
                self.capture_all()
            except Exception:
                log.exception("tour de captures en échec")
            stop.wait(every_seconds)
