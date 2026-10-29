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
    applied = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    assert applied == {p.stem for p in db.migration_files()}
    assert db.migrate(conn) == []


def test_tools_are_found_where_uv_and_node_install_them(tmp_path, monkeypatch):
    """Le diagnostic et les services cherchent aussi dans ~/.local/bin et ~/.local/node/bin : un PATH sans eux
    (service launchd, autre terminal) ne fait plus croire qu'Appium manque."""
    from pathlib import Path

    from loopcast.farm.backend import _find_exe, find_exe

    monkeypatch.setenv("PATH", str(tmp_path / "vide"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    name = "outil-ferme-factice"
    assert find_exe(name) is None and _find_exe(name) == name
    tool = tmp_path / ".local" / "node" / "bin" / name
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    assert find_exe(name) == str(tool) and _find_exe(name) == str(tool)
    assert find_exe(str(tool)) == str(tool) and find_exe(str(tmp_path / "absent")) is None
