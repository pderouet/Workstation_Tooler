"""Tests headless de l'AppUpdater : versions, forges HTTP, report d'exécution.

Aucun accès réseau : les ouvreur d'URL sont remplacés par des doublures.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from core import app_updater as app_updater_module
from core.app_updater import (
    GITLAB_READ_TOKEN,
    AppUpdater,
    fetch_latest_version_github,
    fetch_latest_version_gitlab,
    github_archive_url,
    github_read_token,
    gitlab_archive_url,
    gitlab_read_token,
    read_current_version,
)


class FakeResponse:
    """Réponse HTTP factice : source binaire avec fin de fichier (read par blocs)."""

    def __init__(self, body: bytes) -> None:
        self._remaining = body

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            data, self._remaining = self._remaining, b""
        else:
            data, self._remaining = self._remaining[:size], self._remaining[size:]
        return data

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


def capture_opener(body: bytes) -> Tuple[Any, Dict[str, Any]]:
    """Construit un ouvreur factice retournant ``body`` et capturant la requête."""
    captured: Dict[str, Any] = {}

    def opener(request: Any, timeout: int) -> FakeResponse:
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["timeout"] = timeout
        return FakeResponse(body)

    return opener, captured


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
# Fournisseur GitHub (HTTP, fichier brut raw).
# ----------------------------------------------------------------------


def test_fetch_latest_version_github_requete_anonyme() -> None:
    """L'URL vise le fichier brut de la branche, sans authentification (dépôt public)."""
    opener, captured = capture_opener(b"0.4.7\n")
    version = fetch_latest_version_github("pderouet/Workstation_Tooler", "main", opener=opener)

    assert version == "0.4.7"
    assert captured["url"] == (
        "https://raw.githubusercontent.com/pderouet/Workstation_Tooler/main/version.txt"
    )
    assert "authorization" not in captured["headers"]


def test_fetch_latest_version_github_avec_token_prive() -> None:
    """Un jeton fourni part en Authorization: Bearer (dépôt redevenu privé)."""
    opener, captured = capture_opener(b"0.4.8\n")
    version = fetch_latest_version_github(
        "pderouet/Workstation_Tooler", "main", token="jeton-gh", opener=opener
    )

    assert version == "0.4.8"
    assert captured["headers"].get("authorization") == "Bearer jeton-gh"


def test_fetch_latest_version_github_contenu_invalide() -> None:
    """Un version.txt distant mal formé lève une ValueError explicite."""
    opener, _captured = capture_opener(b"pas-une-version")
    with pytest.raises(ValueError, match="invalide"):
        fetch_latest_version_github("pderouet/Workstation_Tooler", "main", opener=opener)


def test_fetch_latest_version_github_depot_mal_forme() -> None:
    """Un dépôt sans « propriétaire/dépôt » est refusé avant toute requête."""
    with pytest.raises(ValueError, match="dépôt GitHub mal formé"):
        fetch_latest_version_github("workstation_tooler", "main")


# ----------------------------------------------------------------------
# Fournisseur GitLab (API v4, PRIVATE-TOKEN).
# ----------------------------------------------------------------------


