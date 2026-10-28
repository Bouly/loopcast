import json
import subprocess

from loopcast import db
from loopcast.farm.backend import PyMobileDeviceBackend


def fake_run(outputs: dict):
    def run(cmd, **_kw):
        key = " ".join(cmd[1:3])
        out = outputs.get(key)
        if isinstance(out, Exception):
            return subprocess.CompletedProcess(cmd, 1, "", str(out))
        return subprocess.CompletedProcess(cmd, 0, out if isinstance(out, str) else json.dumps(out), "")
    return run


def test_usbmux_list_prefers_usb(monkeypatch):
    devices = [
        {"UniqueDeviceID": "U1", "DeviceName": "A", "ProductType": "iPhone15,2", "ProductVersion": "26.0",
         "ConnectionType": "Network"},
        {"UniqueDeviceID": "U1", "DeviceName": "A", "ProductType": "iPhone15,2", "ProductVersion": "26.0",
         "ConnectionType": "USB"},
        {"Identifier": "U2", "DeviceName": "B"},
    ]
    monkeypatch.setattr(subprocess, "run", fake_run({"usbmux list": devices}))
    got = {d.udid: d for d in PyMobileDeviceBackend().list_devices()}
    assert got["U1"].connection == "USB" and got["U2"].name == "B"


def test_health(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run({
        "lockdown info": {"DeviceName": "A"},
        "amfi developer-mode-status": "true\n",
        "diagnostics battery": {"CurrentCapacity": 64, "IsCharging": False},
    }))
    h = PyMobileDeviceBackend().health("U1")
    assert (h.trusted, h.developer_mode, h.battery, h.charging) == (True, True, 64, False)


def test_health_untrusted(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run({"lockdown info": RuntimeError("PairingDialogResponsePending")}))
    h = PyMobileDeviceBackend().health("U1")
    assert h.trusted is False


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "x.db"
    db.connect(path).close()
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
