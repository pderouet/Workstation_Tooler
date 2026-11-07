"""Tests headless de l'AppUpdater : versions, fournisseurs, report d'exécution.

Aucun accès réseau ni Git réel : les exécuteurs de commandes et l'ouvreur
d'URL sont remplacés par des doublures.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from core import app_updater as app_updater_module
from core.app_updater import (
    AppUpdater,
    fetch_latest_version_github,
    fetch_latest_version_gitlab,
    read_current_version,
)


class FakeResponse:
    """Réponse HTTP factice (gestionnaire de contexte + lecture)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


def make_recording_bus() -> Any:
    """Construit une doublure d'EventBus n'exposant que update_available."""
    calls: List[Tuple[str, str, str]] = []

    class Signal:
        def emit(self, *args: Any) -> None:
            calls.append(args)

    class Bus:
        update_available = Signal()

    return Bus(), calls


class FakeConfig:
    """ConfigLoader factice sur un dictionnaire de clés à points."""

    def __init__(self, settings: Dict[str, Any]) -> None:
        self._settings = settings

    def get_setting(self, dotted_key: str, default: Any = None) -> Any:
        current: Any = self._settings
        for part in dotted_key.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current


# ----------------------------------------------------------------------
# Lecture de la version locale.
# ----------------------------------------------------------------------


def test_read_current_version_valide(tmp_path: Path) -> None:
    """Une version bien formée est lue et nettoyée."""
    version_file = tmp_path / "version.txt"
    version_file.write_text("1.2.3\n", encoding="utf-8")
    assert read_current_version(version_file) == "1.2.3"


@pytest.mark.parametrize("contenu", ["abc", "1.2", "1.2.3.4", "", "v1.2.3"])
def test_read_current_version_invalide(tmp_path: Path, contenu: str) -> None:
    """Un contenu non conforme à x.y.z est rejeté (None)."""
    version_file = tmp_path / "version.txt"
    version_file.write_text(contenu, encoding="utf-8")
    assert read_current_version(version_file) is None


def test_read_current_version_absent(tmp_path: Path) -> None:
    """Un fichier absent retourne None sans lever."""
    assert read_current_version(tmp_path / "inconnu.txt") is None


# ----------------------------------------------------------------------
# Fournisseur GitHub (git fetch + git show).
# ----------------------------------------------------------------------


def test_fetch_latest_version_github_commandes_et_resultat() -> None:
    """Le fournisseur GitHub enchaîne fetch puis show et valide la version."""
    commands: List[List[str]] = []

    def fake_runner(command: List[str], **_kwargs: Any) -> subprocess.CompletedProcess:
        commands.append(list(command))
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="0.4.7\n")

    version = fetch_latest_version_github(Path("/opt/app"), "main", runner=fake_runner)

    assert version == "0.4.7"
    assert commands[0][:4] == ["git", "-C", "/opt/app", "fetch"]
    assert commands[0][-1] == "main"
    assert "FETCH_HEAD:version.txt" in commands[1]


def test_fetch_latest_version_github_contenu_invalide() -> None:
    """Un version.txt distant mal formé lève une ValueError explicite."""

    def fake_runner(_command: List[str], **_kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="pas-une-version")

    with pytest.raises(ValueError, match="invalide"):
        fetch_latest_version_github(Path("/opt/app"), "main", runner=fake_runner)


def test_fetch_latest_version_github_erreur_git_propagee() -> None:
    """Une erreur Git remonte à l'appelant (journalisation par AppUpdater)."""

    def fake_runner(_command: List[str], **_kwargs: Any) -> subprocess.CompletedProcess:
        raise subprocess.CalledProcessError(returncode=128, cmd="git")

    with pytest.raises(subprocess.CalledProcessError):
        fetch_latest_version_github(Path("/opt/app"), "main", runner=fake_runner)


# ----------------------------------------------------------------------
# Fournisseur GitLab (API v4, PRIVATE-TOKEN).
# ----------------------------------------------------------------------


def test_fetch_latest_version_gitlab_requete_et_resultat() -> None:
    """La requête vise l'API raw du fichier avec ref=branche et PRIVATE-TOKEN."""
    captured: Dict[str, Any] = {}

    def fake_opener(request: Any, timeout: int) -> FakeResponse:
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["timeout"] = timeout
        return FakeResponse(b"1.0.3\n")

    version = fetch_latest_version_gitlab(
        "https://gitlab.example.com/", "42", "release/1.x", "tok", opener=fake_opener
    )

    assert version == "1.0.3"
    assert captured["url"] == (
        "https://gitlab.example.com/api/v4/projects/42"
        "/repository/files/version.txt/raw?ref=release%2F1.x"
    )
    assert captured["headers"].get("private-token") == "tok"


def test_fetch_latest_version_gitlab_contenu_invalide() -> None:
    """Un contenu mal formé lève une ValueError explicite."""
    with pytest.raises(ValueError, match="invalide"):
        fetch_latest_version_gitlab(
            "https://gitlab.example.com",
            "42",
            "main",
            "tok",
            opener=lambda _r, timeout=10: FakeResponse(b"??"),
        )


@pytest.mark.parametrize("project_id,token", [("", "tok"), ("42", "")])
def test_fetch_latest_version_gitlab_configuration_incomplete(project_id: str, token: str) -> None:
    """Un ID de projet ou un token manquant est refusé avant toute requête."""
    with pytest.raises(ValueError, match="configuration GitLab incomplète"):
        fetch_latest_version_gitlab(
            "https://gitlab.example.com",
            project_id,
            "main",
            token,
            opener=lambda _r, timeout=10: FakeResponse(b"1.0.0"),
        )


