"""Fixtures partagées : catalogue factice monté sur un système de fichiers local.

Le faux partage reproduit l'agencement documenté du catalogue (un dossier par
application, un ``app.yaml``, un dossier par version avec ``manifest.yaml``)
sans aucune dépendance réseau ni Qt.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from engine.repository import RemoteRepository
from engine.storage import LocalStorageBackend

APP_VIM_YAML = """\
application: vim
display_name: Vim
enabled: true
version_detection:
  binary: vim
  args: ["--version"]
  pattern: 'Vi IMproved (\\S+)'
"""

MANIFEST_VIM_0500 = """\
version: "9.1.0500"
files:
  - source: vim-9.1.0500.tar.gz
    action: decompress
    target: "~/.local/share/workstation_tooler-tests/vim"
"""

MANIFEST_VIM_0700 = """\
version: "9.1.0700"
files:
  - source: vim-9.1.0700.tar.gz
    action: decompress
    target: "~/.local/share/workstation_tooler-tests/vim"
  - source: vimrc.fragment
    action: ensure_content
    target: "~/.config/workstation_tooler-tests/vimrc"
"""

APP_K9S_YAML = """\
application: k9s
display_name: K9s
enabled: true
version_detection:
  binary: k9s
  args: ["version", "--short"]
  pattern: 'Version\\D*(v[\\d.]+)'
"""

MANIFEST_K9S = """\
version: "v0.50.0"
files:
  - source: k9s_Linux_amd64.tar.gz
    action: decompress
    target: "~/.local/share/workstation_tooler-tests/k9s"
"""

APP_BROKEN_YAML = """\
application: broken
champ_inconnu: true
version_detection:
  binary: broken
  pattern: '(\\S+)'
"""

APP_DISABLED_YAML = """\
application: disabled_tool
display_name: Outil désactivé
enabled: false
version_detection:
  binary: disabled_tool
  pattern: '(\\S+)'
"""

MANIFEST_DISABLED = """\
files:
  - source: outil.txt
    action: copy
    target: "~/.local/share/workstation_tooler-tests/disabled_tool.txt"
"""


def _write_targz(path: Path, members: dict[str, bytes]) -> None:
    """Écrit une véritable archive tar.gz (extractible) avec les membres fournis."""
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def build_fake_share(root: Path) -> Path:
    """Construit le contenu du faux catalogue sous ``root`` et le retourne.

    Applications créées :
        - ``vim`` : deux versions (9.1.0500, 9.1.0700) + un dossier de version
          sans manifest (ignoré) ;
        - ``k9s`` : une version ``v0.50.0`` ;
        - ``broken_tool`` : app.yaml invalide (clé inconnue) ;
        - ``disabled_tool`` : application valide mais désactivée ;
        - ``no_versions_tool`` : aucune version déclarée ;
        - un fichier parasite à la racine (ignoré).
    """
    vim = root / "vim"
    (vim / "9.1.0500").mkdir(parents=True)
    (vim / "9.1.0700").mkdir(parents=True)
    (vim / "9.0.0000").mkdir(parents=True)  # dossier sans manifest : pas une version.
    (vim / "app.yaml").write_text(APP_VIM_YAML, encoding="utf-8")
    (vim / "9.1.0500" / "manifest.yaml").write_text(MANIFEST_VIM_0500, encoding="utf-8")
    _write_targz(
        vim / "9.1.0500" / "vim-9.1.0500.tar.gz",
        {"bin/vim": b"#!/bin/sh\necho vim factice 9.1.0500\n"},
    )
    (vim / "9.1.0700" / "manifest.yaml").write_text(MANIFEST_VIM_0700, encoding="utf-8")
    _write_targz(
        vim / "9.1.0700" / "vim-9.1.0700.tar.gz",
        {"bin/vim": b"#!/bin/sh\necho vim factice 9.1.0700\n"},
    )
    (vim / "9.1.0700" / "vimrc.fragment").write_text(
        '" demonstration Workstation Tooler\n', encoding="utf-8"
    )

    k9s = root / "k9s"
    (k9s / "v0.50.0").mkdir(parents=True)
    (k9s / "app.yaml").write_text(APP_K9S_YAML, encoding="utf-8")
    (k9s / "v0.50.0" / "manifest.yaml").write_text(MANIFEST_K9S, encoding="utf-8")
    _write_targz(
        k9s / "v0.50.0" / "k9s_Linux_amd64.tar.gz",
        {"k9s": b"binaire k9s factice v0.50.0\n"},
    )

    broken = root / "broken_tool"
    broken.mkdir(parents=True)
    (broken / "app.yaml").write_text(APP_BROKEN_YAML, encoding="utf-8")

    disabled = root / "disabled_tool"
    (disabled / "1.0.0").mkdir(parents=True)
    (disabled / "app.yaml").write_text(APP_DISABLED_YAML, encoding="utf-8")
    (disabled / "1.0.0" / "manifest.yaml").write_text(MANIFEST_DISABLED, encoding="utf-8")
    (disabled / "1.0.0" / "outil.txt").write_text("outil désactivé\n", encoding="utf-8")

    no_versions = root / "no_versions_tool"
    no_versions.mkdir(parents=True)
    (no_versions / "app.yaml").write_text(
        APP_VIM_YAML.replace("application: vim", "application: no_versions_tool"),
        encoding="utf-8",
    )

    (root / "README.txt").write_text("fichier parasite à la racine\n", encoding="utf-8")
    return root


@pytest.fixture
def share_root(tmp_path: Path) -> Path:
    """Fournit un faux catalogue complet dans un répertoire temporaire."""
    return build_fake_share(tmp_path / "partage")


@pytest.fixture
def repository(share_root: Path) -> RemoteRepository:
    """Fournit un RemoteRepository branché sur le faux catalogue local."""
    return RemoteRepository(LocalStorageBackend(share_root.as_uri()))
