"""python -m loopcast <commande>"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import httpx

from loopcast import config as cfg
from loopcast import db


def _setup(args) -> tuple[cfg.Config, object]:
    config = cfg.load()
    if getattr(args, "demo", False):
        config.farm.backend = "fake"
    return config, db.connect(config.db_path)


def _backend(config: cfg.Config):
    from loopcast.farm.backend import make_backend

    return make_backend(config.farm.backend, config.farm.pymobiledevice3)


def _resolve(config: cfg.Config, ref: str) -> str:
    """Accepte « phone-1 » ou un UDID."""
    phone = config.phone_by_id(ref)
    if phone and phone.udid:
        return phone.udid
    return ref


def cmd_serve(args) -> int:
    import uvicorn

    from loopcast.api.app import create_app

    config, conn = _setup(args)
    if args.demo:
        _seed_demo_config(config)
    app = create_app(config, conn, _backend(config), supervise=not args.no_supervise,
                     web_dist=config.root / "web" / "dist")
    if args.host not in ("127.0.0.1", "localhost") and not args.host.startswith("100."):
        print("Attention : n'écouter que sur 127.0.0.1 ou l'adresse Tailscale (100.x), jamais sur internet.",
              file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _seed_demo_config(config: cfg.Config) -> None:
    """En démo, les deux iPhones simulés sont rattachés à phone-1 et phone-2."""
    from loopcast.farm.backend import make_backend

    for phone, dev in zip(config.phones, make_backend("fake").list_devices()):
        phone.udid = dev.udid


def cmd_farm_list(args) -> int:
    from loopcast.farm.supervisor import Supervisor, list_phones

    config, conn = _setup(args)
    if args.demo:
        _seed_demo_config(config)
    Supervisor(config, conn, _backend(config)).tick()
    rows = list_phones(conn, config)
    if not rows:
        print("Aucun iPhone branché ni déclaré.")
    for r in rows:
        battery = f"{r['battery']} %" if r["battery"] is not None else "—"
        problems = " ; ".join(p["message"] for p in r["problems"]) or "—"
        print(f"{(r['phone_id'] or '?'):<10} {r['status']:<11} iOS {r['ios'] or '—':<6} {battery:>6}  "
              f"{r['udid'] or '(UDID à renseigner)'}  {problems}")
    return 0


def cmd_farm_watch(args) -> int:
    from loopcast.farm.supervisor import Supervisor
    from loopcast.notify import is_alert, notify

    config, conn = _setup(args)
    if args.demo:
        _seed_demo_config(config)

    def on_events(events):
        for _udid, kind, message in events:
            print(message, flush=True)
            if is_alert(kind) and not args.quiet:
                notify("Loopcast · ferme", message, config.settings.get("notify"))

    stop = threading.Event()
    try:
        Supervisor(config, conn, _backend(config)).run_forever(stop, on_events)
    except KeyboardInterrupt:
        stop.set()
    return 0


def cmd_farm_screenshot(args) -> int:
    config, _conn = _setup(args)
    udid = _resolve(config, args.phone)
    out = Path(args.out or f"{args.phone}.png")
    out.write_bytes(_backend(config).screenshot(udid))
    print(out)
    return 0


def cmd_farm_doctor(args) -> int:
    """Vérifie tout ce qu'il faut sur le Mac de la ferme, avec la marche à suivre pour chaque manque."""
    config, _conn = _setup(args)
    ok = True

    def check(label: str, passed: bool, fix: str) -> None:
        nonlocal ok
        ok &= passed
        print(f"{'✓' if passed else '✗'} {label}" + ("" if passed else f"\n    → {fix}"))

    def run(*cmd: str) -> str | None:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return p.stdout if p.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    check("macOS", sys.platform == "darwin", "la ferme tourne sur le Mac (USB), pas dans Docker")
    xcode = run("xcodebuild", "-version")
    check(f"Xcode ({xcode.splitlines()[0] if xcode else 'absent'})", bool(xcode),
          "installer Xcode depuis l'App Store, puis : sudo xcode-select -s /Applications/Xcode.app")
    check("pymobiledevice3", shutil.which(config.farm.pymobiledevice3) is not None,
          "pipx install pymobiledevice3 (ou pip install -e 'engine[ios]')")
    try:
        httpx.get("http://127.0.0.1:49151/", timeout=3)
        tunneld = True
    except httpx.HTTPError:
        tunneld = False
    check("tunneld (iOS 17+ : captures, mode développeur)", tunneld,
          "sudo pymobiledevice3 remote tunneld  (à lancer au démarrage, voir ops/)")
    check("Appium", shutil.which("appium") is not None, "npm install -g appium")
    drivers = ""
    if shutil.which("appium"):   # appium écrit cette liste sur stderr selon les versions
        p = subprocess.run(["appium", "driver", "list", "--installed"], capture_output=True, text=True, timeout=60)
        drivers = p.stdout + p.stderr
    check("Driver XCUITest", "xcuitest" in drivers, "appium driver install xcuitest")
    try:
        status = httpx.get(f"{config.farm.appium_url}/status", timeout=3).status_code == 200
    except httpx.HTTPError:
        status = False
    check(f"Serveur Appium ({config.farm.appium_url})", status, "appium  (à lancer au démarrage, voir ops/)")
    check("Signature WebDriverAgent (farm.xcode_org_id)", bool(config.farm.xcode_org_id),
          "renseigner farm.xcode_org_id (Team ID Apple Developer) dans config/settings.yaml")
    declared = [p for p in config.phones if p.udid]
    check(f"iPhones déclarés avec UDID ({len(declared)}/{len(config.phones)})", bool(declared),
          "brancher l'iPhone, `python -m loopcast farm list`, copier l'UDID dans config/devices.yaml")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    p = argparse.ArgumentParser(prog="loopcast")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="API (et front construit) sur http://127.0.0.1:8787")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--no-supervise", action="store_true", help="ne pas lancer la supervision en fond")
    s.add_argument("--demo", action="store_true", help="iPhones simulés (sans Mac ni téléphone)")
    s.set_defaults(fn=cmd_serve)

    farm = sub.add_parser("farm", help="ferme d'iPhones").add_subparsers(dest="farm_cmd", required=True)
    f = farm.add_parser("list", help="état de chaque iPhone")
    f.add_argument("--demo", action="store_true")
    f.set_defaults(fn=cmd_farm_list)
    f = farm.add_parser("watch", help="supervision continue dans le terminal")
    f.add_argument("--demo", action="store_true")
    f.add_argument("--quiet", action="store_true", help="sans notifications")
    f.set_defaults(fn=cmd_farm_watch)
    f = farm.add_parser("screenshot", help="capture d'écran d'un iPhone")
    f.add_argument("phone", help="phone-1 ou UDID")
    f.add_argument("-o", "--out")
    f.set_defaults(fn=cmd_farm_screenshot)
    f = farm.add_parser("doctor", help="vérifie les prérequis du Mac de la ferme")
    f.set_defaults(fn=cmd_farm_doctor)

    args = p.parse_args(argv)
    return args.fn(args)
