"""Chargement de config/*.yaml et des chemins du projet.

Mode démo (`--demo`) : une configuration à part, qui ne touche jamais aux vraies données. Base
`data/demo.db` (au lieu de `data/loopcast.db`), fichiers sous `data/demo/` (assets des apps, plans générés,
rendus dans `data/demo/out/`), iPhones simulés, Claude et générateurs vidéo en démo, pas de push ntfy.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

ROOT = Path(os.environ.get("LOOPCAST_ROOT", Path(__file__).resolve().parents[2]))

# Posé par la CLI (`--demo`) le temps d'une commande : chaque load() rend alors une configuration de démo,
# y compris dans les commandes des modules qui chargent la configuration elles-mêmes.
_DEMO = False


@contextmanager
def demo_mode(enabled: bool = True) -> Iterator[None]:
    """Le temps du bloc, load() rend une configuration de démo (si `enabled`)."""
    global _DEMO
    previous, _DEMO = _DEMO, bool(enabled) or _DEMO
    try:
        yield
    finally:
        _DEMO = previous


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
    apps: list[str] = field(default_factory=list)          # apps promues par ce téléphone (`brands`)
    accounts: dict[str, dict] = field(default_factory=dict)  # {tiktok: {handle, created, channel}, …}
    options: dict[str, Any] = field(default_factory=dict)    # réglages propres au téléphone (fuseau, créneaux…)


@dataclass
class Config:
    root: Path
    settings: dict[str, Any]
    farm: FarmSettings
    phones: list[PhoneConfig] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)  # `defaults` de devices.yaml (fuseau, créneaux…)
    demo: bool = False                      # mode démo : base et fichiers à part, rien de réel

    @property
    def data_dir(self) -> Path:
        """data/ ; en démo, data/demo/ (les assets et plans de la démo ne rejoignent jamais les vrais)."""
        return self.root / "data" / "demo" if self.demo else self.root / "data"

    @property
    def db_path(self) -> Path:
        return self.root / "data" / ("demo.db" if self.demo else "loopcast.db")

    @property
    def out_dir(self) -> Path:
        """Les rendus : out/ ; en démo, data/demo/out/ (mêmes ids de contenu possibles que la vraie base)."""
        return self.data_dir / "out" if self.demo else self.root / "out"

    def phone_by_udid(self, udid: str) -> PhoneConfig | None:
        return next((p for p in self.phones if p.udid == udid), None)

    def phone_by_id(self, phone_id: str) -> PhoneConfig | None:
        return next((p for p in self.phones if p.id == phone_id), None)


def load(root: Path | None = None, *, demo: bool | None = None) -> Config:
    """`demo` : None = celui de la commande en cours (demo_mode), sinon forcé."""
    global ROOT
    if root is not None:
        ROOT = Path(root)
    settings = _load_yaml("settings")
    devices = _load_yaml("devices")
    phones = [
        PhoneConfig(id=d["id"], udid=d.get("udid"), owner=d.get("owner") or "", lang=d.get("lang", "fr"), slot=i,
                    apps=list(d.get("apps") or d.get("brands") or []), accounts=dict(d.get("accounts") or {}),
                    options={k: v for k, v in d.items()
                             if k not in ("id", "udid", "owner", "lang", "apps", "brands", "accounts", "model")})
        for i, d in enumerate(devices.get("devices") or [])
    ]
    config = Config(root=ROOT, settings=settings, farm=FarmSettings.from_dict(settings.get("farm") or {}),
                    phones=phones, defaults=dict(devices.get("defaults") or {}), demo=_DEMO if demo is None else demo)
    if config.demo:
        as_demo(config)
    return config


def as_demo(config: Config) -> Config:
    """Rend `config` inoffensive : base et fichiers de démo, iPhones simulés, Claude et générateurs en démo
    (quelle que soit la façon dont les services sont construits ensuite), pas de push ntfy vers l'équipe."""
    config.demo = True
    config.farm.backend = "fake"
    for section in ("llm", "providers"):
        config.settings[section] = {**(config.settings.get(section) or {}), "demo": True}
    config.settings["notify"] = {k: v for k, v in (config.settings.get("notify") or {}).items() if k != "ntfy_url"}
    return config
