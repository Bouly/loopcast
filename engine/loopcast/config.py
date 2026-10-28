"""Chargement de config/*.yaml et des chemins du projet."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("LOOPCAST_ROOT", Path(__file__).resolve().parents[2]))


def _load_yaml(name: str) -> dict[str, Any]:
    """Lit config/<name>.yaml, ou à défaut config/<name>.example.yaml."""
    for candidate in (ROOT / "config" / f"{name}.yaml", ROOT / "config" / f"{name}.example.yaml"):
        if candidate.exists():
            return yaml.safe_load(candidate.read_text()) or {}
    return {}


@dataclass
class FarmSettings:
    backend: str = "pymobiledevice3"        # pymobiledevice3 | fake
    pymobiledevice3: str = "pymobiledevice3"
    appium_url: str = "http://127.0.0.1:4723"
    poll_seconds: int = 15
    thumb_seconds: int = 5                  # fréquence des vignettes d'écran du dashboard
    battery_low: int = 25
    offline_alert_minutes: int = 10
    wda_base_port: int = 8100
    mjpeg_base_port: int = 9100
    xcode_org_id: str | None = None
    wda_bundle_id: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FarmSettings:
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class PhoneConfig:
    id: str
    udid: str | None
    owner: str = ""
    lang: str = "fr"
    slot: int = 0                           # index dans devices.yaml, sert à attribuer les ports


@dataclass
class Config:
    root: Path
    settings: dict[str, Any]
    farm: FarmSettings
    phones: list[PhoneConfig] = field(default_factory=list)

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "loopcast.db"

    def phone_by_udid(self, udid: str) -> PhoneConfig | None:
        return next((p for p in self.phones if p.udid == udid), None)

    def phone_by_id(self, phone_id: str) -> PhoneConfig | None:
        return next((p for p in self.phones if p.id == phone_id), None)


def load(root: Path | None = None) -> Config:
    global ROOT
    if root is not None:
        ROOT = Path(root)
    settings = _load_yaml("settings")
    devices = _load_yaml("devices")
    phones = [
        PhoneConfig(id=d["id"], udid=d.get("udid"), owner=d.get("owner") or "", lang=d.get("lang", "fr"), slot=i)
        for i, d in enumerate(devices.get("devices") or [])
    ]
    return Config(root=ROOT, settings=settings, farm=FarmSettings.from_dict(settings.get("farm") or {}), phones=phones)