# ----------------------------------------------------------------------
# check_update et report « Pas aujourd'hui ».
# ----------------------------------------------------------------------


def configure_updater(
    monkeypatch, current: Optional[str], latest: Optional[str]
) -> Tuple[AppUpdater, List[Tuple[str, str, str]]]:
    """Prépare le singleton AppUpdater avec versions et bus factices."""
    updater = AppUpdater()
    monkeypatch.setattr(updater, "get_current_version", lambda: current)
    monkeypatch.setattr(updater, "get_latest_version", lambda: latest)
    bus, calls = make_recording_bus()
    monkeypatch.setattr(updater, "_event_bus", bus)
    return updater, calls


def test_check_update_detecte_ecart(monkeypatch) -> None:
    """Une version locale plus ancienne déclenche update_available."""
    updater, calls = configure_updater(monkeypatch, "0.4.6", "0.4.7")
    status = updater.check_update()
    assert status["update_available"] is True
    assert status["dismissed"] is False
    assert calls == [("app", "0.4.6", "0.4.7")]


def test_check_update_a_jour_et_pas_de_retrogradage(monkeypatch) -> None:
    """Ni version identique, ni poste plus récent : aucune proposition."""
    updater, calls = configure_updater(monkeypatch, "0.4.7", "0.4.7")
    assert updater.check_update()["update_available"] is False

    updater, calls = configure_updater(monkeypatch, "0.5.0", "0.4.7")
    assert updater.check_update()["update_available"] is False
    assert calls == []


def test_check_update_version_indisponible(monkeypatch) -> None:
    """Sans version distante (réseau/forge indisponible), aucune proposition."""
    updater, calls = configure_updater(monkeypatch, "0.4.7", None)
    status = updater.check_update()
    assert status["update_available"] is False
    assert status["latest_version"] is None
    assert calls == []


def test_report_masque_la_proposition_pour_cette_execution(monkeypatch) -> None:
    """« Pas aujourd'hui » suspend l'émission jusqu'à l'arrêt du programme."""
    updater, calls = configure_updater(monkeypatch, "0.4.6", "0.4.7")
    updater.dismiss_update()

    status = updater.check_update()
    assert status["update_available"] is True  # écart réel conservé (manuel possible)
    assert status["dismissed"] is True
    assert calls == []  # aucune notification automatique.


def test_le_report_disparait_au_redemarrage(monkeypatch) -> None:
    """Un redémarrage (nouvel état interne) repose la question."""
    updater, calls = configure_updater(monkeypatch, "0.4.6", "0.4.7")
    updater.dismiss_update()
    assert updater.check_update()["dismissed"] is True

    # Simulation d'un nouveau processus : état d'exécution réinitialisé.
    updater._update_dismissed = False
    assert updater.check_update()["dismissed"] is False
    assert calls == [("app", "0.4.6", "0.4.7")]


# ----------------------------------------------------------------------
# perform_update : lancement de updater.py.
# ----------------------------------------------------------------------


def test_perform_update_lance_updater_avec_pid_et_options(monkeypatch, tmp_path: Path) -> None:
    """L'updater est lancé détaché avec le PID et les options de déploiement."""
    (tmp_path / "updater.py").write_text("# script factice\n", encoding="utf-8")
    monkeypatch.setattr(app_updater_module, "PROJECT_ROOT", tmp_path)
    updater = AppUpdater()
    monkeypatch.setattr(
        updater,
        "_config",
        FakeConfig({"forge": {"provider": "github", "github": {"branch": "main"}}}),
    )
    spawned: List[Dict[str, Any]] = []

    def fake_spawn(arguments: List[str], **kwargs: Any) -> None:
        spawned.append({"args": list(arguments), "kwargs": kwargs})

    assert updater.perform_update(spawn=fake_spawn) is True

    args = spawned[0]["args"]
    assert args[0] == sys.executable
    assert str(os.getpid()) in args
    assert "--app-dir" in args and str(tmp_path) in args
    assert "--provider" in args and "github" in args
    assert "--branch" in args and "main" in args
    assert "--no-relaunch" not in args
    # Détachement selon la plateforme.
    if os.name == "nt":
        assert spawned[0]["kwargs"]["creationflags"]
    else:
        assert spawned[0]["kwargs"]["start_new_session"] is True


def test_perform_update_sans_relaunch_quand_desactive(monkeypatch, tmp_path: Path) -> None:
    """update.app_auto_restart: false ajoute --no-relaunch."""
    (tmp_path / "updater.py").write_text("# script factice\n", encoding="utf-8")
    monkeypatch.setattr(app_updater_module, "PROJECT_ROOT", tmp_path)
    updater = AppUpdater()
    monkeypatch.setattr(
        updater,
        "_config",
        FakeConfig(
            {
                "forge": {"provider": "gitlab", "gitlab": {"branch": "dev"}, "github": {}},
                "update": {"app_auto_restart": False},
            }
        ),
    )
    spawned: List[Dict[str, Any]] = []

    def fake_spawn(arguments: List[str], **kwargs: Any) -> None:
        spawned.append({"args": list(arguments), "kwargs": kwargs})

    assert updater.perform_update(spawn=fake_spawn) is True
    assert "--no-relaunch" in spawned[0]["args"]


def test_perform_update_script_absent(monkeypatch, tmp_path: Path) -> None:
    """L'absence d'updater.py lève une erreur explicite (routée vers ErrorHandler)."""
    monkeypatch.setattr(app_updater_module, "PROJECT_ROOT", tmp_path)
    updater = AppUpdater()
    monkeypatch.setattr(updater, "_config", FakeConfig({}))
    with pytest.raises(FileNotFoundError, match="updater.py"):
        updater.perform_update(spawn=lambda *_a, **_k: None)
