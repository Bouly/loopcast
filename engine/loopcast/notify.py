"""Notifications : centre de notifications macOS + push sur les iPhones de l'équipe (ntfy)."""

from __future__ import annotations

import logging
import subprocess
import sys

import httpx

log = logging.getLogger(__name__)

# Événements qui méritent de déranger quelqu'un ; les autres restent dans le journal du dashboard.
ALERT_KINDS = ("problem_", "phone_new", "farm_error")


def is_alert(kind: str) -> bool:
    return kind.startswith(ALERT_KINDS)


def notify(title: str, message: str, settings: dict | None = None) -> None:
    settings = settings or {}
    if sys.platform == "darwin":
        script = f"display notification {_q(message)} with title {_q(title)}"
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    topic_url = settings.get("ntfy_url")   # ex. https://ntfy.sh/loopcast-<secret> ou un ntfy auto-hébergé
    if topic_url:
        try:
            httpx.post(topic_url, content=message.encode(), headers={"Title": title}, timeout=10)
        except httpx.HTTPError as e:
            log.warning("ntfy en échec : %s", e)


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
