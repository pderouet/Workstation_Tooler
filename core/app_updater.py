"""Singleton AppUpdater : mise à jour de l'application Workstation Tooler elle-même.

Permet de comparer la version actuellement déployée sur le poste à la
dernière version disponible sur le dépôt GitHub du projet, et de déclencher
la mise à jour depuis le SystemTray.

Les méthodes ci-dessous sont volontairement fournies sous forme de
squelette : la logique d'appel réel à l'API GitHub et le mécanisme de mise
à jour effectif (ex. ``git pull``, téléchargement d'un asset de release,
etc.) restent à implémenter selon le mode de déploiement retenu.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from core import SingletonMeta
from core.event_bus import EventBus
from core.logger import Logger
from core.thread_manager import ThreadManager

#: Version actuellement déployée de Workstation Tooler (à faire évoluer à chaque release).
APP_VERSION = "0.1.0"

#: Dépôt GitHub source du projet, au format ``propriétaire/dépôt``.
GITHUB_REPOSITORY = "pderouet/Workstation_Tooler"


class AppUpdater(metaclass=SingletonMeta):
    """Gère la vérification et l'exécution de la mise à jour de l'application.

    Exemple :
        >>> AppUpdater().start_check_update(on_result=lambda status: print(status))
    """

    def __init__(self) -> None:
        """Connecte le squelette aux singletons du socle (logger, bus, threads)."""
        self._logger = Logger()
        self._event_bus = EventBus()
        self._thread_manager = ThreadManager()

    def get_current_version(self) -> str:
        """Retourne la version actuellement déployée sur le poste.

        Returns:
            La version locale de l'application (``APP_VERSION``).
        """
        return APP_VERSION

    def get_latest_version(self) -> Optional[str]:
        """Retourne la dernière version disponible sur le dépôt GitHub.

        TODO:
            Implémenter l'appel à l'API GitHub (ex. tags ou releases de
            ``GITHUB_REPOSITORY``) afin de résoudre la dernière version
            publiée.

        Returns:
            La dernière version disponible, ou ``None`` tant que la
            résolution n'est pas implémentée.
        """
        # TODO: interroger https://api.github.com/repos/<GITHUB_REPOSITORY>/tags
        # (ou /releases/latest) et retourner la version la plus récente.
        return None

    def check_update(self) -> Dict[str, Any]:
        """Compare la version locale à la dernière version disponible.

        Returns:
            Un dictionnaire ``{"current_version", "latest_version", "update_available"}``.
        """
        current_version = self.get_current_version()
        latest_version = self.get_latest_version()
        update_available = latest_version is not None and latest_version != current_version

        self._logger.info(
            f"[app] version installée={current_version}, dernière version={latest_version}"
        )

        if update_available:
            self._event_bus.update_available.emit(
                "app", current_version, latest_version or "inconnue"
            )

        return {
            "current_version": current_version,
            "latest_version": latest_version,
            "update_available": update_available,
        }

    def perform_update(self, progress_callback: Optional[Callable[[int], None]] = None) -> bool:
        """Exécute la mise à jour de l'application vers la dernière version.

        TODO:
            Implémenter le mécanisme de mise à jour effectif (ex. ``git
            pull`` sur le clone du poste, téléchargement et remplacement
            d'un exécutable packagé, etc.), puis prévoir le redémarrage de
            l'application.

        Args:
            progress_callback: Fonction optionnelle appelée avec un
                pourcentage d'avancement (0-100).

        Returns:
            ``True`` si la mise à jour s'est terminée avec succès.
        """
        self._logger.warning("[app] perform_update() n'est pas encore implémenté.")
        # TODO: implémenter la mise à jour réelle (git pull / téléchargement release / etc.).
        return False

    # ------------------------------------------------------------------
    # Déclenchement asynchrone (délégation systématique au ThreadManager).
    # ------------------------------------------------------------------

    def start_check_update(
        self,
        on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> str:
        """Déclenche ``check_update`` en tâche de fond.

        Args:
            on_result: Rappelé avec le résultat de la vérification.
            on_error: Rappelé avec l'exception levée en cas d'échec.

        Returns:
            L'identifiant de la tâche créée par le ``ThreadManager``.
        """
        task_name = "app.verification"
        self._event_bus.task_started.emit(task_name)

        def _on_result(result: Dict[str, Any]) -> None:
            self._event_bus.task_finished.emit(task_name)
            if on_result is not None:
                on_result(result)

        def _on_error(exc: Exception) -> None:
            self._event_bus.task_finished.emit(task_name)
            if on_error is not None:
                on_error(exc)

        return self._thread_manager.run_task(
            self.check_update, on_result=_on_result, on_error=_on_error
        )

    def start_update(
        self,
        on_result: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Déclenche ``perform_update`` en tâche de fond.

        Args:
            on_result: Rappelé avec le résultat booléen de la mise à jour.
            on_error: Rappelé avec l'exception levée en cas d'échec.
            on_progress: Rappelé avec l'avancement de la mise à jour.

        Returns:
            L'identifiant de la tâche créée par le ``ThreadManager``.
        """
        task_name = "app.mise_a_jour"
        self._event_bus.module_status_changed.emit("app", "mise_a_jour")
        self._event_bus.task_started.emit(task_name)

        def _on_result(result: bool) -> None:
            self._event_bus.task_finished.emit(task_name)
            if on_result is not None:
                on_result(result)

        def _on_error(exc: Exception) -> None:
            self._event_bus.task_finished.emit(task_name)
            if on_error is not None:
                on_error(exc)

        return self._thread_manager.run_task(
            self.perform_update, on_result=_on_result, on_error=_on_error, on_progress=on_progress
        )
