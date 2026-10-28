"""python -m loopcast apps … : tout le parcours en ligne de commande, en démo (sans clé ni worker)."""

import re
import shutil

from loopcast import config as config_module
from loopcast.cli import main

from .helpers import REPO, png


def test_cli_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config_module, "ROOT", tmp_path)
    (tmp_path / "brands").mkdir()
    shutil.copy(REPO / "brands" / "habitudo.json", tmp_path / "brands" / "habitudo.json")
    shot = tmp_path / "accueil.png"
    shot.write_bytes(png(300, 650))

    assert main(["apps", "add", "habitudo"]) == 0
    out = capsys.readouterr().out
    assert "App « Habitudo » (habitudo) ajoutée, langues : fr, en." in out and "Reprise de brands/habitudo.json" in out

    assert main(["apps", "upload", "habitudo", str(shot), str(tmp_path / "absent.png")]) == 1
    out = capsys.readouterr().out
    assert "#1 screenshot 300×650 accueil.png" in out and "absent.png : introuvable" in out

    assert main(["apps", "analyze", "habitudo", "--run", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "apps.describe_asset #1 : terminée" in out and "apps.analyze #2 : terminée" in out
    assert "Statut : questions à traiter." in out

    assert main(["apps", "questions", "habitudo"]) == 0
    ids = [int(i) for i in re.findall(r"^#(\d+) \[", capsys.readouterr().out, re.M)]
    assert len(ids) == 4
    for qid in ids[:-1]:
        assert main(["apps", "answer", "habitudo", str(qid), "Gratuit", "pour", "toujours"]) == 0
    assert "Encore 1 question(s) ouverte(s)." in capsys.readouterr().out
    assert main(["apps", "answer", "habitudo", str(ids[-1]), "--skip", "--run", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "la fiche va être affinée" in out and "apps.refine #3 : terminée" in out and "Statut : fiche prête." in out

    assert main(["apps", "approve", "habitudo"]) == 0
    assert "Fiche v2 approuvée. Stratégie demandée (tâche #4" in capsys.readouterr().out
    assert main(["apps", "list"]) == 0
    assert re.search(r"habitudo\s+fiche prête\s+1 captures\s+fiche v2 approuvée", capsys.readouterr().out)
    assert main(["apps", "show", "habitudo"]) == 0
    out = capsys.readouterr().out
    assert "Habitudo (habitudo) · fiche prête · langues fr, en" in out and "[fr] 3 habitudes" in out
    assert "Fiche v2 (affinée avec les réponses de l'équipe, approuvée)" in out

    assert main(["apps", "show", "inconnue"]) == 1
    assert "Erreur : app inconnue : « inconnue »" in capsys.readouterr().out
