"""python -m loopcast content list|show|produce|approve|reject|qa"""

import json

import pytest

from loopcast import cli
from loopcast import config as cfg

from .conftest import FakeRenderer, make_video, needs_ffmpeg

pytestmark = needs_ffmpeg

PROPS = {"title": "Ce qui a changé mes matins", "items": ["Téléphone hors de la chambre", "Un verre d'eau",
                                                           "Cocher mes habitudes dans Habitudo"]}


@pytest.fixture
def root(pipe, monkeypatch):
    """La CLI lit config/ et data/ sous LOOPCAST_ROOT : on la pointe sur le pipeline de test."""
    monkeypatch.setattr(cfg, "ROOT", pipe.root)
    fake = FakeRenderer()
    monkeypatch.setattr("loopcast.modules.services", lambda config, demo=False: {"renderer": fake})
    return pipe


def test_produce_now_list_show_approve(root, capsys):
    idea_id = root.idea("notes-app", props=PROPS)
    assert cli.main(["content", "produce", idea_id, "--now"]) == 0
    out = capsys.readouterr().out
    assert "Production demandée" in out and "content.render" in out and f"Contenu {idea_id} : à valider" in out

    assert cli.main(["content", "list", "--status", "review"]) == 0
    assert idea_id in capsys.readouterr().out
    assert cli.main(["content", "show", idea_id]) == 0
    out = capsys.readouterr().out
    assert "Statut : à valider" in out and "Contrôle qualité : réussi" in out and "#habitudes" in out

    assert cli.main(["content", "approve", idea_id]) == 0
    assert "Validé." in capsys.readouterr().out
    assert root.content(idea_id)["status"] == "approved"
    assert cli.main(["content", "produce", idea_id]) == 1                 # déjà validé : pas de relance
    assert "déjà validé" in capsys.readouterr().err


def test_reject_and_relaunch(root, capsys):
    idea_id = root.idea("notes-app", props=PROPS)
    cli.main(["content", "produce", idea_id, "--now"])
    capsys.readouterr()
    assert cli.main(["content", "reject", idea_id, "--note", "trop lent au début"]) == 0
    assert "La note servira au prochain lot" in capsys.readouterr().out
    c = root.content(idea_id)
    assert c["status"] == "rejected" and c["review_note"] == "trop lent au début"
    assert cli.main(["content", "produce", idea_id]) == 0                 # relance : nouvelle production
    assert root.content(idea_id)["run"] == 1
    assert cli.main(["content", "approve", "inconnu"]) == 1


def test_qa_command(root, tmp_path, capsys):
    assert cli.main(["content", "qa", str(make_video(tmp_path / "ok.mp4", 7))]) == 0
    out = capsys.readouterr().out
    assert "Contrôle qualité : réussi" in out and "1080×1920 h264" in out
    assert cli.main(["content", "qa", str(make_video(tmp_path / "short.mp4", 3))]) == 1
    assert "✗ Trop courte : 3,0 s, 6 s au minimum." in capsys.readouterr().out
    idea_id = root.idea("notes-app", props=PROPS)
    cli.main(["content", "produce", idea_id, "--now"])
    capsys.readouterr()
    assert cli.main(["content", "qa", idea_id]) == 0
    assert json.loads(root.content(idea_id)["qa"])["ok"]
    assert cli.main(["content", "qa", "ni-fichier-ni-contenu"]) == 1


def test_node_named_in_settings_is_found_where_it_is_installed(tmp_path, monkeypatch):
    """`render.node: node` (la valeur par défaut) ne doit pas empêcher de trouver Node dans ~/.local/node/bin quand
    le PATH du service ne l'a pas : sinon chaque rendu meurt sur « Node introuvable »."""
    from loopcast.production import options

    monkeypatch.setenv("PATH", str(tmp_path / "vide"))
    monkeypatch.setenv("HOME", str(tmp_path))
    node = tmp_path / ".local" / "node" / "bin" / "node"
    node.parent.mkdir(parents=True)
    node.write_text("#!/bin/sh\n")
    node.chmod(0o755)
    monkeypatch.setattr(options, "_TOOL_DIRS", ("~/.local/node/bin",))
    assert options.node_bin({"render": {"node": "node"}}) == str(node)
    assert options.node_bin({}) == str(node)
    assert options.node_bin({"render": {"node": str(tmp_path / "absent" / "node")}}) is None   # chemin explicite faux
