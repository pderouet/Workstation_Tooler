"""Tests headless de l'orchestrateur UpdateEngine.

Le stockage repose sur le faux catalogue local (voir ``conftest.py``), la
détection et le bus d'événements sont remplacés par des doublures : aucune
connexion réseau, aucun sous-processus réel, aucun objet Qt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from engine.repository import RemoteRepository
from engine.update_engine import UpdateEngine

# ----------------------------------------------------------------------
# Doublures du socle (logger, bus, thread manager, détecteur).
# ----------------------------------------------------------------------


class RecordingSignal:
    """Signal factice qui enregistre ses émissions."""

    def __init__(self) -> None:
        self.calls: List[Tuple[Any, ...]] = []

    def emit(self, *args: Any) -> None:
        self.calls.append(args)


class FakeEventBus:
    """Bus factice exposant les signaux utilisés par le moteur."""

    def __init__(self) -> None:
        self.catalog_loaded = RecordingSignal()
        self.catalog_updates_available = RecordingSignal()
        self.update_available = RecordingSignal()
        self.module_status_changed = RecordingSignal()
        self.task_started = RecordingSignal()
        self.task_finished = RecordingSignal()


class FakeLogger:
    """Logger factice enregistrant les messages émis."""

    def __init__(self) -> None:
        self.messages: List[str] = []

    def _record(self, level: str, message: str) -> None:
        self.messages.append(f"{level}: {message}")

    def debug(self, message: str) -> None:
        self._record("DEBUG", message)

    def info(self, message: str) -> None:
        self._record("INFO", message)

    def warning(self, message: str) -> None:
        self._record("WARNING", message)

    def error(self, message: str) -> None:
        self._record("ERROR", message)

    def critical(self, message: str) -> None:
        self._record("CRITICAL", message)


class FakeThreadManager:
    """Thread manager factice exécutant la tâche immédiatement, sans thread."""

    def run_task(
        self,
        func: Callable[..., Any],
        *args: Any,
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
        **kwargs: Any,
    ) -> str:
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - doublure de test
            if on_error is not None:
                on_error(exc)
        else:
            if on_result is not None:
                on_result(result)
        return "task-fake"


def make_engine(
    repository: RemoteRepository,
    installed_by_binary: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple[UpdateEngine, FakeEventBus, FakeLogger, FakeThreadManager]:
    """Construit un moteur câblé sur des doublures complètes du socle.

    Args:
        repository: Repository du faux catalogue.
        installed_by_binary: Versions « installées » simulées, indexées par
            nom de binaire (valeur ``None`` = non installé).
    """
    versions = installed_by_binary or {}

    def fake_detector(detection: Any) -> Optional[str]:
        return versions.get(detection.binary)

    event_bus = FakeEventBus()
    logger = FakeLogger()
    thread_manager = FakeThreadManager()
    engine = UpdateEngine(
        logger=logger,  # type: ignore[arg-type]
        event_bus=event_bus,  # type: ignore[arg-type]
        thread_manager=thread_manager,  # type: ignore[arg-type]
        repository=repository,
        detector=fake_detector,
    )
    return engine, event_bus, logger, thread_manager


# ----------------------------------------------------------------------
# Catalogue et vérifications.
# ----------------------------------------------------------------------


def test_load_catalog_publie_les_applications_actives(repository: RemoteRepository) -> None:
    """Le chargement émet catalog_loaded avec les applications actives du partage."""
    engine, event_bus, *_ = make_engine(repository)
    engine.load_catalog()

    assert event_bus.catalog_loaded.calls == [
        (
            [
                {"name": "k9s", "display_name": "K9s"},
                {"name": "vim", "display_name": "Vim"},
            ],
        )
    ]


def test_check_updates_detecte_les_ecarts(repository: RemoteRepository) -> None:
    """Une version installée plus ancienne que la disponible déclenche l'événement groupé."""
    engine, event_bus, *_ = make_engine(
        repository, installed_by_binary={"vim": "9.1.0500", "k9s": "v0.50.0"}
    )
    status = engine.check_updates()

    assert status["updates_available"] == ["vim"]
    assert status["applications"]["vim"]["update_available"] is True
    assert status["applications"]["k9s"]["update_available"] is False
    # Un seul événement groupé, avec le libellé UI du catalogue.
    assert event_bus.catalog_updates_available.calls == [
        (
            [
                {
                    "name": "vim",
                    "display_name": "Vim",
                    "current": "9.1.0500",
                    "latest": "9.1.0700",
                }
            ],
        )
    ]
    # Le signal update_available est réservé à l'application elle-même.
    assert event_bus.update_available.calls == []


