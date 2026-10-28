"""Accès bas niveau aux iPhones branchés (USB ou Wi-Fi appairé).

Le backend réel appelle la CLI `pymobiledevice3` sur le Mac de la ferme : il faut l'USB,
donc il ne tourne pas dans Docker. Le FakeBackend sert aux tests et au mode démo.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class DeviceInfo:
    udid: str
    name: str = ""
    model: str = ""            # ProductType, ex. iPhone16,1
    ios: str = ""
    connection: str = "USB"    # USB | Network


@dataclass
class DeviceHealth:
    trusted: bool = True       # « Faire confiance à cet ordinateur » accepté
    developer_mode: bool | None = None
    battery: int | None = None
    charging: bool | None = None
    errors: list[str] = field(default_factory=list)


# Code interne Apple (ProductType) → nom commercial. Les numéros sont décalés : iPhone15,3 = iPhone 14 Pro Max.
MODEL_NAMES = {
    "iPhone13,1": "iPhone 12 mini", "iPhone13,2": "iPhone 12",
    "iPhone13,3": "iPhone 12 Pro", "iPhone13,4": "iPhone 12 Pro Max",
    "iPhone14,4": "iPhone 13 mini", "iPhone14,5": "iPhone 13",
    "iPhone14,2": "iPhone 13 Pro", "iPhone14,3": "iPhone 13 Pro Max",
    "iPhone14,6": "iPhone SE (3e gén.)",
    "iPhone14,7": "iPhone 14", "iPhone14,8": "iPhone 14 Plus",
    "iPhone15,2": "iPhone 14 Pro", "iPhone15,3": "iPhone 14 Pro Max",
    "iPhone15,4": "iPhone 15", "iPhone15,5": "iPhone 15 Plus",
    "iPhone16,1": "iPhone 15 Pro", "iPhone16,2": "iPhone 15 Pro Max",
    "iPhone17,3": "iPhone 16", "iPhone17,4": "iPhone 16 Plus",
    "iPhone17,1": "iPhone 16 Pro", "iPhone17,2": "iPhone 16 Pro Max",
    "iPhone17,5": "iPhone 16e",
}


def model_name(product_type: str) -> str:
    return MODEL_NAMES.get(product_type, product_type)


class DeviceBackend(Protocol):
    def list_devices(self) -> list[DeviceInfo]: ...
    def health(self, udid: str) -> DeviceHealth: ...
    def screenshot(self, udid: str) -> bytes: ...


class BackendError(RuntimeError):
    pass


def _find_exe(exe: str) -> str:
    """Le PATH d'un service launchd ou d'un terminal n'a pas toujours ~/.local/bin :
    on cherche aussi à côté de l'interpréteur (extra [ios] installé dans le venv)."""
    import shutil
    import sys
    from pathlib import Path

    if "/" in exe or shutil.which(exe):
        return exe
    for candidate in (Path(sys.executable).parent / exe, Path.home() / ".local" / "bin" / exe):
        if candidate.exists():
            return str(candidate)
    return exe


class PyMobileDeviceBackend:
    """Appelle `pymobiledevice3 … --udid` et lit le JSON.

    Les noms de champs sont lus de façon tolérante : la sortie de la CLI a changé entre versions.
    À valider sur le premier iPhone branché (`pymobiledevice3 usbmux list`).
    """

    def __init__(self, exe: str = "pymobiledevice3", timeout: float = 20):
        self.exe = _find_exe(exe)
        self.timeout = timeout

    def _run(self, *args: str) -> str:
        try:
            proc = subprocess.run(
                [self.exe, *args], capture_output=True, text=True, timeout=self.timeout, check=False
            )
        except FileNotFoundError as e:
            raise BackendError(f"{self.exe} introuvable : installer l'extra [ios] sur le Mac de la ferme") from e
        except subprocess.TimeoutExpired as e:
            raise BackendError(f"{' '.join(args)} : délai dépassé") from e
        if proc.returncode != 0:
            raise BackendError((proc.stderr or proc.stdout).strip()[-400:] or f"code {proc.returncode}")
        return proc.stdout

    def _json(self, *args: str):
        out = self._run(*args)
        try:
            return json.loads(out)
        except json.JSONDecodeError as e:
            raise BackendError(f"{' '.join(args)} : sortie non JSON") from e

    def list_devices(self) -> list[DeviceInfo]:
        devices: dict[str, DeviceInfo] = {}
        for raw in self._json("usbmux", "list"):
            udid = raw.get("UniqueDeviceID") or raw.get("Identifier") or raw.get("SerialNumber")
            if not udid:
                continue
            info = DeviceInfo(
                udid=udid,
                name=raw.get("DeviceName", ""),
                model=raw.get("ProductType", ""),
                ios=raw.get("ProductVersion", ""),
                connection=raw.get("ConnectionType", "USB"),
            )
            # Un iPhone branché ET appairé en Wi-Fi apparaît deux fois : on garde l'USB.
            if udid not in devices or info.connection == "USB":
                devices[udid] = info
        return list(devices.values())

    def health(self, udid: str) -> DeviceHealth:
        h = DeviceHealth()
        try:
            self._json("lockdown", "info", "--udid", udid)
        except BackendError as e:
            h.trusted = False
            h.errors.append(str(e))
            return h
        try:
            out = self._run("amfi", "developer-mode-status", "--udid", udid).strip().lower()
            h.developer_mode = out.startswith("true")
        except BackendError as e:
            h.errors.append(f"mode développeur : {e}")
        try:
            battery = self._json("diagnostics", "battery", "single", "--udid", udid)
            level = battery.get("CurrentCapacity")
            h.battery = int(level) if level is not None else None
            charging = battery.get("IsCharging")
            h.charging = bool(charging) if charging is not None else None
        except (BackendError, AttributeError, ValueError) as e:
            h.errors.append(f"batterie : {e}")
        return h

    def screenshot(self, udid: str) -> bytes:
        # iOS 17+ : nécessite `sudo pymobiledevice3 remote tunneld` lancé en tâche de fond.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "screen.png"
            self._run("developer", "dvt", "screenshot", "--tunnel", udid, str(out))
            return out.read_bytes()


def solid_png(width: int, height: int, rgb: tuple[int, int, int] = (40, 40, 48)) -> bytes:
    """PNG uni, pour le mode démo (sans dépendance d'image)."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    row = b"\x00" + bytes(rgb) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


_FAKE_PNG = solid_png(393, 852)   # proportions d'un iPhone 15 (en points)


class FakeBackend:
    """Téléphones simulés : on modifie `devices` / `healths` pendant les tests."""

    def __init__(self, devices: list[DeviceInfo] | None = None):
        self.devices: list[DeviceInfo] = list(devices or [])
        self.healths: dict[str, DeviceHealth] = {}

    def list_devices(self) -> list[DeviceInfo]:
        return list(self.devices)

    def health(self, udid: str) -> DeviceHealth:
        return self.healths.get(udid, DeviceHealth(developer_mode=True, battery=80, charging=True))

    def screenshot(self, udid: str) -> bytes:
        return _FAKE_PNG


def make_backend(kind: str, exe: str = "pymobiledevice3") -> DeviceBackend:
    if kind == "fake":
        return FakeBackend(
            [
                DeviceInfo("00008110-DEMO0000000001", "iPhone démo 1", "iPhone15,2", "26.0"),
                DeviceInfo("00008110-DEMO0000000002", "iPhone démo 2", "iPhone16,1", "26.0"),
            ]
        )
    if kind == "pymobiledevice3":
        return PyMobileDeviceBackend(exe)
    raise ValueError(f"backend inconnu : {kind}")
