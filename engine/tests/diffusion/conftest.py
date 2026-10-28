"""Le module diffusion en test : horloge injectable, FakePublisher, aucune notification réelle.

Ce dossier est un paquet (`__init__.py`) : ses modules s'appellent diffusion.test_…, sans collision
avec les tests des autres modules.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from loopcast import accounts, db
from loopcast.config import Config, FarmSettings, PhoneConfig
from loopcast.diffusion.publishers import FakePublisher, Publishers
from loopcast.diffusion.settings import DiffusionSettings
from loopcast.diffusion.store import iso

UTC = timezone.utc


class Clock:
    """Lundi 16/11/2026, 05:00 UTC = 06:00 à Paris (heure d'hiver)."""

    def __init__(self, now: datetime | None = None):
        self.now = now or datetime(2026, 11, 16, 5, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)

    def set(self, *args) -> None:
        self.now = datetime(*args, tzinfo=UTC)


DEFAULTS = {"timezone": "Europe/Paris", "windows": ["07:30-09:00", "12:00-14:00", "18:00-22:30"],
            "human_windows": ["09:00-21:00"], "min_gap_minutes": 180}


def phone(pid: str, lang: str = "fr", *, tiktok: dict | None = None, instagram: dict | None = None,
          apps: tuple[str, ...] = ("habitudo",), slot: int = 0) -> PhoneConfig:
    accs = {}
    if tiktok is not None:
        accs["tiktok"] = {"handle": f"@{pid}.tt", "created": "2026-10-01", "channel": "api_direct", **tiktok}
    if instagram is not None:
        accs["instagram"] = {"handle": f"@{pid}.ig", "created": "2026-10-01", "channel": "api_direct", **instagram}
    return PhoneConfig(pid, f"UDID-{pid}", lang=lang, slot=slot, apps=list(apps), accounts=accs)


def make_config(tmp_path, phones=None, settings=None, defaults=None) -> Config:
    return Config(root=tmp_path, settings=settings or {}, farm=FarmSettings(backend="fake"),
                  phones=phones if phones is not None else [phone("phone-1", tiktok={}, instagram={})],
                  defaults={**DEFAULTS, **(defaults or {})})


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    """Les notifications (osascript, ntfy) ne partent jamais pendant les tests : on les note."""
    out: list[tuple[str, str]] = []
    monkeypatch.setattr("loopcast.notify.notify", lambda title, message, settings=None: out.append((title, message)))
    return out


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def cfg(tmp_path):
    return make_config(tmp_path)


@pytest.fixture
def settings(cfg):
    return DiffusionSettings.from_config(cfg)


@pytest.fixture
def conn(cfg):
    c = db.connect(":memory:")
    accounts.sync_from_config(c, cfg)
    c.execute("INSERT INTO apps(id, name, status) VALUES ('habitudo', 'Habitudo', 'active')")
    return c


@pytest.fixture
def fake():
    return FakePublisher()


@pytest.fixture
def pubs(cfg, fake):
    return Publishers(cfg, override=fake)


@pytest.fixture
def media(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def add_content(conn, media, clock):
    """add_content("c1", fmt="chat-story", phone="phone-1") → un contenu validé avec son fichier rendu."""
    n = {"i": 0}

    def make(cid: str, *, lang: str = "fr", fmt: str = "notes-app", phone: str | None = "phone-1",
             app: str = "habitudo", status: str = "approved", parent: str | None = None, idea_phone: str | None = None,
             kind: str = "video", files: list[str] | None = None, ai_label: bool = False) -> str:
        n["i"] += 1
        if files is None:
            path = media / f"{cid}.mp4"
            path.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            files = [str(path)]
        idea_id = None
        if idea_phone is not None:
            idea_id = f"idea-{cid}"
            conn.execute(
                "INSERT INTO ideas(id, app_id, lang, format, hook, idea, status) VALUES (?,?,?,?,?,?, 'produced')",
                (idea_id, app, lang, fmt, "accroche", json.dumps({"phone_id": idea_phone})))
        approved = iso(clock() - timedelta(days=2) + timedelta(minutes=n["i"]))
        conn.execute(
            """INSERT INTO content(id, brand, app_id, format, lang, caption, hashtags, status, files, ai_label,
                                   parent_id, idea_id, account_id, kind, created_at, approved_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, app, app, fmt, lang, f"Légende {cid}", json.dumps(["habitudes", "#productivite"]), status,
             json.dumps(files), int(ai_label), parent, idea_id, f"{phone}:tiktok" if phone else None, kind,
             approved, approved))
        return cid

    return make


@pytest.fixture
def add_post(conn):
    """add_post("c1", "phone-1:tiktok", at, status="posted", views=120) : un post déjà en base."""

    def make(content_id: str, account_id: str, at: datetime, *, status: str = "posted", views: int | None = None,
             external_id: str | None = None) -> int:
        platform = account_id.split(":")[1]
        cur = conn.execute(
            """INSERT INTO posts(content_id, account_id, platform, app_id, scheduled_at, planned_at, status, attempts,
                                 posted_at, views, external_id, log)
               VALUES (?,?,?,?,?,?,?,1,?,?,?, '[]')""",
            (content_id, account_id, platform, "habitudo", iso(at), iso(at), status,
             iso(at) if status == "posted" else None, views, external_id))
        return cur.lastrowid

    return make