def test_check_updates_groupement_en_une_notification(repository: RemoteRepository) -> None:
    """Plusieurs mises à jour disponibles = UN seul événement les listant toutes."""
    engine, event_bus, *_ = make_engine(repository, installed_by_binary={"vim": "9.1.0500"})
    status = engine.check_updates()

    assert status["updates_available"] == ["k9s", "vim"]
    assert len(event_bus.catalog_updates_available.calls) == 1
    payload = event_bus.catalog_updates_available.calls[0][0]
    assert {entry["name"] for entry in payload} == {"k9s", "vim"}
    assert {entry["display_name"] for entry in payload} == {"K9s", "Vim"}


def test_check_updates_application_non_installee(repository: RemoteRepository) -> None:
    """Une application absente du poste est signalée comme mise à jour (installation)."""
    engine, event_bus, *_ = make_engine(repository, installed_by_binary={"vim": "9.1.0700"})
    status = engine.check_updates()

    assert status["updates_available"] == ["k9s"]
    payload = event_bus.catalog_updates_available.calls[0][0]
    assert payload == [
        {"name": "k9s", "display_name": "K9s", "current": "non installé", "latest": "v0.50.0"}
    ]
    assert event_bus.update_available.calls == []


def test_check_versions_ignoree_si_plus_recente_que_le_catalogue(
    repository: RemoteRepository,
) -> None:
    """Un poste plus récent que le catalogue n'est pas rétrogradé."""
    engine, event_bus, *_ = make_engine(
        repository, installed_by_binary={"vim": "9.2.0000", "k9s": "v0.99"}
    )
    status = engine.check_updates()
    assert status["updates_available"] == []
    assert event_bus.catalog_updates_available.calls == []


def test_check_updates_charge_le_catalogue_si_necessaire(repository: RemoteRepository) -> None:
    """La vérification charge le catalogue à la demande s'il n'est pas encore connu."""
    engine, event_bus, *_ = make_engine(repository, installed_by_binary={})
    status = engine.check_updates()
    assert set(status["applications"]) == {"vim", "k9s"}
    assert event_bus.catalog_loaded.calls  # émis par le chargement implicite


def test_check_updates_survit_a_un_detecteur_en_echec(repository: RemoteRepository) -> None:
    """Une commande de détection défaillante est dégradée, pas fatale."""

    def failing_detector(detection: Any) -> Optional[str]:
        raise OSError("binaire corrompu")

    logger = FakeLogger()
    engine = UpdateEngine(
        logger=logger,  # type: ignore[arg-type]
        event_bus=FakeEventBus(),  # type: ignore[arg-type]
        thread_manager=FakeThreadManager(),  # type: ignore[arg-type]
        repository=repository,
        detector=failing_detector,
    )
    status = engine.check_updates()
    assert set(status["applications"]) == {"vim", "k9s"}
    assert any("détection impossible" in message for message in logger.messages)


# ----------------------------------------------------------------------
# Mise à jour et reconfiguration.
# ----------------------------------------------------------------------


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    """Isole le HOME des tests : les cibles « ~/... » restent dans tmp_path."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def test_update_application_applique_le_manifest(
    repository: RemoteRepository, fake_home: Path
) -> None:
    """La mise à jour décompresse l'archive et applique le fragment de config."""
    engine, *_ = make_engine(repository, installed_by_binary={"vim": "9.1.0500"})
    progress: List[int] = []

    assert engine.update_application("vim", progress_callback=progress.append) is True

    extracted = fake_home / ".local" / "share" / "workstation_tooler-tests" / "vim" / "bin" / "vim"
    assert extracted.read_text(encoding="utf-8").startswith("#!/bin/sh")
    vimrc = fake_home / ".config" / "workstation_tooler-tests" / "vimrc"
    assert "demonstration Workstation Tooler" in vimrc.read_text(encoding="utf-8")
    assert progress == [50, 100]  # deux fichiers dans le manifest 9.1.0700.


