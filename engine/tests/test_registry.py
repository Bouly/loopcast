"""Ajouter un iPhone depuis le dashboard (farm/registry.py) : devices.yaml ne change qu'à l'endroit voulu."""

import pytest
import yaml
from conftest import UDID1, UDID2

from loopcast.farm import registry
from loopcast.farm.registry import RegistryError

NEW = "00008101-00064CD9NEW00001"

DEVICES = """\
# Copier en config/devices.yaml (ignoré par git).
defaults:
  timezone: Europe/Paris

devices:
  - id: phone-1
    model: iPhone 15 Pro
    udid: "00008110-AAAA00000001"
    owner: "Sarah"
    lang: fr
    brands: [habitudo]
    accounts:
      tiktok:    {handle: "@habitudo.fr", created: 2026-11-01, channel: api_draft}

  - id: phone-2
    model: iPhone
    udid: "00008110-AAAA00000002"
    owner: "Yanis"
    lang: en
    brands: [habitudo]
    accounts: {}

  - id: phone-3
    model: iPhone
    udid: null          # à renseigner
    owner: ""
    lang: fr
    brands: []          # à affecter à la 2e app
    accounts: {}
"""


@pytest.fixture
def devices(config):
    path = config.root / "config" / "devices.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(DEVICES)
    return path


def test_a_free_line_gets_the_udid_and_nothing_else_moves(config, devices):
    phone = registry.adopt(config, NEW, "phone-3", connected={UDID1}, owner="Ahmed", model="iPhone 12 mini")
    assert phone.id == "phone-3" and config.phone_by_udid(NEW) is phone and phone.owner == "Ahmed"
    expected = DEVICES.replace(
        '    model: iPhone\n    udid: null          # à renseigner\n    owner: ""\n    lang: fr',
        '    model: "iPhone 12 mini"\n    udid: "00008101-00064CD9NEW00001"          # à renseigner\n'
        '    owner: "Ahmed"\n    lang: fr',
    )
    assert devices.read_text() == expected          # commentaires, ordre et autres lignes intacts


def test_a_new_line_goes_at_the_end_with_the_next_number(config, devices):
    phone = registry.adopt(config, NEW, None, connected=set(), lang="en", model="iPhone 12 mini")
    assert (phone.id, phone.slot, phone.lang) == ("phone-4", 3, "en")
    assert devices.read_text().startswith(DEVICES)  # rien de touché au-dessus : les ports des autres ne bougent pas
    data = yaml.safe_load(devices.read_text())
    assert [d["id"] for d in data["devices"]] == ["phone-1", "phone-2", "phone-3", "phone-4"]
    assert data["devices"][3] == {"id": "phone-4", "model": "iPhone 12 mini", "udid": NEW, "owner": "", "lang": "en",
                                  "brands": [], "accounts": {}}


def test_an_unplugged_phone_can_be_replaced_and_hands_over_its_line(config, devices):
    phone = registry.adopt(config, NEW, "phone-2", connected={UDID1})
    assert phone.id == "phone-2" and config.phone_by_udid(UDID2) is None
    data = yaml.safe_load(devices.read_text())
    assert data["devices"][1]["udid"] == NEW and data["devices"][1]["owner"] == "Yanis"


@pytest.mark.parametrize("udid, phone_id, why", [
    (UDID1, "phone-3", "déjà partie de la ferme : phone-1"),
    (NEW, "phone-1", "phone-1 est branché"),
    (NEW, "phone-9", "phone-9 n'existe pas"),
])
def test_refusals_write_nothing(config, devices, udid, phone_id, why):
    with pytest.raises(RegistryError, match=why):
        registry.adopt(config, udid, phone_id, connected={UDID1})
    assert devices.read_text() == DEVICES
    assert config.phone_by_udid(NEW) is None


def test_the_demo_never_writes_the_real_file(config, devices):
    config.demo = True
    with pytest.raises(RegistryError, match="En démo"):
        registry.adopt(config, NEW, "phone-3", connected=set())
    assert devices.read_text() == DEVICES


def test_without_devices_yaml_the_example_is_copied_first(config):
    example = config.root / "config" / "devices.example.yaml"
    example.parent.mkdir(parents=True)
    example.write_text(DEVICES)
    registry.adopt(config, NEW, "phone-3", connected=set())
    assert yaml.safe_load((config.root / "config" / "devices.yaml").read_text())["devices"][2]["udid"] == NEW
    assert example.read_text() == DEVICES


def test_slots_say_which_lines_are_free_or_plugged(config):
    slots = {s["phone_id"]: s for s in registry.slots(config, connected={UDID1})}
    assert (slots["phone-1"]["free"], slots["phone-1"]["connected"]) == (False, True)
    assert (slots["phone-2"]["free"], slots["phone-2"]["connected"]) == (False, False)
    assert slots["phone-3"]["free"] is True
