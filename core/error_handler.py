"""Système centralisé de gestion des erreurs.

Toute exception interceptée dans l'application (modules, threads, UI) doit
être transmise à ce gestionnaire unique, qui se charge de la journaliser
via le ``Logger`` et de notifier l'interface utilisateur via l'``EventBus``.
Aucun bloc ``except`` générique ne doit avaler une exception sans la faire
transiter par ``ErrorHandler.handle_exception``.
"""

from __future__ import annotations

from core import SingletonMeta
from core.event_bus import EventBus
from core.logger import Logger


class ErrorHandler(metaclass=SingletonMeta):
    """Point d'entrée unique pour le traitement des erreurs applicatives.

    Exemple :
        >>> try:
        ...     risky_operation()
        ... except Exception as exc:
        ...     ErrorHandler().handle_exception(exc, context="module.openshift")
    """

    def __init__(self) -> None:
        """Connecte le gestionnaire au ``Logger`` et à l'``EventBus``."""
        self._logger = Logger()
        self._event_bus = EventBus()

    def handle_exception(
        self,
        exception: Exception,
        context: str = "",
        notify_ui: bool = True,
    ) -> None:
        """Journalise une exception et notifie l'UI via l'``EventBus``.

        Args:
            exception: L'exception interceptée à traiter.
            context: Description du contexte d'origine (ex. nom du module),
                utile au diagnostic.
            notify_ui: Si ``True``, émet le signal ``error_occurred`` afin
                que l'interface graphique puisse notifier l'utilisateur.
        """
        message = (
            f"[{context}] {exception.__class__.__name__}: {exception}"
            if context
            else str(exception)
        )
        self._logger.error(message)

        if notify_ui:
            title = f"Erreur{f' - {context}' if context else ''}"
            self._event_bus.error_occurred.emit(title, str(exception))

    def handle_message(self, title: str, message: str, level: str = "error") -> None:
        """Permet de notifier une erreur fonctionnelle sans exception Python.

        Args:
            title: Titre court de l'erreur, affiché à l'utilisateur.
            message: Détail de l'erreur.
            level: Niveau de log à utiliser (``"warning"`` ou ``"error"``).
        """
        log_method = self._logger.warning if level == "warning" else self._logger.error
        log_method(f"{title}: {message}")
        self._event_bus.error_occurred.emit(title, message)
