"""Singleton Scheduler : planification des vérifications de mise à jour récurrentes.

Orchestre, via des ``QTimer`` (donc sans bloquer le thread principal), la
vérification périodique des mises à jour disponibles :
- pour l'application Workstation Tooler elle-même (``AppUpdater``) ;
- pour chaque module de mise à jour chargé (``BaseModule.check_update``).

Les vérifications elles-mêmes sont déléguées au ``ThreadManager`` par les
objets concernés (``AppUpdater.start_check_update`` / ``BaseModule.start_check_update``) :
le ``Scheduler`` ne fait que déclencher ces appels aux instants prévus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QTimer

from core.app_updater import AppUpdater
from core.config_loader import ConfigLoader
from core.logger import Logger

if TYPE_CHECKING:
    from modules.base_module import BaseModule

#: Intervalle par défaut (en minutes) si absent de la configuration.
DEFAULT_APP_CHECK_INTERVAL_MINUTES = 240
DEFAULT_MODULES_CHECK_INTERVAL_MINUTES = 60


class Scheduler(QObject):
    """Planifie les vérifications récurrentes de mise à jour (application et modules).

    Exemple :
        >>> Scheduler().configure(modules=loaded_modules)
        >>> Scheduler().start()
    """

    _instance: Optional["Scheduler"] = None
    _initialized: bool = False

    def __new__(cls, *args: Any, **kwargs: Dict[str, Any]) -> "Scheduler":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialise les timers et les dépendances (une seule fois)."""
        if Scheduler._initialized:
            return
        super().__init__()
        self._logger = Logger()
        self._config = ConfigLoader()
        self._app_updater = AppUpdater()
        self._modules: List["BaseModule"] = []

        self._app_timer = QTimer(self)
        self._app_timer.timeout.connect(self._check_app_update)

        self._modules_timer = QTimer(self)
        self._modules_timer.timeout.connect(self._check_modules_update)

        Scheduler._initialized = True

    def configure(self, modules: List["BaseModule"]) -> None:
        """Enregistre les modules dont la mise à jour doit être surveillée.

        Args:
            modules: Liste des modules de mise à jour déjà attachés au socle.
        """
        self._modules = modules

    def start(self) -> None:
        """Démarre les timers de vérification selon la configuration.

        Lit les intervalles (en minutes) depuis ``settings.yaml`` :
        ``update.app_check_interval_minutes`` et ``update.check_interval_minutes``.
        Si ``update.check_on_startup`` est vrai, une première vérification est
        déclenchée immédiatement.
        """
        app_interval = int(
            self._config.get_setting(
                "update.app_check_interval_minutes", DEFAULT_APP_CHECK_INTERVAL_MINUTES
            )
        )
        modules_interval = int(
            self._config.get_setting(
                "update.check_interval_minutes", DEFAULT_MODULES_CHECK_INTERVAL_MINUTES
            )
        )

        self._app_timer.start(app_interval * 60 * 1000)
        self._modules_timer.start(modules_interval * 60 * 1000)

        self._logger.info(
            f"Scheduler démarré (app toutes les {app_interval} min, "
            f"modules toutes les {modules_interval} min)."
        )

        if self._config.get_setting("update.check_on_startup", default=True):
            self._check_app_update()
            self._check_modules_update()

    def stop(self) -> None:
        """Arrête les timers de vérification."""
        self._app_timer.stop()
        self._modules_timer.stop()

    def _check_app_update(self) -> None:
        """Déclenche la vérification de mise à jour de l'application."""
        self._app_updater.start_check_update(on_result=self._on_app_update_checked)

    def _on_app_update_checked(self, status: Dict[str, Any]) -> None:
        """Journalise le résultat de la vérification de mise à jour de l'application."""
        self._logger.info(f"[scheduler] résultat vérification application : {status}")

    def _check_modules_update(self) -> None:
        """Déclenche la vérification de mise à jour de chaque module enregistré."""
        for module in self._modules:
            module.start_check_update(on_result=self._make_module_result_logger(module.name))

    def _make_module_result_logger(self, module_name: str):
        """Construit un callback de journalisation du résultat pour un module donné.

        Args:
            module_name: Nom du module concerné, utilisé dans le message de log.

        Returns:
            Une fonction acceptant le dictionnaire de statut de ``check_update``.
        """

        def _log_result(status: Dict[str, Any]) -> None:
            self._logger.info(f"[scheduler] résultat vérification '{module_name}' : {status}")

        return _log_result
