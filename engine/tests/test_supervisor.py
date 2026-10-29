import json
from datetime import datetime, timedelta, timezone

from conftest import UDID1, UDID2, health

from loopcast.farm.backend import BackendError, DeviceInfo
from loopcast.farm.health import FarmHealth, Service, Signing
from loopcast.farm.supervisor import Supervisor, list_phones


def kinds(result):
    return [k for _u, k, _m in result.events]


def phone(conn, udid):
    row = dict(conn.execute("SELECT * FROM phones WHERE udid=?", (udid,)).fetchone())
    row["problems"] = json.loads(row["problems"])
    return row


def test_new_phone_is_registered_once(config, conn, backend, clock):
    sup = Supervisor(config, conn, backend, clock)
    assert kinds(sup.tick()) == ["phone_new"]
    assert sup.tick().events == []          # rien de neuf : pas de bruit
    row = phone(conn, UDID1)
    assert row["phone_id"] == "phone-1" and row["status"] == "ok" and row["battery"] == 80


def test_problems_are_reported_on_change_only(config, conn, backend, clock):
    sup = Supervisor(config, conn, backend, clock)
    sup.tick()
    backend.healths[UDID1] = health(developer_mode=False, battery=10, charging=False)
    assert kinds(sup.tick()) == ["problem_battery_low", "problem_devmode_off"]
    assert phone(conn, UDID1)["status"] == "attention"
    assert sup.tick().events == []
    backend.healths[UDID1] = health()
    assert kinds(sup.tick()) == ["resolved_battery_low", "resolved_devmode_off"]
    assert phone(conn, UDID1)["status"] == "ok"


def test_untrusted_phone_hides_other_checks(config, conn, backend, clock):
    backend.healths[UDID1] = health(trusted=False, developer_mode=None, battery=None)
    Supervisor(config, conn, backend, clock).tick()
    assert phone(conn, UDID1)["problems"] == ["untrusted"]


def test_unknown_phone(config, conn, backend, clock):
    backend.devices.append(DeviceInfo("00008110-STRANGER", "iPhone ?", "iPhone14,5", "26.0"))
    Supervisor(config, conn, backend, clock).tick()
    row = phone(conn, "00008110-STRANGER")
    assert row["status"] == "unknown" and row["phone_id"] is None


def test_unplugged_then_alert_after_grace_then_back(config, conn, backend, clock):
    sup = Supervisor(config, conn, backend, clock)
    sup.tick()
    backend.devices.clear()
    assert kinds(sup.tick()) == ["phone_gone"]
    assert phone(conn, UDID1)["status"] == "offline"
    clock.advance(minutes=5)
    assert sup.tick().events == []                     # encore dans le délai de grâce
    clock.advance(minutes=6)
    assert kinds(sup.tick()) == ["problem_offline"]
    clock.advance(minutes=30)
    assert sup.tick().events == []                     # une seule alerte
    backend.devices.append(DeviceInfo(UDID1, "iPhone de Sarah", "iPhone15,2", "26.0"))
    assert kinds(sup.tick()) == ["phone_back"]
    assert phone(conn, UDID1)["status"] == "ok"


def test_listing_failure_is_logged_not_raised(config, conn, clock):
    class Broken:
        def list_devices(self):
            raise BackendError("usbmuxd ne répond pas")

    result = Supervisor(config, conn, Broken(), clock).tick()
    assert kinds(result) == ["farm_error"]


def test_list_includes_declared_but_never_seen(config, conn, backend, clock):
    Supervisor(config, conn, backend, clock).tick()
    rows = {r["phone_id"]: r for r in list_phones(conn, config)}
    assert rows["phone-1"]["status"] == "ok" and rows["phone-1"]["model_name"] == "iPhone 14 Pro"
    assert rows["phone-2"]["status"] == "never_seen" and rows["phone-2"]["udid"] == UDID2
    assert rows["phone-3"]["problems"][0]["message"] == "Place libre"


# --- Santé de la ferme hors iPhones : Appium, tunneld, signature de WebDriverAgent -------------------------

class FarmChecks:
    """Appium, tunneld et la signature, réglables à la main."""

    def __init__(self):
        self.appium = Service(True, "prêt (3.9.0)")
        self.tunneld = Service(True, "actif, aucun iPhone en tunnel")
        self.signing = Signing("ok", datetime(2026, 11, 4, 21, 11, tzinfo=timezone.utc), "x.xctrunner")

    def check(self, now):
        return FarmHealth(now, self.appium, self.tunneld, self.signing)


def farm_kinds(result):
    return [k for udid, k, _m in result.events if udid is None]


def test_a_service_down_is_reported_after_two_rounds_and_once(config, conn, backend, clock):
    checks = FarmChecks()
    sup = Supervisor(config, conn, backend, clock, checks=checks)
    first = sup.tick()
    assert farm_kinds(first) == [] and first.farm_changed           # premier tour : la page se remplit
    assert not sup.tick().farm_changed                               # rien n'a bougé : pas de mise à jour
    checks.appium = Service(False, "ne répond pas")
    blip = sup.tick()
    assert farm_kinds(blip) == [] and blip.farm_changed             # un redémarrage d'Appium ne réveille personne
    assert farm_kinds(sup.tick()) == ["problem_appium_down"]
    assert farm_kinds(sup.tick()) == [] and sup.farm_problems == {"appium_down"}
    # Le serveur redémarre : le problème est repris du journal, sans nouvelle alerte.
    restarted = Supervisor(config, conn, backend, clock, checks=checks)
    assert farm_kinds(restarted.tick()) == [] and restarted.farm_problems == {"appium_down"}
    checks.appium = Service(True, "prêt (3.9.0)")
    assert farm_kinds(restarted.tick()) == ["resolved_appium_down"]
    assert [r["message"] for r in conn.execute("SELECT message FROM events WHERE phone_udid IS NULL ORDER BY id")] == \
        ["Appium ne répond pas : aucune prise en main possible", "Appium répond de nouveau"]


def test_signing_warns_then_worsens_then_is_renewed_once(config, conn, backend, clock):
    checks = FarmChecks()
    expires = checks.signing.expires_at
    sup = Supervisor(config, conn, backend, clock, checks=checks)
    sup.tick()
    checks.signing = Signing("expiring", expires, "x.xctrunner")
    assert farm_kinds(sup.tick()) == ["problem_signing_expiring"]
    checks.signing = Signing("expired", expires, "x.xctrunner")
    assert farm_kinds(sup.tick()) == ["problem_signing_expired"]    # elle s'aggrave : pas de « résolu » au passage
    restarted = Supervisor(config, conn, backend, clock, checks=checks)
    assert farm_kinds(restarted.tick()) == [] and restarted.farm_problems == {"signing_expired"}
    checks.signing = Signing("missing")                              # plus de profil lisible : on ne conclut rien
    assert farm_kinds(restarted.tick()) == [] and restarted.farm_problems == {"signing_expired"}
    checks.signing = Signing("ok", expires + timedelta(days=7), "x.xctrunner")
    assert farm_kinds(restarted.tick()) == ["resolved_signing_expired"] and restarted.farm_problems == set()


def test_a_failing_farm_check_does_not_stop_the_phones(config, conn, backend, clock):
    class Broken:
        def check(self, now):
            raise RuntimeError("vérification impossible")

    assert kinds(Supervisor(config, conn, backend, clock, checks=Broken()).tick()) == ["phone_new"]
