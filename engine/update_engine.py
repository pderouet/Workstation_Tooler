"""Orchestrateur du moteur de mise à jour piloté par le catalogue distant.

L'``UpdateEngine`` est le pendant des anciens modules : unique, il découvre les
applications depuis le chemin réseau, compare les versions installées aux
versions disponibles, puis télécharge et applique les actions déclarées dans
les manifests (``copy`` / ``decompress`` / ``ensure_content``).

Conformément aux règles du projet :
    - toute méthode ``*`` bloquante (réseau, sous-processus, fichiers) est
      destinée à être exécutée en tâche de fond via les wrappers ``start_*``,
      qui délèguent au ``ThreadManager`` ;
    - l'UI est informée exclusivement via l'``EventBus`` ;
    - les exceptions sont propagées aux callbacks ``on_error`` des wrappers,
      à router vers l'``ErrorHandler`` centralisé.
"""

from __future__ import annotations

import subprocess
import tempfile
import threading
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.event_bus import EventBus
from core.logger import Logger
from core.thread_manager import ThreadManager
from engine.actions import execute_file_action
from engine.catalog import CatalogLoader
from engine.detection import detect_installed_version
from engine.models import (
    ActionKind,
    Application,
    Catalog,
    FileAction,
    VersionDetection,
    VersionManifest,
)
from engine.repository import RemoteRepository
from engine.version import compare_versions

#: Fonction de rappel de progression (pourcentage 0-100).
ProgressCallback = Callable[[int], None]

#: Fonction de détection de version installée, injectable pour les tests.
VersionDetector = Callable[[VersionDetection], Optional[str]]


