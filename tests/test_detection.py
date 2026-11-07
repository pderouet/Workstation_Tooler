"""Tests headless de la détection de version installée (exécuteur injecté)."""

from __future__ import annotations

import subprocess
import sys

from engine.detection import _default_command_output, detect_installed_version, resolve_binary
from engine.models import VersionDetection

VIM_STDOUT = "VIM - Vi IMproved 9.1\npatches 1-1234\n"


def make_detection(**overrides: object) -> VersionDetection:
    """Construit une déclaration de détection avec valeurs par défaut surchargeables."""
    values: dict[str, object] = {
        "binary": "vim",
        "pattern": r"Vi IMproved (\S+)",
        "args": ("--version",),
        "fallback_binary": "",
        "timeout_seconds": 5,
    }
    values.update(overrides)
    return VersionDetection(**values)  # type: ignore[arg-type]


def test_extraction_avec_groupe_capturant() -> None:
    """Le premier groupe du motif fournit la version."""
    version = detect_installed_version(make_detection(), command_output=lambda *_args: VIM_STDOUT)
    assert version == "9.1"


def test_extraction_sans_groupe_retourne_la_correspondance() -> None:
    """Sans groupe, la correspondance entière est la version."""
    detection = make_detection(pattern=r"\d+\.\d+")
    version = detect_installed_version(detection, command_output=lambda *_a: VIM_STDOUT)
    assert version == "9.1"


def test_motif_sans_correspondance_retourne_none() -> None:
    """Sans correspondance dans la sortie, la version est indéterminée."""
    version = detect_installed_version(
        make_detection(), command_output=lambda *_a: "un outil inconnu v?\n"
    )
    assert version is None


def test_binaire_introuvable_retourne_none(monkeypatch) -> None:
    """Un binaire absent du PATH (avec ou sans repli) rend la détection impossible."""
    monkeypatch.setattr("engine.detection.shutil.which", lambda _name: None)
    assert resolve_binary(make_detection()) is None
    assert detect_installed_version(make_detection()) is None


def test_binaire_de_repli_utilise(monkeypatch) -> None:
    """Le binaire de remplacement est utilisé si le principal est introuvable."""
    monkeypatch.setattr(
        "engine.detection.shutil.which",
        lambda name: f"/usr/bin/{name}" if name == "powershell" else None,
    )
    seen: dict[str, object] = {}

    def fake_output(binary: str, args: list[str], timeout: int) -> str:
        seen["binary"] = binary
        return "PowerShell 7.4.1\n"

    detection = make_detection(
        binary="pwsh", fallback_binary="powershell", pattern=r"PowerShell (\S+)"
    )
    version = detect_installed_version(detection, command_output=fake_output)
    assert version == "7.4.1"
    assert seen["binary"] == "powershell"


def test_runner_par_defaut_execute_un_vrai_sous_processus() -> None:
    """Le runner réel exécute la commande et capture la sortie standard."""
    stdout = _default_command_output(sys.executable, ["-c", "print('7.4.1')"], timeout_seconds=10)
    assert "7.4.1" in stdout


def test_runner_par_defaut_propage_les_erreurs() -> None:
    """Un délai trop court fait remonter l'exception plutôt qu'un None silencieux."""
    try:
        _default_command_output(sys.executable, ["-c", "import time; time.sleep(5)"], 1)
    except subprocess.SubprocessError:
        pass
    else:
        raise AssertionError("TimeoutExpired attendu")