def test_fetch_latest_version_gitlab_requete_et_resultat() -> None:
    """La requête vise l'API raw du fichier avec ref=branche et PRIVATE-TOKEN."""
    opener, captured = capture_opener(b"1.0.3\n")
    version = fetch_latest_version_gitlab(
        "https://gitlab.example.com/", "42", "release/1.x", "tok", opener=opener
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
# Jetons (variables d'environnement prioritaires).
# ----------------------------------------------------------------------


def test_gitlab_read_token_variable_environnement_prioritaire(monkeypatch) -> None:
    """La variable d'environnement prime sur la constante (dépôt public)."""
    monkeypatch.delenv("WORKSTATION_TOOLER_GITLAB_TOKEN", raising=False)
    assert gitlab_read_token() == GITLAB_READ_TOKEN  # repli sur la constante.

    monkeypatch.setenv("WORKSTATION_TOOLER_GITLAB_TOKEN", "jeton-env")
    assert gitlab_read_token() == "jeton-env"


def test_github_read_token_optionnel(monkeypatch) -> None:
    """Le jeton GitHub est purement optionnel (dépôt public par défaut)."""
    monkeypatch.delenv("WORKSTATION_TOOLER_GITHUB_TOKEN", raising=False)
    assert github_read_token() == ""

    monkeypatch.setenv("WORKSTATION_TOOLER_GITHUB_TOKEN", "jeton-gh")
    assert github_read_token() == "jeton-gh"


# ----------------------------------------------------------------------
# URL d'archives de déploiement.
# ----------------------------------------------------------------------


def test_url_archive_github() -> None:
    """L'archive GitHub passe par l'API tarball de la branche."""
    assert github_archive_url("pderouet/Workstation_Tooler", "main") == (
        "https://api.github.com/repos/pderouet/Workstation_Tooler/tarball/main"
    )


def test_url_archive_gitlab_sans_jet_dans_l_url() -> None:
    """L'archive GitLab passe par l'API v4 : aucun jeton dans l'URL."""
    assert gitlab_archive_url("https://gitlab.example.com/", "42", "dev") == (
        "https://gitlab.example.com/api/v4/projects/42/repository/archive.tar.gz?sha=dev"
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

GITHUB_SETTINGS: Dict[str, Any] = {
    "github": {"repository": "pderouet/Workstation_Tooler"},
    "forge": {"provider": "github", "github": {"branch": "main"}},
}
GITLAB_SETTINGS: Dict[str, Any] = {
    "github": {"repository": "pderouet/Workstation_Tooler"},
    "forge": {
        "provider": "gitlab",
        "gitlab": {"base_url": "https://gitlab.example.com", "project_id": "42", "branch": "dev"},
    },
}


def prepare_launcher(
    monkeypatch, tmp_path: Path, settings: Dict[str, Any]
) -> Tuple[AppUpdater, List[Dict[str, Any]], Any]:
    """Prépare un environnement de lancement factice (updater.py + config + spawn)."""
    (tmp_path / "updater.py").write_text("# script factice\n", encoding="utf-8")
    monkeypatch.setattr(app_updater_module, "PROJECT_ROOT", tmp_path)

    updater = AppUpdater()
    monkeypatch.setattr(updater, "_config", FakeConfig(settings))

    spawned: List[Dict[str, Any]] = []

    def fake_spawn(arguments: List[str], **kwargs: Any) -> None:
        spawned.append({"args": list(arguments), "kwargs": kwargs})

    return updater, spawned, fake_spawn


def run_fake_update(monkeypatch, tmp_path: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Lance perform_update avec un spawn factice et retourne la capture du lancement."""
    updater, spawned, fake_spawn = prepare_launcher(monkeypatch, tmp_path, settings)
    assert updater.perform_update(spawn=fake_spawn) is True
    return spawned[0]


def test_perform_update_lance_updater_avec_url_archive_github(monkeypatch, tmp_path: Path) -> None:
    """L'updater reçoit le PID et l'URL d'archive GitHub (aucun jeton en argument)."""
    launcher = run_fake_update(monkeypatch, tmp_path, GITHUB_SETTINGS)
    args = launcher["args"]

    assert args[0] == sys.executable
    assert str(os.getpid()) in args
    assert "--app-dir" in args and str(tmp_path) in args
    assert "--provider" in args and "github" in args
    url = args[args.index("--archive-url") + 1]
    assert url == "https://api.github.com/repos/pderouet/Workstation_Tooler/tarball/main"
    assert "--no-relaunch" not in args
    if os.name == "nt":
        assert launcher["kwargs"]["creationflags"]
    else:
        assert launcher["kwargs"]["start_new_session"] is True


def test_perform_update_url_archive_gitlab(monkeypatch, tmp_path: Path) -> None:
    """Le fournisseur GitLab produit l'URL d'archive API v4 correspondante."""
    launcher = run_fake_update(monkeypatch, tmp_path, GITLAB_SETTINGS)
    args = launcher["args"]
    url = args[args.index("--archive-url") + 1]
    assert url == (
        "https://gitlab.example.com/api/v4/projects/42/repository/archive.tar.gz?sha=dev"
    )
    assert "gitlab" in args


def test_perform_update_sans_relaunch_quand_desactive(monkeypatch, tmp_path: Path) -> None:
    """update.app_auto_restart: false ajoute --no-relaunch."""
    settings = dict(GITHUB_SETTINGS)
    settings["update"] = {"app_auto_restart": False}
    launcher = run_fake_update(monkeypatch, tmp_path, settings)
    assert "--no-relaunch" in launcher["args"]


def test_perform_update_script_absent(monkeypatch, tmp_path: Path) -> None:
    """L'absence d'updater.py lève une erreur explicite (routée vers ErrorHandler)."""
    monkeypatch.setattr(app_updater_module, "PROJECT_ROOT", tmp_path)
    updater = AppUpdater()
    monkeypatch.setattr(updater, "_config", FakeConfig(GITHUB_SETTINGS))
    with pytest.raises(FileNotFoundError, match="updater.py"):
        updater.perform_update(spawn=lambda *_a, **_k: None)
