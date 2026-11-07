"""Tests headless du parsing et de la validation des manifests du catalogue."""

from __future__ import annotations

import pytest

from engine.models import (
    ActionKind,
    ManifestError,
    parse_app_metadata,
    parse_version_manifest,
)

APP_YAML_VALIDE = """
application: vim
display_name: Vim
enabled: true
version_detection:
  binary: vim
  fallback_binary: vim2
  args: ["--version"]
  pattern: 'Vi IMproved (\\S+)'
  timeout_seconds: 5
"""

MANIFEST_YAML_VALIDE = """
version: "9.1.0700"
files:
  - source: vim-9.1.0700.tar.gz
    action: decompress
    target: "~/.local/share/vim"
  - source: vim
    action: copy
    target: "~/.local/bin/vim"
    mode: "755"
  - source: vimrc.fragment
    action: ensure_content
    target: "~/.vimrc"
"""


def test_parse_app_metadata_valide() -> None:
    """Un app.yaml conforme produit des métadonnées complètes."""
    metadata = parse_app_metadata("vim", APP_YAML_VALIDE)
    assert metadata.name == "vim"
    assert metadata.display_name == "Vim"
    assert metadata.enabled is True
    assert metadata.detection.binary == "vim"
    assert metadata.detection.fallback_binary == "vim2"
    assert metadata.detection.args == ("--version",)
    assert metadata.detection.timeout_seconds == 5


def test_parse_app_metadata_valeurs_par_defaut() -> None:
    """Les champs optionnels omis reçoivent des valeurs par défaut sûres."""
    metadata = parse_app_metadata(
        "openshift_cnpg",
        """
version_detection:
  binary: kubectl-cnpg
  pattern: '(\\S+)'
""",
    )
    assert metadata.display_name == "Openshift Cnpg"
    assert metadata.enabled is True
    assert metadata.detection.args == ()
    assert metadata.detection.timeout_seconds == 5


def test_parse_app_metadata_nom_incoherent() -> None:
    """Le champ 'application' doit correspondre au nom du dossier."""
    with pytest.raises(ManifestError, match="ne correspond pas au nom du dossier"):
        parse_app_metadata("vim", APP_YAML_VALIDE.replace("application: vim", "application: nano"))


def test_parse_app_metadata_detection_absente() -> None:
    """L'absence de section version_detection est refusée."""
    with pytest.raises(ManifestError, match="version_detection"):
        parse_app_metadata("vim", "display_name: Vim\n")


def test_parse_app_metadata_cle_inconnue() -> None:
    """Les clés hors schéma sont rejetées explicitement."""
    with pytest.raises(ManifestError, match="clés inconnues"):
        parse_app_metadata("vim", APP_YAML_VALIDE + "telechargement: https://...\n")


def test_parse_app_metadata_pattern_invalide() -> None:
    """Une regex de détection invalide est refusée au parsing."""
    with pytest.raises(ManifestError, match="regex valide"):
        parse_app_metadata(
            "vim",
            """
version_detection:
  binary: vim
  pattern: '(non ferme'
""",
        )


def test_parse_app_metadata_yaml_invalide() -> None:
    """Un YAML syntaxiquement invalide lève une ManifestError."""
    with pytest.raises(ManifestError, match="YAML invalide"):
        parse_app_metadata("vim", "version_detection: [non fermé\n  - {")


def test_parse_manifest_valide() -> None:
    """Un manifest conforme produit la liste ordonnée de ses actions."""
    manifest = parse_version_manifest("vim", "9.1.0700", MANIFEST_YAML_VALIDE)
    assert manifest.application == "vim"
    assert manifest.version == "9.1.0700"
    assert [f.action for f in manifest.files] == [
        ActionKind.DECOMPRESS,
        ActionKind.COPY,
        ActionKind.ENSURE_CONTENT,
    ]
    assert manifest.files[1].mode == "755"
    assert manifest.files[2].mode == ""


def test_parse_manifest_version_implicite() -> None:
    """Le champ 'version' peut être omis s'il égal le nom du dossier."""
    manifest = parse_version_manifest(
        "vim",
        "9.1.0700",
        """
files:
  - {source: a.txt, action: copy, target: ~/a.txt}
""",
    )
    assert manifest.version == "9.1.0700"


def test_parse_manifest_version_incoherente() -> None:
    """Le champ 'version' doit correspondre au nom du dossier de version."""
    with pytest.raises(ManifestError, match="ne correspond pas au nom du dossier"):
        parse_version_manifest("vim", "9.1.0800", MANIFEST_YAML_VALIDE)


def test_parse_manifest_action_inconnue() -> None:
    """Un mot-clé d'action hors enum est refusé avec la liste des valides."""
    with pytest.raises(ManifestError, match="'action' inconnue 'supprime'"):
        parse_version_manifest(
            "vim",
            "1.0",
            """
files:
  - {source: a, action: supprime, target: ~/a}
""",
        )


def test_parse_manifest_fichiers_vides() -> None:
    """Un manifest sans fichier déclaré est refusé."""
    with pytest.raises(ManifestError, match="liste non vide"):
        parse_version_manifest("vim", "1.0", "files: []\n")


def test_parse_manifest_source_absolue_refusee() -> None:
    """Une source absolue ou contenant '..' est refusée (sécurité)."""
    with pytest.raises(ManifestError, match="chemin relatif"):
        parse_version_manifest(
            "vim",
            "1.0",
            """
files:
  - {source: /etc/passwd, action: copy, target: ~/a}
""",
        )
    with pytest.raises(ManifestError, match="chemin relatif"):
        parse_version_manifest(
            "vim",
            "1.0",
            """
files:
  - {source: "../../secret", action: copy, target: ~/a}
""",
        )


def test_parse_manifest_mode_invalide() -> None:
    """Un mode non octal est refusé."""
    with pytest.raises(ManifestError, match="'mode' doit être octal"):
        parse_version_manifest(
            "vim",
            "1.0",
            """
files:
  - {source: a, action: copy, target: ~/a, mode: "rwx"}
""",
        )
