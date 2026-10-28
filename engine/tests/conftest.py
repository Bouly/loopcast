from datetime import datetime, timedelta, timezone

import pytest

from loopcast import db
from loopcast.config import Config, FarmSettings, PhoneConfig
from loopcast.farm.backend import DeviceHealth, DeviceInfo, FakeBackend

UDID1 = "00008110-AAAA00000001"
UDID2 = "00008110-AAAA00000002"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def config(tmp_path):
    return Config(
        root=tmp_path,
        settings={},
        farm=FarmSettings(backend="fake", offline_alert_minutes=10, battery_low=25, xcode_org_id="TEAM123"),
        phones=[
            PhoneConfig("phone-1", UDID1, owner="Sarah", slot=0),
            PhoneConfig("phone-2", UDID2, owner="Yanis", slot=1),
            PhoneConfig("phone-3", None, slot=2),
        ],
    )


@pytest.fixture
def conn():
    return db.connect(":memory:")


@pytest.fixture
def backend():
    return FakeBackend([DeviceInfo(UDID1, "iPhone de Sarah", "iPhone15,2", "26.0")])


def health(**kw) -> DeviceHealth:
    base = dict(trusted=True, developer_mode=True, battery=80, charging=True)
    base.update(kw)
    return DeviceHealth(**base)
