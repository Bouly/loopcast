import json

from conftest import UDID1, UDID2, health

from loopcast.farm.backend import BackendError, DeviceInfo
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
    assert rows["phone-1"]["status"] == "ok"
    assert rows["phone-2"]["status"] == "never_seen" and rows["phone-2"]["udid"] == UDID2
    assert rows["phone-3"]["problems"][0]["message"] == "UDID à renseigner"
