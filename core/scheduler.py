"""Singleton Scheduler : planification des vérifications de mise à jour récurrentes.

Orchestre, via des ``QTimer`` (donc sans bloquer le thread principal), la
vérification périodique des mises à jour disponibles :
- pour l'application Workstation Tooler elle-même (``AppUpdater``) ;
- pour les applications gérées par le moteur de mise à jour
  (``UpdateEngine.check_updates``, piloté par le catalogue distant).

Les vérifications elles-mêmes sont déléguées au ``ThreadManager`` par les
objets concernés (``AppUpdater.start_check_update`` /
``UpdateEngine.start_check_updates``) : le ``Scheduler`` ne fait que
déclencher ces appels aux instants prévus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from PyQt6.QtCore import QObject, QTimer

from core.app_updater import AppUpdater
from core.config_loader import ConfigLoader
from core.error_handler import ErrorHandler
from core.logger import Logger

if TYPE_CHECKING:
    from engine.update_engine import UpdateEngine

#: Intervalle par défaut (en minutes) si absent de la configuration.
DEFAULT_APP_CHECK_INTERVAL_MINUTES = 240
DEFAULT_APPLICATIONS_CHECK_INTERVAL_MINUTES = 60


class Scheduler(QObject):
    """Planifie les vérifications récurrentes de mise à jour (application et catalogue).

    Exemple :
        >>> Scheduler().configure(engine=update_engine)
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
        self._error_handler = ErrorHandler()
        self._engine: Optional["UpdateEngine"] = None

        self._app_timer = QTimer(self)
        self._app_timer.timeout.connect(self._check_app_update)

        self._applications_timer = QTimer(self)
        self._applications_timer.timeout.connect(self._check_applications_update)

        Scheduler._initialized = True

    def configure(self, engine: "UpdateEngine") -> None:
        """Enregistre le moteur dont les applications doivent être surveillées.

        Args:
            engine: Moteur de mise à jour branché sur le catalogue distant.
        """
        self._engine = engine

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
        applications_interval = int(
            self._config.get_setting(
                "update.check_interval_minutes", DEFAULT_APPLICATIONS_CHECK_INTERVAL_MINUTES
            )
        )

        self._app_timer.start(app_interval * 60 * 1000)
        self._applications_timer.start(applications_interval * 60 * 1000)

        self._logger.info(
            f"Scheduler démarré (app toutes les {app_interval} min, "
            f"applications toutes les {applications_interval} min)."
        )

        if self._config.get_setting("update.check_on_startup", default=True):
            self._check_app_update()
            self._check_applications_update()

    def stop(self) -> None:
        """Arrête les timers de vérification."""
        self._app_timer.stop()
        self._applications_timer.stop()

    def _check_app_update(self) -> None:
        """Déclenche la vérification de mise à jour de l'application.

        Une défaillance de la vérification périodique est journalisée (sans
        notification intrusive pour l'utilisateur).
        """
        self._app_updater.start_check_update(
            on_result=self._on_app_update_checked,
            on_error=self._on_app_check_error,
        )

    def _on_app_check_error(self, exc: Exception) -> None:
        """Journalise une erreur de vérification périodique (sans notification UI)."""
        self._error_handler.handle_exception(
            exc, context="app (vérification planifiée)", notify_ui=False
        )

    def _on_app_update_checked(self, status: Dict[str, Any]) -> None:
        """Journalise le résultat de la vérification de mise à jour de l'application."""
        self._logger.info(f"[scheduler] résultat vérification application : {status}")

    def _check_applications_update(self) -> None:
        """Déclenche la vérification des mises à jour des applications du catalogue."""
        if self._engine is None:
            self._logger.warning("[scheduler] aucun moteur configuré : vérification ignorée.")
            return
        self._engine.start_check_updates(on_result=self._on_applications_update_checked)

    def _on_applications_update_checked(self, status: Dict[str, Any]) -> None:
        """Journalise le récapitulatif de la vérification des applications."""
        self._logger.info(f"[scheduler] résultat vérification des applications : {status}")
