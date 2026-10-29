"""python -m loopcast strategy … : de la fiche approuvée aux idées, en démo, sans worker.

En démo, tout se passe dans la base de démo (data/demo.db) ; la vraie base n'est jamais créée."""

import pytest
import yaml

from loopcast import cli
from loopcast import config as cfg
from loopcast import db
from loopcast.strategy import store

from .helpers import APP, seed_app


@pytest.fixture
def root(tmp_path, monkeypatch, clock):
    (tmp_path / "config").mkdir()
    devices = {"devices": [
        {"id": "phone-1", "lang": "fr", "brands": [APP],
         "accounts": {"tiktok": {"handle": "@h.fr", "created": "2026-10-01"}}},
        {"id": "phone-2", "lang": "en", "brands": [APP],
         "accounts": {"tiktok": {"handle": "@h.en", "created": "2026-10-01"}}},
    ]}
    (tmp_path / "config" / "devices.yaml").write_text(yaml.safe_dump(devices))
    (tmp_path / "config" / "settings.yaml").write_text(
        yaml.safe_dump({"pipeline": {"stock_target": 2, "ideas_per_batch": 2}}))
    monkeypatch.setattr(cfg, "ROOT", tmp_path)
    conn = db.connect(tmp_path / "data" / "demo.db")
    seed_app(conn, clock())
    conn.close()
    return tmp_path


def test_cli_from_brief_to_ideas(root, capsys):
    assert cli.main(["--demo", "strategy", "show", APP]) == 0
    assert "aucune stratégie" in capsys.readouterr().out

    assert cli.main(["--demo", "strategy", "generate", APP, "--run", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "Nouvelle stratégie demandée" in out and "strategy.generate → done" in out

    assert cli.main(["--demo", "strategy", "show", APP]) == 0
    out = capsys.readouterr().out
    assert "stratégie v1 (draft" in out and "phone-2 (en)" in out

    assert cli.main(["--demo", "strategy", "approve", APP]) == 0
    assert "v1 approuvée" in capsys.readouterr().out

    assert cli.main(["--demo", "strategy", "generate", APP, "--stock", "--run", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "ideas.ensure_stock → done" in out and out.count("ideas.generate → done") == 2

    assert cli.main(["--demo", "strategy", "ideas", APP, "--phone", "phone-2"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 2 and all("phone-2" in line and "approved" in line for line in lines)

    idea_id = lines[0].split()[0]
    assert cli.main(["--demo", "strategy", "ideas", "--reject", idea_id, "--note", "hors ton"]) == 0
    conn = db.connect(root / "data" / "demo.db")
    assert store.get_idea(conn, idea_id)["review_note"] == "hors ton"

    assert cli.main(["--demo", "strategy", "generate", APP, "--phone", "phone-9"]) == 1
    assert cli.main(["--demo", "strategy", "approve", APP]) == 1                 # plus de brouillon
    assert "aucun brouillon" in capsys.readouterr().err
    assert not (root / "data" / "loopcast.db").exists()                       # la vraie base jamais ouverte
