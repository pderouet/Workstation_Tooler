"""Singleton EventBus : canal de communication unique entre threads et UI.

Toute information devant circuler entre la logique métier (exécutée dans
des ``QThread`` via le ``ThreadManager``) et l'interface graphique doit
impérativement transiter par ce bus de signaux PyQt (``pyqtSignal``), qui
garantit une livraison thread-safe grâce au mécanisme de connexions
Qt (``QueuedConnection`` automatique entre threads différents).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal


class EventBus(QObject):
    """Bus d'évènements applicatif unique, basé sur des signaux PyQt6.

    Signaux exposés :
        log_message(str, str): niveau, message — pour relayer un log vers l'UI.
        error_occurred(str, str): titre, message — erreur à notifier à l'utilisateur.
        module_status_changed(str, str): nom de la cible (application ou ``"app"``),
            nouveau statut.
        update_progress(str, int): nom de la cible (ou ``"app"``), pourcentage de progression.
        update_finished(str, bool, str): nom de la cible (ou ``"app"``), succès, message.
        update_available(str, str, str): nom de la cible (réservé à ``"app"``, mise à jour
            de l'application elle-même), version courante, version disponible.
        catalog_updates_available(list): mises à jour disponibles des applications du
            catalogue, sous forme de dictionnaires ``{"name", "display_name", "current",
            "latest"}`` — émis UNE SEULE fois par vérification (notification groupée).
        resource_state_changed(str, bool): nom de ressource réseau (``"catalogue"``,
            ``"forge"``), disponible — émis aux transitions uniquement (icône d'erreur
            et replanification du contrôle à 3 minutes en cas d'indisponibilité).
        catalog_loaded(list): applications actives du catalogue distant, sous forme de
            dictionnaires ``{"name", "display_name"}`` — émis par l'``UpdateEngine``.
        task_started(str): nom de la tâche de fond démarrée (ex. ``"engine.vim.mise_a_jour"``),
            utilisé par l'UI pour refléter un état « en cours » (icône WIP).
        task_finished(str): nom de la tâche de fond terminée, utilisé par l'UI pour
            revenir à un état stable (icône OK/Info) une fois toutes les tâches closes.
    """

    log_message = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str, str)
    module_status_changed = pyqtSignal(str, str)
    update_progress = pyqtSignal(str, int)
    update_finished = pyqtSignal(str, bool, str)
    update_available = pyqtSignal(str, str, str)
    catalog_updates_available = pyqtSignal(list)
    resource_state_changed = pyqtSignal(str, bool)
    catalog_loaded = pyqtSignal(list)
    task_started = pyqtSignal(str)
    task_finished = pyqtSignal(str)

    _instance: Optional["EventBus"] = None
    _initialized: bool = False

    def __new__(cls, *args: Any, **kwargs: Dict[str, Any]) -> "EventBus":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialise le ``QObject`` sous-jacent une seule fois (garde Singleton)."""
        if EventBus._initialized:
            return
        super().__init__()
        EventBus._initialized = True
