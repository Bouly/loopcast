"""Notifications : centre de notifications macOS + push sur les iPhones de l'équipe (ntfy).

notify() ne bloque jamais l'appelant : l'envoi part dans un thread de fond. Les alertes partent souvent
depuis une transaction d'écriture SQLite (BEGIN IMMEDIATE) ; un osascript bloqué ou un ntfy (ou un DNS) qui
traîne y tenait le verrou de la base au-delà de son délai d'attente (10 s), et les exécutants voisins
échouaient en écrivant l'état de leurs tâches. Chaque envoi a un délai court ; un échec est journalisé.
"""

from __future__ import annotations

import atexit
import base64
import logging
import subprocess
import sys
import threading
import time

import httpx

log = logging.getLogger(__name__)

# Événements qui méritent de déranger quelqu'un ; les autres restent dans le journal du dashboard.
ALERT_KINDS = ("problem_", "phone_new", "farm_error")

OSASCRIPT_TIMEOUT_S = 5.0
NTFY_TIMEOUT_S = 5.0
MAX_PENDING = 20                 # envois en cours au plus ; au-delà (rafale, réseau coupé), on journalise et on passe

_lock = threading.Lock()
_pending: set[threading.Thread] = set()


def is_alert(kind: str) -> bool:
    return kind.startswith(ALERT_KINDS)


def notify(title: str, message: str, settings: dict | None = None) -> None:
    """Prévient l'équipe en arrière-plan et rend la main tout de suite."""
    settings = dict(settings or {})
    with _lock:
        _pending.difference_update([t for t in _pending if not t.is_alive()])
        if len(_pending) >= MAX_PENDING:
            log.warning("notification non envoyée (%d envois déjà en cours) : %s — %s", len(_pending), title, message)
            return
        thread = threading.Thread(target=_send, args=(title, message, settings), name="notify", daemon=True)
        _pending.add(thread)
        thread.start()


def flush(timeout: float = OSASCRIPT_TIMEOUT_S + NTFY_TIMEOUT_S) -> bool:
    """Attend la fin des envois en cours, `timeout` secondes au plus. Appelé à la sortie du processus : une
    commande courte (CLI) ne coupe pas sa propre notification. Renvoie True si tout est parti."""
    deadline = time.monotonic() + timeout
    with _lock:
        threads = list(_pending)
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return not any(t.is_alive() for t in threads)


atexit.register(flush)


def _send(title: str, message: str, settings: dict) -> None:
    try:
        if sys.platform == "darwin":
            _macos(title, message)
        topic_url = settings.get("ntfy_url")   # ex. https://ntfy.sh/loopcast-<secret> ou un ntfy auto-hébergé
        if topic_url:
            _ntfy(topic_url, title, message)
    except Exception:  # noqa: BLE001 : une notification ratée ne doit rien casser, mais elle se voit dans le journal
        log.exception("notification impossible : %s", title)


def _macos(title: str, message: str) -> None:
    script = f"display notification {_q(message)} with title {_q(title)}"
    try:
        proc = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True,
                              timeout=OSASCRIPT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log.warning("notification macOS : osascript sans réponse après %.0f s", OSASCRIPT_TIMEOUT_S)
        return
    except OSError as e:
        log.warning("notification macOS impossible : %s", e)
        return
    if proc.returncode != 0:
        log.warning("notification macOS en échec (osascript, code %s) : %s", proc.returncode,
                    (proc.stderr or "").strip()[:300])


def _ntfy(url: str, title: str, message: str) -> None:
    try:
        r = httpx.post(url, content=message.encode(), headers={"Title": _header(title)}, timeout=NTFY_TIMEOUT_S)
    except httpx.HTTPError as e:
        log.warning("ntfy en échec : %s", e)
        return
    if r.is_error:
        log.warning("ntfy en échec : HTTP %s %s", r.status_code, r.text[:200])


def _header(value: str) -> str:
    """Un en-tête HTTP ne passe qu'en ASCII (httpx refuse « Loopcast · ferme ») : sinon encodé selon la RFC 2047,
    que ntfy décode (https://docs.ntfy.sh/publish/)."""
    if value.isascii():
        return value
    return "=?UTF-8?B?" + base64.b64encode(value.encode()).decode() + "?="


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
