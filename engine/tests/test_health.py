"""Santé de la ferme hors iPhones : Appium, tunneld et la signature de WebDriverAgent (farm/health.py)."""

import plistlib
from datetime import datetime, timedelta, timezone

import httpx

from loopcast.farm import health
from loopcast.farm.health import FarmHealth, Service, Signing

NOW = datetime(2026, 10, 29, 17, 0, tzinfo=timezone.utc)
RUNNER = "TEAM123.com.equipe.loopcast.wda.xctrunner"


def write_profile(folder, name, app_id, expires):
    """Un .mobileprovision comme ceux de Xcode : le plist en clair au milieu de l'enveloppe signée."""
    plist = plistlib.dumps({"Entitlements": {"application-identifier": app_id},
                            "ExpirationDate": expires.astimezone(timezone.utc).replace(tzinfo=None),
                            "TeamIdentifier": [app_id.split(".")[0]]})
    folder.mkdir(parents=True, exist_ok=True)
    envelope = b"0\x82\x1f\xa0\x06\t*\x86H" + plist + b"\xa0\x82\x0b\x00 signature"
    (folder / f"{name}.mobileprovision").write_bytes(envelope)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def refused(request):
    raise httpx.ConnectError("connexion refusée", request=request)


def test_profile_is_read_inside_the_signed_envelope(tmp_path):
    write_profile(tmp_path, "wda", RUNNER, NOW)
    assert health.read_profile(tmp_path / "wda.mobileprovision")["Entitlements"]["application-identifier"] == RUNNER
    (tmp_path / "abime.mobileprovision").write_bytes(b"\x00\x01 pas de plist")
    assert health.read_profile(tmp_path / "abime.mobileprovision") is None


def test_signing_takes_our_runner_profile_that_expires_last(config, tmp_path):
    config.farm.wda_bundle_id = "com.equipe.loopcast.wda"
    xcode16, older = tmp_path / "UserData", tmp_path / "MobileDevice"
    write_profile(xcode16, "ancien", RUNNER, NOW - timedelta(days=1))            # expiré, Xcode le garde
    write_profile(older, "actuel", RUNNER, NOW + timedelta(days=6))
    write_profile(xcode16, "autre-equipe", "OTHER.com.equipe.loopcast.wda.xctrunner", NOW + timedelta(days=300))
    write_profile(xcode16, "autre-app", "TEAM123.com.equipe.autre.xctrunner", NOW + timedelta(days=300))
    dirs = [xcode16, older]
    s = health.signing_status(config, NOW, dirs)
    assert (s.state, s.expires_at, s.app_id) == ("ok", NOW + timedelta(days=6), "com.equipe.loopcast.wda.xctrunner")
    assert health.signing_status(config, NOW + timedelta(days=3, hours=1), dirs).state == "expiring"  # 3 j ou moins
    assert health.signing_status(config, NOW + timedelta(days=6), dirs).state == "expired"


def test_signing_wildcard_profile_missing_profile_and_no_team(config, tmp_path):
    # Apple Developer payant : un profil joker couvre tous les identifiants de l'équipe (ici celui d'Appium).
    write_profile(tmp_path, "joker", "TEAM123.*", NOW + timedelta(days=365))
    assert health.signing_status(config, NOW, [tmp_path]).state == "ok"
    assert health.signing_status(config, NOW, [tmp_path / "vide"]).state == "missing"
    config.farm.xcode_org_id = None
    assert health.signing_status(config, NOW, [tmp_path]).state == "unconfigured"


def test_appium_status():
    ready = {"value": {"ready": True, "message": "ready", "build": {"version": "3.9.0"}}}
    assert health.check_appium("http://appium", client(lambda r: httpx.Response(200, json=ready))) == \
        Service(True, "prêt (3.9.0)")
    starting = client(lambda r: httpx.Response(200, json={"value": {"ready": False}}))
    assert not health.check_appium("http://appium", starting).ok
    assert health.check_appium("http://appium", client(lambda r: httpx.Response(500))) == \
        Service(False, "répond HTTP 500")
    assert health.check_appium("http://appium", client(refused)) == Service(False, "ne répond pas")


def test_tunneld_status():
    tunnels = {"UDID1": [{"tunnel-address": "fd00::1", "tunnel-port": 50000}], "UDID2": [{}]}
    assert health.check_tunneld("http://t", client(lambda r: httpx.Response(200, json={}))) == \
        Service(True, "actif, aucun iPhone en tunnel")
    assert health.check_tunneld("http://t", client(lambda r: httpx.Response(200, json=tunnels))).detail == \
        "actif, 2 iPhones en tunnel"
    assert health.check_tunneld("http://t", client(refused)) == Service(False, "ne répond pas")


def test_texts_are_in_the_team_timezone(config):
    expires = datetime(2026, 11, 4, 21, 11, tzinfo=timezone.utc)                 # 22 h 11 à Paris (heure d'hiver)
    h = FarmHealth(expires - timedelta(days=2), Service(True, "prêt"), Service(True, "actif"),
                   Signing("expiring", expires, "x.xctrunner"))
    tz = health.farm_tz(config)
    assert health.problem_message("signing_expiring", h, tz) == \
        "La signature de WebDriverAgent expire le 4 nov. à 22 h 11, heure de Paris (dans 2 jours)"
    assert health.resolved_message("signing_expired", h, tz) == \
        "Signature de WebDriverAgent renouvelée : valable jusqu'au 4 nov. à 22 h 11, heure de Paris"
    assert health.resolved_message("tunneld_down", h, tz) == "tunneld répond de nouveau"
    # Le Mac de la ferme peut être ailleurs : le fuseau est toujours écrit.
    assert health.date_text(expires, "Asia/Bangkok") == "5 nov. à 4 h 11, heure de Bangkok"


def test_status_lists_the_problems_with_what_to_do(config):
    h = FarmHealth(NOW, Service(False, "ne répond pas"), Service(True, "actif"),
                   Signing("ok", NOW + timedelta(days=6), "x.xctrunner"))
    status = health.status_dict(h, {"appium_down"}, config)
    assert status["appium"] == {"ok": False, "detail": "ne répond pas"}
    assert status["signing"] == {"state": "ok", "expires_at": "2026-11-04T17:00:00+00:00", "app_id": "x.xctrunner"}
    assert status["problems"] == [{"code": "appium_down", "level": "bad",
                                   "message": "Appium ne répond pas : aucune prise en main possible",
                                   "fix": health.FARM_PROBLEMS["appium_down"][2]}]
    assert health.status_dict(None, set(), config)["problems"] == []
