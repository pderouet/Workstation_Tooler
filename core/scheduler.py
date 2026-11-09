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

La disponibilité des ressources réseau (partage du catalogue, forge) est
suivie par :class:`ResourceHealthMonitor` : une ressource inaccessible fait
basculer son contrôle sur l'intervalle de reprise (3 minutes par défaut)
jusqu'à la première réussite, et chaque transition d'état est publiée sur
l'``EventBus`` (``resource_state_changed``) pour refléter l'erreur dans l'UI
sans interrompre l'application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Set

from PyQt6.QtCore import QObject, QTimer

from core.app_updater import AppUpdater
from core.config_loader import ConfigLoader
from core.error_handler import ErrorHandler
from core.event_bus import event_bus
from core.logger import Logger

if TYPE_CHECKING:
    from engine.update_engine import UpdateEngine

#: Intervalle par défaut (en minutes) si absent de la configuration.
DEFAULT_APP_CHECK_INTERVAL_MINUTES = 240
DEFAULT_APPLICATIONS_CHECK_INTERVAL_MINUTES = 60

#: Intervalle de reprise (en minutes) d'une ressource réseau indisponible.
DEFAULT_RETRY_INTERVAL_MINUTES = 3

#: Ressource « partage réseau du catalogue des applications ».
RESOURCE_CATALOGUE = "catalogue"

#: Ressource « forge de mise à jour de l'application » (GitHub/GitLab).
RESOURCE_FORGE = "forge"


class ResourceHealthMonitor:
    """Suit la disponibilité des ressources réseau et adapte la périodicité des contrôles.

    Une ressource signalée indisponible bascule son timer de contrôle sur
    l'intervalle de reprise ; dès la première réussite, l'intervalle normal est
    restauré. Les changements d'état sont publiés exactement une fois par
    transition via le rappel ``notify`` (reposé sur l'``EventBus`` par le
    ``Scheduler``).
    """

    def __init__(
        self,
        timers: Dict[str, Any],
        normal_intervals_ms: Dict[str, int],
        retry_interval_ms: int,
        notify: Callable[[str, bool], None],
    ) -> None:
        """Initialise le suivi des ressources.

        Args:
            timers: Timer de contrôle par ressource (objet à méthode
                ``start(délai_ms)`` — ``QTimer`` ou doublure de test).
            normal_intervals_ms: Intervalle configuré (ms) par ressource.
            retry_interval_ms: Intervalle de reprise (ms) en cas d'indisponibilité.
            notify: Rappel des transitions, ``(ressource, disponible)``.
        """
        self._timers = timers
        self._normal_intervals_ms = normal_intervals_ms
        self._retry_interval_ms = retry_interval_ms
        self._notify = notify
        self._degraded: Set[str] = set()

    @property
    def degraded(self) -> Set[str]:
        """Les ressources actuellement considérées indisponibles."""
        return set(self._degraded)

    def register_outcome(self, resource: str, available: bool) -> None:
        """Enregistre le résultat d'un contrôle et réagit aux transitions.

        Args:
            resource: Nom de la ressource (ex. ``"catalogue"``).
            available: ``True`` si le contrôle a réussi.
        """
        if not available:
            if resource in self._degraded:
                return  # déjà en erreur : pas de re-notification.
            self._degraded.add(resource)
            self._notify(resource, False)
            self._restart(resource, self._retry_interval_ms)
        elif resource in self._degraded:
            self._degraded.discard(resource)
            self._notify(resource, True)
            self._restart(resource, self._normal_intervals_ms[resource])

    def _restart(self, resource: str, interval_ms: int) -> None:
        """Replanifie le timer de contrôle d'une ressource au délai demandé."""
        timer = self._timers.get(resource)
        if timer is not None:
            timer.start(interval_ms)