def test_update_application_inconnue_ou_desactivee(repository: RemoteRepository) -> None:
    """Une application inconnue ou désactivée est refusée explicitement."""
    engine, *_ = make_engine(repository)
    with pytest.raises(ValueError, match="inconnue du catalogue"):
        engine.update_application("outil_fantome")
    with pytest.raises(ValueError, match="désactivée"):
        engine.update_application("disabled_tool")


def test_reconfigure_application_n_applique_que_ensure_content(
    repository: RemoteRepository, fake_home: Path
) -> None:
    """La reconfiguration crée le fragment de config mais ne déploie pas l'archive."""
    engine, event_bus, logger, *_ = make_engine(repository, installed_by_binary={})

    assert engine.reconfigure_application("vim") is True

    vimrc = fake_home / ".config" / "workstation_tooler-tests" / "vimrc"
    assert vimrc.exists()
    assert not (fake_home / ".local" / "share" / "workstation_tooler-tests").exists()
    assert not event_bus.update_available.calls


def test_reconfigure_utilise_la_version_installee(
    repository: RemoteRepository, fake_home: Path
) -> None:
    """La reconfiguration privilégie la version installée lorsqu'elle est au catalogue."""
    engine, _, logger, *_ = make_engine(repository, installed_by_binary={"vim": "9.1.0500"})

    assert engine.reconfigure_application("vim") is True
    assert any("reconfiguration depuis 9.1.0500" in m for m in logger.messages)


def test_update_all_met_a_jour_les_applications_obsoletes(
    repository: RemoteRepository, fake_home: Path
) -> None:
    """Toutes les applications obsolètes ou absentes sont traitées séquentiellement."""
    engine, *_ = make_engine(repository, installed_by_binary={"vim": "9.1.0500", "k9s": None})
    progress: List[int] = []

    results = engine.update_all(progress_callback=progress.append)

    assert results == {"vim": True, "k9s": True}
    k9s_extracted = fake_home / ".local" / "share" / "workstation_tooler-tests" / "k9s" / "k9s"
    assert k9s_extracted.exists()
    assert progress == [50, 100]  # une étape par application mise à jour.


def test_update_all_sans_aucune_mise_a_jour(repository: RemoteRepository) -> None:
    """Aucune application obsolète : rien à faire, résultat vide."""
    engine, *_ = make_engine(repository, installed_by_binary={"vim": "9.1.0700", "k9s": "v0.50.0"})
    assert engine.update_all() == {}


# ----------------------------------------------------------------------
# Déclenchement asynchrone.
# ----------------------------------------------------------------------


def test_start_check_updates_passe_par_le_thread_manager(
    repository: RemoteRepository,
) -> None:
    """Les wrappers start_* publient le cycle de tâche et restituent le résultat."""
    engine, event_bus, *_ = make_engine(repository, installed_by_binary={"vim": "9.1.0700"})
    results: List[Any] = []
    errors: List[Exception] = []

    engine.start_check_updates(on_result=results.append, on_error=errors.append)

    assert not errors
    assert results and results[0]["updates_available"] == ["k9s"]
    assert event_bus.task_started.calls == [("engine.catalogue.verification",)]
    assert event_bus.task_finished.calls == [("engine.catalogue.verification",)]


def test_start_update_application_publie_les_bons_noms_de_tache(
    repository: RemoteRepository, fake_home: Path
) -> None:
    """La tâche de mise à jour d'une application est nommée d'après celle-ci."""
    engine, event_bus, *_ = make_engine(repository, installed_by_binary={"vim": None})
    results: List[bool] = []

    engine.start_update_application("vim", on_result=results.append)

    assert results == [True]
    assert event_bus.task_started.calls == [("engine.vim.mise_a_jour",)]
    assert event_bus.module_status_changed.calls == [("vim", "mise_a_jour")]


def test_start_propage_les_erreurs_au_callback(repository: RemoteRepository) -> None:
    """Une exception dans la tâche remonte via on_error après clôture de la tâche."""
    engine, event_bus, *_ = make_engine(repository)
    errors: List[Exception] = []

    engine.start_update_application("inconnu", on_error=errors.append)

    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    assert event_bus.task_finished.calls == [("engine.inconnu.mise_a_jour",)]
