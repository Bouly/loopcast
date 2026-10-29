"""Notifications : notify() rend la main tout de suite, quoi qu'il arrive à osascript ou à ntfy.

Les alertes partent souvent d'une transaction d'écriture SQLite : un envoi lent y tenait le verrou de la base
plus longtemps que le délai d'attente des exécutants voisins (10 s).
"""

import base64
import logging
import subprocess
import threading
import time
from email.header import decode_header
from types import SimpleNamespace

import httpx
import pytest

from loopcast import notify

NTFY = {"ntfy_url": "https://ntfy.example/loopcast-test"}


def _patch(monkeypatch, run, post):
    """Un Mac (osascript) et un ntfy simulés : aucun envoi réel."""
    monkeypatch.setattr(notify, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(notify, "subprocess", SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(notify, "httpx", SimpleNamespace(post=post, HTTPError=httpx.HTTPError))


@pytest.fixture
def hanging(monkeypatch):
    """osascript et ntfy qui pendent jusqu'à ce que le test les libère ; on note ce qu'ils reçoivent."""
    release = threading.Event()
    seen: dict = {}

    def run(cmd, **kw):
        seen["osascript"] = (cmd, kw.get("timeout"))
        release.wait(5)
        return SimpleNamespace(returncode=0, stderr="")

    def post(url, **kw):
        seen["ntfy"] = (url, kw.get("timeout"), kw["headers"]["Title"], kw["content"])
        release.wait(5)
        return httpx.Response(200, request=httpx.Request("POST", url))

    _patch(monkeypatch, run, post)
    yield release, seen
    release.set()
    notify.flush(5)


def test_notify_never_blocks_the_caller(hanging):
    release, seen = hanging
    start = time.monotonic()
    notify.notify("Loopcast · diffusion", "phone-1:tiktok : post #3 à vérifier", NTFY)
    assert time.monotonic() - start < 0.5                      # osascript et ntfy pendent : l'appelant n'attend pas
    release.set()
    assert notify.flush(5)
    cmd, osascript_timeout = seen["osascript"]
    assert cmd[0] == "osascript" and 'with title "Loopcast · diffusion"' in cmd[2] and osascript_timeout <= 5
    url, ntfy_timeout, title, body = seen["ntfy"]
    assert url == NTFY["ntfy_url"] and ntfy_timeout <= 5 and body == "phone-1:tiktok : post #3 à vérifier".encode()
    # Titre non ASCII : encodé (RFC 2047), sinon httpx refuse l'en-tête et ntfy ne recevait jamais rien.
    (raw, charset), = decode_header(title)
    assert raw.decode(charset) == "Loopcast · diffusion"


def test_failures_are_logged_never_raised(monkeypatch, caplog):
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    def post(url, **kw):
        raise httpx.ConnectTimeout("délai de connexion dépassé")

    _patch(monkeypatch, run, post)
    with caplog.at_level(logging.WARNING, logger="loopcast.notify"):
        notify.notify("Loopcast · ferme", "phone-2 débranché", NTFY)
        assert notify.flush(5)
    messages = [r.getMessage() for r in caplog.records]
    assert any("osascript sans réponse après 5 s" in m for m in messages)
    assert any("ntfy en échec : délai de connexion dépassé" in m for m in messages)


def test_a_burst_never_piles_up_threads(hanging, monkeypatch, caplog):
    release, _seen = hanging
    monkeypatch.setattr(notify, "MAX_PENDING", 2)
    with caplog.at_level(logging.WARNING, logger="loopcast.notify"):
        for i in range(3):
            notify.notify("Loopcast", f"alerte {i}")
    assert any("notification non envoyée (2 envois déjà en cours)" in r.getMessage() for r in caplog.records)
    release.set()
    assert notify.flush(5)


def test_ascii_titles_are_sent_as_they_are():
    assert notify._header("Loopcast") == "Loopcast"
    encoded = base64.b64encode("Loopcast · ferme".encode()).decode()
    assert notify._header("Loopcast · ferme") == f"=?UTF-8?B?{encoded}?="