class UpdateEngine:
    """Moteur unique de vérification et de mise à jour des applications gérées."""

    def __init__(
        self,
        logger: Logger,
        event_bus: EventBus,
        thread_manager: ThreadManager,
        repository: RemoteRepository,
        detector: VersionDetector = detect_installed_version,
    ) -> None:
        """Initialise le moteur sur le socle applicatif et le repository distant.

        Args:
            logger: Logger applicatif (thread-safe).
            event_bus: Bus d'événements vers l'UI.
            thread_manager: Gestionnaire de tâches de fond.
            repository: Accès structuré au catalogue distant.
            detector: Fonction de détection de version installée, injectable
                pour les tests.
        """
        self._logger = logger
        self._event_bus = event_bus
        self._thread_manager = thread_manager
        self._repository = repository
        self._detector = detector

        self._catalog: Optional[Catalog] = None
        self._manifest_cache: Dict[Tuple[str, str], VersionManifest] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Catalogue des applications.
    # ------------------------------------------------------------------

    def load_catalog(self) -> Catalog:
        """Charge le catalogue des applications depuis le chemin réseau.

        Bloquant (I/O réseau) : à exécuter via :meth:`start_load_catalog`.
        Les applications mal déclarées sont ignorées et journalisées ; un
        chemin réseau inaccessible, en revanche, lève une ``OSError``.

        Returns:
            Le catalogue chargé.

        Raises:
            OSError: Si la racine du catalogue est inaccessible.
        """
        catalog = CatalogLoader(self._repository).load()
        with self._lock:
            self._catalog = catalog
            self._manifest_cache.clear()

        for name, reason in catalog.skipped.items():
            self._logger.warning(f"[moteur] application '{name}' ignorée : {reason}")

        self._event_bus.catalog_loaded.emit(
            [
                {"name": app.metadata.name, "display_name": app.metadata.display_name}
                for app in catalog.enabled_applications()
            ]
        )
        enabled = ", ".join(app.metadata.name for app in catalog.enabled_applications())
        self._logger.info(f"[moteur] catalogue chargé : applications actives = [{enabled}]")
        return catalog

    def _ensure_catalog(self) -> Catalog:
        """Retourne le catalogue courant, en le chargeant s'il ne l'est pas encore."""
        if self._catalog is None:
            return self.load_catalog()
        return self._catalog

    def _get_manifest(self, application: str, version: str) -> VersionManifest:
        """Charge (et met en cache) le manifest d'une version donnée."""
        key = (application, version)
        with self._lock:
            manifest = self._manifest_cache.get(key)
            if manifest is None:
                manifest = self._repository.load_manifest(application, version)
                self._manifest_cache[key] = manifest
            return manifest

    # ------------------------------------------------------------------
    # Vérifications de mises à jour.
    # ------------------------------------------------------------------

    def check_updates(self, progress_callback: Optional[ProgressCallback] = None) -> Dict[str, Any]:
        """Compare, pour chaque application active, la version installée à la plus récente.

        Bloquant (réseau + sous-processus) : à exécuter via
        :meth:`start_check_updates`. Les mises à jour détectées sont publiées
        en UN SEUL événement ``catalog_updates_available`` (notification
        groupée) ; le signal ``update_available`` reste réservé à la mise à
        jour de l'application elle-même.

        Args:
            progress_callback: Fonction optionnelle rappelée avec le
                pourcentage d'avancement (une étape par application).

        Returns:
            Un récapitulatif ``{"applications": {<nom>: statut}, "updates_available": [noms]}``.
        """
        catalog = self._ensure_catalog()
        applications = catalog.enabled_applications()

        results: Dict[str, Dict[str, Any]] = {}
        updates_available: List[Dict[str, str]] = []
        for index, app in enumerate(applications):
            name = app.metadata.name
            current = self._detect_installed(app)
            latest = app.latest_version

            update_available = latest is not None and (
                current is None or compare_versions(current, latest) < 0
            )
            results[name] = {
                "current_version": current,
                "latest_version": latest,
                "update_available": update_available,
            }
            self._logger.info(
                f"[{name}] installée={current or 'non installée'}, "
                f"disponible={latest or 'inconnue'}"
            )
            if update_available:
                updates_available.append(
                    {
                        "name": name,
                        "display_name": app.metadata.display_name,
                        "current": current or "non installé",
                        "latest": latest or "inconnue",
                    }
                )
            if progress_callback is not None:
                progress_callback(int((index + 1) / len(applications) * 100))

        if updates_available:
            self._event_bus.catalog_updates_available.emit(updates_available)

        return {
            "applications": results,
            "updates_available": [entry["name"] for entry in updates_available],
        }

    def _detect_installed(self, app: Application) -> Optional[str]:
        """Détecte la version installée, en dégradant proprement sur échec.

        Une commande de détection qui échoue ou expire est journalisée et
        assimilée à « non installé » : elle ne doit pas interrompre la
        vérification des autres applications.
        """
        try:
            return self._detector(app.metadata.detection)
        except (subprocess.SubprocessError, OSError) as exc:
            self._logger.warning(
                f"[{app.metadata.name}] détection impossible ({exc}) : considérée non installée."
            )
            return None

    # ------------------------------------------------------------------
    # Mises à jour et reconfiguration.
    # ------------------------------------------------------------------

    def update_application(
        self, application: str, progress_callback: Optional[ProgressCallback] = None
    ) -> bool:
        """Met à jour une application vers sa version la plus récente disponible.

        Bloquant (réseau + fichiers) : à exécuter via :meth:`start_update_application`.

        Args:
            application: Nom de l'application (dossier du catalogue).
            progress_callback: Fonction optionnelle rappelée avec le
                pourcentage d'avancement (une étape par fichier du manifest).

        Returns:
            ``True`` si tous les fichiers ont été appliqués avec succès.

        Raises:
            ValueError: Si l'application est inconnue, désactivée ou sans version.
            OSError: Si le catalogue ou un fichier est inaccessible.
        """
        app = self._active_application(application)
        version = app.latest_version
        if version is None:
            raise ValueError(f"[{application}] aucune version disponible dans le catalogue.")

        self._logger.info(f"[{application}] mise à jour vers {version}...")
        manifest = self._get_manifest(application, version)
        self._apply_actions(application, manifest.version, list(manifest.files), progress_callback)
        return True

    def reconfigure_application(
        self, application: str, progress_callback: Optional[ProgressCallback] = None
    ) -> bool:
        """Réapplique la configuration d'une application sans la mettre à jour.

        N'exécute que les actions ``ensure_content`` du manifest : la version
        utilisée est la version installée détectée si elle existe dans le
        catalogue, sinon la plus récente disponible.

        Args:
            application: Nom de l'application (dossier du catalogue).
            progress_callback: Fonction optionnelle rappelée avec le
                pourcentage d'avancement.

        Returns:
            ``True`` si les actions de configuration ont été appliquées.

        Raises:
            ValueError: Si l'application est inconnue ou désactivée.
            OSError: Si le catalogue est inaccessible.
        """
        app = self._active_application(application)
        current = self._detect_installed(app)
        version = current if current in app.versions else app.latest_version
        if version is None:
            raise ValueError(f"[{application}] aucune version disponible dans le catalogue.")

        manifest = self._get_manifest(application, version)
        ensure_actions = [
            action for action in manifest.files if action.action is ActionKind.ENSURE_CONTENT
        ]
        self._logger.info(
            f"[{application}] reconfiguration depuis {version} "
            f"({len(ensure_actions)} action(s) ensure_content)."
        )
        if ensure_actions:
            self._apply_actions(application, version, ensure_actions, progress_callback)
        return True

    def update_all(self, progress_callback: Optional[ProgressCallback] = None) -> Dict[str, bool]:
        """Met à jour séquentiellement toutes les applications obsolètes ou absentes.

        Bloquant : à exécuter via :meth:`start_update_all`.

        Args:
            progress_callback: Fonction optionnelle rappelée avec le
                pourcentage d'avancement global (une étape par application).

        Returns:
            Le statut de réussite (``bool``) de chaque mise à jour, par nom
            d'application.
        """
        status = self.check_updates()
        targets: List[str] = status["updates_available"]

        results: Dict[str, bool] = {}
        for index, application in enumerate(targets):
            results[application] = self.update_application(application)
            if progress_callback is not None and targets:
                progress_callback(int((index + 1) / len(targets) * 100))
        return results

    def _active_application(self, application: str) -> Application:
        """Retourne une application active du catalogue, avec garde-fous."""
        catalog = self._ensure_catalog()
        app = catalog.applications.get(application)
        if app is None:
            raise ValueError(
                f"Application inconnue du catalogue : '{application}' "
                f"(valides : {sorted(catalog.applications)})."
            )
        if not app.metadata.enabled:
            raise ValueError(f"Application désactivée dans le catalogue : '{application}'.")
        return app

    def _apply_actions(
        self,
        application: str,
        version: str,
        actions: List[FileAction],
        progress_callback: Optional[ProgressCallback],
    ) -> None:
        """Télécharge chaque fichier source puis exécute son action localement.

        Les téléchargements transitent par un répertoire temporaire, nettoyé en
        fin de traitement ; la progression est répartie uniformément sur les
        fichiers.
        """
        with tempfile.TemporaryDirectory(prefix="workstation_tooler_") as temp_dir:
            staging = Path(temp_dir)
            for index, action in enumerate(actions):
                self._logger.info(
                    f"[{application}] {action.action.value} : {action.source} -> {action.target}"
                )
                downloaded = staging / f"{index:03d}_{PurePosixPath(action.source).name}"
                self._repository.fetch_file(application, version, action.source, downloaded)
                modified = execute_file_action(action, downloaded)
                if action.action is ActionKind.ENSURE_CONTENT:
                    self._logger.info(
                        f"[{application}] contenu {'ajouté' if modified else 'déjà présent'} "
                        f"dans {action.target}"
                    )
                if progress_callback is not None and actions:
                    progress_callback(int((index + 1) / len(actions) * 100))

    # ------------------------------------------------------------------
    # Déclenchement asynchrone (délégation systématique au ThreadManager).
    # ------------------------------------------------------------------

    def _start_action(
        self,
        action: Callable[..., Any],
        target: str,
        status: str,
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Exécute une action du moteur en tâche de fond, avec suivi sur l'EventBus.

        Args:
            action: Fonction à exécuter (peut accepter ``progress_callback``).
            target: Nom de la cible publiée sur l'EventBus (application, etc.).
            status: Statut publié (ex. ``"mise_a_jour"``).
            on_result: Rappelé avec le résultat de l'action.
            on_error: Rappelé avec l'exception levée en cas d'échec.
            on_progress: Rappelé avec l'avancement de l'action (0-100).

        Returns:
            L'identifiant de la tâche créée par le ``ThreadManager``.
        """
        task_name = f"engine.{target}.{status}"
        self._event_bus.module_status_changed.emit(target, status)
        self._event_bus.task_started.emit(task_name)

        def _on_result(result: Any) -> None:
            self._event_bus.task_finished.emit(task_name)
            if on_result is not None:
                on_result(result)

        def _on_error(exc: Exception) -> None:
            self._event_bus.task_finished.emit(task_name)
            if on_error is not None:
                on_error(exc)

        return self._thread_manager.run_task(
            action,
            on_result=_on_result,
            on_error=_on_error,
            on_progress=on_progress,
        )

    def start_load_catalog(
        self,
        on_result: Optional[Callable[[Catalog], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> str:
        """Déclenche le chargement du catalogue en tâche de fond."""
        return self._start_action(self.load_catalog, "catalogue", "chargement", on_result, on_error)

    def start_check_updates(
        self,
        on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> str:
        """Déclenche la vérification des mises à jour en tâche de fond."""
        return self._start_action(
            self.check_updates, "catalogue", "verification", on_result, on_error
        )

    def start_update_application(
        self,
        application: str,
        on_result: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Déclenche la mise à jour d'une application en tâche de fond."""

        def _run(progress_callback: Optional[ProgressCallback] = None) -> bool:
            return self.update_application(application, progress_callback)

        return self._start_action(
            _run, application, "mise_a_jour", on_result, on_error, on_progress
        )

    def start_reconfigure_application(
        self,
        application: str,
        on_result: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Déclenche la reconfiguration d'une application en tâche de fond."""

        def _run(progress_callback: Optional[ProgressCallback] = None) -> bool:
            return self.reconfigure_application(application, progress_callback)

        return self._start_action(
            _run, application, "reconfiguration", on_result, on_error, on_progress
        )

    def start_update_all(
        self,
        on_result: Optional[Callable[[Dict[str, bool]], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Déclenche la mise à jour de toutes les applications en tâche de fond."""

        def _run(progress_callback: Optional[ProgressCallback] = None) -> Dict[str, bool]:
            return self.update_all(progress_callback)

        return self._start_action(_run, "global", "mise_a_jour", on_result, on_error, on_progress)
