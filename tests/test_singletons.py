"""Tests headless des singletons QObject via fabriques de module.

Le patron « fabrique » remplace la surcharge de ``__new__``/``__init__`` sur
les classes sip/PyQt : ce dernier provoquait, avec certaines combinaisons
PyQt6/sip sous Windows, une récursion infinie de l'initialisation native
(stack overflow silencieux). Ces tests garantissent que les fabriques
retournent bien une instance unique et que les classes restent **complètes**
(toutes leurs méthodes présentes) — régression piégée lors du refactor.
"""

from __future__ import annotations

from core.event_bus import EventBus, event_bus
from core.scheduler import Scheduler, scheduler
from core.thread_manager import ThreadManager, thread_manager


def test_event_bus_instance_unique() -> None:
    """La fabrique event_bus() retourne toujours la même instance."""
    assert event_bus() is event_bus()
    assert isinstance(event_bus(), EventBus)


def test_thread_manager_instance_unique_et_complet() -> None:
    """La fabrique thread_manager() est unique et la classe garde ses méthodes."""
    assert thread_manager() is thread_manager()
    assert isinstance(thread_manager(), ThreadManager)
    for method in ("run_task", "shutdown"):
        assert hasattr(ThreadManager, method), f"méthode perdue : {method}"


def test_scheduler_instance_unique_et_complet() -> None:
    """La fabrique scheduler() est unique et la classe garde ses méthodes."""
    assert scheduler() is scheduler()
    assert isinstance(scheduler(), Scheduler)
    for method in ("configure", "start", "stop", "_check_app_update"):
        assert hasattr(Scheduler, method), f"méthode perdue : {method}"


def test_event_bus_signaux_disponibles() -> None:
    """Les signaux attendus par l'UI existent sur l'instance unique."""
    bus = event_bus()
    for signal in (
        "error_occurred",
        "update_finished",
        "update_available",
        "catalog_updates_available",
        "resource_state_changed",
        "catalog_loaded",
        "task_started",
        "task_finished",
    ):
        assert hasattr(bus, signal), f"signal perdu : {signal}"