class Scheduler(QObject):
    """Planifie les vérifications récurrentes de mise à jour (application et catalogue).

    Exemple :
        >>> scheduler().configure(engine=update_engine)
        >>> scheduler().start()
    """

    def __init__(self) -> None:
        """Initialise les timers et les dépendances."""
        super().__init__()
        self._logger = Logger()
        self._config = ConfigLoader()
        self._app_updater = AppUpdater()
        self._error_handler = ErrorHandler()
        self._event_bus = event_bus()
        self._engine: Optional["UpdateEngine"] = None

        self._app_timer = QTimer(self)
        self._app_timer.timeout.connect(self._check_app_update)

        self._applications_timer = QTimer(self)
        self._applications_timer.timeout.connect(self._check_applications_update)

        self._monitor = ResourceHealthMonitor(
            timers={RESOURCE_FORGE: self._app_timer, RESOURCE_CATALOGUE: self._applications_timer},
            normal_intervals_ms={
                RESOURCE_FORGE: self._configured_interval_ms(
                    "update.app_check_interval_minutes", DEFAULT_APP_CHECK_INTERVAL_MINUTES
                ),
                RESOURCE_CATALOGUE: self._configured_interval_ms(
                    "update.check_interval_minutes", DEFAULT_APPLICATIONS_CHECK_INTERVAL_MINUTES
                ),
            },
            retry_interval_ms=self._configured_interval_ms(
                "update.retry_interval_minutes", DEFAULT_RETRY_INTERVAL_MINUTES
            ),
            notify=self._event_bus.resource_state_changed.emit,
        )

    def _configured_interval_ms(self, key: str, default_minutes: int) -> int:
        """Lit un intervalle (minutes) dans la configuration et le convertit en ms."""
        minutes = int(self._config.get_setting(key, default_minutes))
        return minutes * 60 * 1000

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
        self._app_timer.start(
            self._configured_interval_ms(
                "update.app_check_interval_minutes", DEFAULT_APP_CHECK_INTERVAL_MINUTES
            )
        )
        self._applications_timer.start(
            self._configured_interval_ms(
                "update.check_interval_minutes", DEFAULT_APPLICATIONS_CHECK_INTERVAL_MINUTES
            )
        )

        self._logger.info("Scheduler démarré (contrôles périodiques actifs).")

        if self._config.get_setting("update.check_on_startup", default=True):
            self._check_app_update()
            self._check_applications_update()

    def stop(self) -> None:
        """Arrête les timers de vérification."""
        self._app_timer.stop()
        self._applications_timer.stop()

    # ------------------------------------------------------------------
    # Vérification de l'application elle-même (forge).
    # ------------------------------------------------------------------

    def _check_app_update(self) -> None:
        """Déclenche la vérification de mise à jour de l'application.

        Une défaillance (forge injoignable) est journalisée sans notification
        intrusive et fait basculer le contrôle sur l'intervalle de reprise.
        """
        self._app_updater.start_check_update(
            on_result=self._on_app_update_checked,
            on_error=self._on_app_check_error,
        )

    def _on_app_check_error(self, exc: Exception) -> None:
        """Journalise l'échec du contrôle et dégrade la ressource forge."""
        self._error_handler.handle_exception(
            exc, context="app (vérification planifiée)", notify_ui=False
        )
        self._monitor.register_outcome(RESOURCE_FORGE, available=False)

    def _on_app_update_checked(self, status: Dict[str, Any]) -> None:
        """Journalise le résultat et rétablit la forge si elle était dégradée.

        Une version distante indéterminée (``latest_version`` à ``None``)
        signale une forge inaccessible : la ressource est dégradée.
        """
        self._logger.info(f"[scheduler] résultat vérification application : {status}")
        forge_available = status.get("latest_version") is not None
        self._monitor.register_outcome(RESOURCE_FORGE, available=forge_available)

    # ------------------------------------------------------------------
    # Vérification des applications du catalogue (partage réseau).
    # ------------------------------------------------------------------

    def _check_applications_update(self) -> None:
        """Déclenche la vérification des mises à jour des applications du catalogue."""
        if self._engine is None:
            self._logger.warning("[scheduler] aucun moteur configuré : vérification ignorée.")
            return
        self._engine.start_check_updates(
            on_result=self._on_applications_update_checked,
            on_error=self._on_applications_check_error,
        )

    def _on_applications_check_error(self, exc: Exception) -> None:
        """Journalise l'échec du contrôle et dégrade la ressource catalogue."""
        self._error_handler.handle_exception(
            exc, context="applications (vérification planifiée)", notify_ui=False
        )
        self._monitor.register_outcome(RESOURCE_CATALOGUE, available=False)

    def _on_applications_update_checked(self, status: Dict[str, Any]) -> None:
        """Journalise le récapitulatif et rétablit le catalogue si dégradé."""
        self._logger.info(f"[scheduler] résultat vérification des applications : {status}")
        self._monitor.register_outcome(RESOURCE_CATALOGUE, available=True)


#: Instance unique du Scheduler (créée au premier appel de la fabrique).
_instance: Optional["Scheduler"] = None


def scheduler() -> "Scheduler":
    """Retourne l'instance unique du ``Scheduler`` (créée au premier appel).

    Singleton par fabrique de module (et non par surcharge de
    ``__new__``/``__init__``, fragile avec sip — voir
    :func:`core.event_bus.event_bus`).

    Returns:
        L'instance unique du planificateur.
    """
    global _instance
    if _instance is None:
        _instance = Scheduler()
    return _instance
