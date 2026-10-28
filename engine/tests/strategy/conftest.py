import pytest

from loopcast import db
from loopcast.strategy import demo, prompts, tasks  # noqa: F401  (tâches et réponses de démo enregistrées)

from .helpers import make_config, seed_app


@pytest.fixture
def sconfig(tmp_path):
    return make_config(tmp_path)


@pytest.fixture
def sconn():
    return db.connect(":memory:")


@pytest.fixture
def seeded(sconn, clock):
    return seed_app(sconn, clock())


@pytest.fixture(autouse=True)
def no_playbook(tmp_path, monkeypatch):
    """Par défaut, pas de playbook : le repli intégré au prompt est utilisé."""
    empty = tmp_path / "knowledge"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(prompts, "KNOWLEDGE_DIR", empty)
    return empty
