"""Classe abstraite de base pour tous les modules de mise à jour d'outils.

Chaque outil pris en charge (OpenShift, Vim, DBeaver, Freelens, K9s, ...)
doit être implémenté comme un module indépendant héritant de
``BaseModule``. Celle-ci fournit, par défaut, une méthode de vérification
des mises à jour (``check_update``) basée sur un patron de conception
« template method » : chaque module n'a qu'à implémenter les méthodes
d'accès aux versions (``get_installed_version``/``get_latest_version``) et
aux actions de cycle de vie (``install``/``uninstall``/``reconfigure``).

Aucune logique lourde ne doit être exécutée directement dans le thread
appelant : les méthodes ``start_*`` délèguent systématiquement l'exécution
au ``ThreadManager``.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Tuple

from core.config_loader import ConfigLoader
from core.event_bus import EventBus
from core.logger import Logger
from core.thread_manager import ThreadManager

ProgressCallback = Callable[[int], None]


class BaseModule(ABC):
    """Interface commune que tout module de mise à jour doit respecter."""

    #: Nom unique du module, utilisé pour les logs, la configuration et l'UI.
    name: str = "base"

    #: Libellé lisible affiché dans les menus de l'UI (par défaut ``name`` capitalisé).
    display_name: str = ""

    def __init__(self) -> None:
        """Initialise les attributs d'attache au socle (non connectés par défaut)."""
        self.logger: Optional[Logger] = None
        self.event_bus: Optional[EventBus] = None
        self.config: Optional[ConfigLoader] = None
        self._thread_manager: Optional[ThreadManager] = None
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()

    def attach(
        self,
        logger: Logger,
        event_bus: EventBus,
        config: ConfigLoader,
        thread_manager: ThreadManager,
    ) -> None:
        """Attache le module au socle applicatif (singletons partagés).

        Cette méthode doit être appelée par le chargeur de modules juste
        après l'instanciation, avant tout appel à ``check_update`` ou à une
        action de cycle de vie (install/uninstall/reinstall/reconfigure).

        Args:
            logger: Instance unique du ``Logger`` applicatif.
            event_bus: Instance unique de l'``EventBus``.
            config: Instance unique du ``ConfigLoader``.
            thread_manager: Instance unique du ``ThreadManager``.
        """
        self.logger = logger
        self.event_bus = event_bus
        self.config = config
        self._thread_manager = thread_manager
        self.logger.info(f"Module '{self.name}' attaché au socle.")

    def module_config(self) -> Dict[str, Any]:
        """Raccourci vers la configuration propre à ce module.

        Returns:
            Le dictionnaire de configuration du module (vide si absent).
        """
        if self.config is None:
            return {}
        return self.config.get_module_config(self.name, default={}) or {}

    # ------------------------------------------------------------------
    # Méthodes à implémenter par chaque module concret.
    # ------------------------------------------------------------------

    @abstractmethod
    def get_installed_version(self) -> Optional[str]:
        """Retourne la version actuellement installée sur le poste.

        Returns:
            La version installée, ou ``None`` si l'outil n'est pas installé
            ou que sa version n'a pas pu être déterminée.
        """
        raise NotImplementedError

    @abstractmethod
    def get_latest_version(self) -> Optional[str]:
        """Retourne la dernière version disponible (dépôt interne, GitHub, etc.).

        Returns:
            La dernière version disponible, ou ``None`` si elle n'a pas pu
            être déterminée.
        """
        raise NotImplementedError

    @abstractmethod
    def install(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Installe l'outil géré par ce module.

        Args:
            progress_callback: Fonction optionnelle appelée avec un
                pourcentage d'avancement (0-100).

        Returns:
            ``True`` si l'installation s'est terminée avec succès.
        """
        raise NotImplementedError

    @abstractmethod
    def uninstall(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Désinstalle l'outil géré par ce module.

        Args:
            progress_callback: Fonction optionnelle appelée avec un
                pourcentage d'avancement (0-100).

        Returns:
            ``True`` si la désinstallation s'est terminée avec succès.
        """
        raise NotImplementedError

    @abstractmethod
    def reconfigure(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Réapplique la configuration de l'outil (fichiers de config, profils, etc.).

        Args:
            progress_callback: Fonction optionnelle appelée avec un
                pourcentage d'avancement (0-100).

        Returns:
            ``True`` si la reconfiguration s'est terminée avec succès.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Méthodes concrètes fournies par défaut (template method).
    # ------------------------------------------------------------------

    def check_update(self) -> Dict[str, Any]:
        """Vérifie si une mise à jour est disponible pour l'outil géré.

        Implémentation par défaut, commune à tous les modules : elle
        s'appuie sur ``get_installed_version`` et ``get_latest_version``
        pour déterminer si une mise à jour doit être proposée.

        Returns:
            Un dictionnaire ``{"current_version", "latest_version", "update_available"}``.
        """
        current_version = self.get_installed_version()
        latest_version = self.get_latest_version()

        update_available = latest_version is not None and (
            current_version is None or current_version != latest_version
        )

        if self.logger is not None:
            self.logger.info(
                f"[{self.name}] version installée={current_version}, dernière version={latest_version}"
            )

        if update_available and self.event_bus is not None:
            self.event_bus.update_available.emit(
                self.name, current_version or "non installé", latest_version or "inconnue"
            )

        return {
            "current_version": current_version,
            "latest_version": latest_version,
            "update_available": update_available,
        }

    def _run_simulated_steps(
        self, steps: Tuple[str, ...], progress_callback: Optional[ProgressCallback] = None
    ) -> bool:
        """Exécute une séquence d'étapes en journalisant et en reportant la progression.

        Utilitaire partagé par les modules dont l'action réelle (téléchargement,
        appel à un gestionnaire de paquets, etc.) reste à implémenter : il
        fournit un comportement observable (logs, progression) en attendant.

        Args:
            steps: Libellés des étapes à journaliser successivement.
            progress_callback: Fonction optionnelle appelée avec un
                pourcentage d'avancement (0-100) après chaque étape.

        Returns:
            ``True`` une fois toutes les étapes « exécutées ».
        """
        for index, step in enumerate(steps, start=1):
            if self.logger is not None:
                self.logger.info(f"[{self.name}] {step}...")
            time.sleep(0.2)  # Simule le temps de traitement de l'étape.
            if progress_callback is not None:
                progress_callback(int(index / len(steps) * 100))

        if self.logger is not None:
            self.logger.info(f"[{self.name}] Opération terminée avec succès.")
        return True

    def reinstall(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Réinstalle l'outil (désinstallation puis installation).

        Les modules ayant une procédure de réinstallation spécifique
        peuvent surcharger cette méthode.

        Args:
            progress_callback: Fonction optionnelle appelée avec un
                pourcentage d'avancement (0-100).

        Returns:
            ``True`` si la désinstallation et l'installation ont réussi.
        """
        uninstalled = self.uninstall(progress_callback)
        if not uninstalled:
            return False
        return self.install(progress_callback)

    # ------------------------------------------------------------------
    # Déclenchement asynchrone (délégation systématique au ThreadManager).
    # ------------------------------------------------------------------

    def _start_action(
        self,
        action: Callable[..., Any],
        status: str,
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Délègue l'exécution d'une action de cycle de vie au ``ThreadManager``.

        Args:
            action: Méthode du module à exécuter en tâche de fond.
            status: Statut à publier sur l'``EventBus`` (ex. ``"installation"``).
            on_result: Rappelé avec le résultat de l'action.
            on_error: Rappelé avec l'exception levée en cas d'échec.
            on_progress: Rappelé avec l'avancement de l'action.

        Returns:
            L'identifiant de la tâche créée par le ``ThreadManager``.

        Raises:
            RuntimeError: Si le module n'a pas été attaché au socle.
        """
        if self._thread_manager is None:
            raise RuntimeError(f"Le module '{self.name}' n'a pas été attaché au socle (attach()).")

        task_name = f"module.{self.name}.{status}"
        if self.event_bus is not None:
            self.event_bus.module_status_changed.emit(self.name, status)
            self.event_bus.task_started.emit(task_name)

        def _on_result(result: Any) -> None:
            if self.event_bus is not None:
                self.event_bus.task_finished.emit(task_name)
            if on_result is not None:
                on_result(result)

        def _on_error(exc: Exception) -> None:
            if self.event_bus is not None:
                self.event_bus.task_finished.emit(task_name)
            if on_error is not None:
                on_error(exc)

        return self._thread_manager.run_task(
            action,
            on_result=_on_result,
            on_error=_on_error,
            on_progress=on_progress,
        )

    def start_check_update(
        self,
        on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> str:
        """Déclenche ``check_update`` en tâche de fond."""
        return self._start_action(self.check_update, "verification", on_result, on_error)

    def start_install(
        self,
        on_result: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Déclenche ``install`` en tâche de fond."""
        return self._start_action(self.install, "installation", on_result, on_error, on_progress)

    def start_uninstall(
        self,
        on_result: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Déclenche ``uninstall`` en tâche de fond."""
        return self._start_action(
            self.uninstall, "desinstallation", on_result, on_error, on_progress
        )

    def start_reinstall(
        self,
        on_result: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Déclenche ``reinstall`` en tâche de fond."""
        return self._start_action(
            self.reinstall, "reinstallation", on_result, on_error, on_progress
        )

    def start_reconfigure(
        self,
        on_result: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Déclenche ``reconfigure`` en tâche de fond."""
        return self._start_action(
            self.reconfigure, "reconfiguration", on_result, on_error, on_progress
        )
