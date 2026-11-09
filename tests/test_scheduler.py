"""Tests headless du suivi de disponibilité des ressources réseau (Scheduler).

La logique de dégradation/reprise est portée par ``ResourceHealthMonitor``
(logique pure) : timers et notifications y sont remplacés par des doublures,
aucun objet Qt n'est instancié.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from core.scheduler import RESOURCE_CATALOGUE, RESOURCE_FORGE, ResourceHealthMonitor


class FakeTimer:
    """Timer factice enregistrant les replanifications demandées."""

    def __init__(self) -> None:
        self.intervals: List[int] = []

    def start(self, interval_ms: int) -> None:
        self.intervals.append(interval_ms)


def make_monitor(
    normal_ms: Dict[str, int] = None,
    retry_ms: int = 3 * 60 * 1000,
) -> Tuple[ResourceHealthMonitor, Dict[str, FakeTimer], List[Tuple[str, bool]]]:
    """Construit un moniteur câblé sur des timers et un notify factices."""
    timers = {RESOURCE_FORGE: FakeTimer(), RESOURCE_CATALOGUE: FakeTimer()}
    notifications: List[Tuple[str, bool]] = []
    monitor = ResourceHealthMonitor(
        timers=timers,
        normal_intervals_ms=normal_ms
        or {RESOURCE_FORGE: 240 * 60 * 1000, RESOURCE_CATALOGUE: 60 * 60 * 1000},
        retry_interval_ms=retry_ms,
        notify=lambda resource, available: notifications.append((resource, available)),
    )
    return monitor, timers, notifications


def test_transition_vers_indisponible_une_seule_fois() -> None:
    """L'échec notifie une seule fois puis replanifie à 3 minutes."""
    monitor, timers, notifications = make_monitor()

    monitor.register_outcome(RESOURCE_CATALOGUE, available=False)
    monitor.register_outcome(RESOURCE_CATALOGUE, available=False)  # toujours en erreur.

    assert notifications == [(RESOURCE_CATALOGUE, False)]
    assert timers[RESOURCE_CATALOGUE].intervals == [3 * 60 * 1000]
    assert monitor.degraded == {RESOURCE_CATALOGUE}


def test_retablissement_restaure_l_intervalle_normal() -> None:
    """La première réussite après échec notifie et revient à l'intervalle configuré."""
    monitor, timers, notifications = make_monitor(
        normal_ms={RESOURCE_CATALOGUE: 60 * 60 * 1000, RESOURCE_FORGE: 240 * 60 * 1000}
    )

    monitor.register_outcome(RESOURCE_CATALOGUE, available=False)
    monitor.register_outcome(RESOURCE_CATALOGUE, available=True)

    assert notifications == [
        (RESOURCE_CATALOGUE, False),
        (RESOURCE_CATALOGUE, True),
    ]
    assert timers[RESOURCE_CATALOGUE].intervals == [3 * 60 * 1000, 60 * 60 * 1000]
    assert monitor.degraded == set()


def test_reussites_repetees_sans_notification() -> None:
    """En état nominal, les réussites successives ne notifient ni ne replanifient."""
    monitor, timers, notifications = make_monitor()

    monitor.register_outcome(RESOURCE_CATALOGUE, available=True)
    monitor.register_outcome(RESOURCE_FORGE, available=True)

    assert notifications == []
    assert timers[RESOURCE_CATALOGUE].intervals == []
    assert timers[RESOURCE_FORGE].intervals == []


def test_degradation_apres_retablissement() -> None:
    """Un nouvel échec après rétablissement redéclenche la dégradation."""
    monitor, _timers, notifications = make_monitor()

    monitor.register_outcome(RESOURCE_FORGE, available=False)
    monitor.register_outcome(RESOURCE_FORGE, available=True)
    monitor.register_outcome(RESOURCE_FORGE, available=False)

    assert notifications == [
        (RESOURCE_FORGE, False),
        (RESOURCE_FORGE, True),
        (RESOURCE_FORGE, False),
    ]
    assert monitor.degraded == {RESOURCE_FORGE}


def test_ressources_independantes() -> None:
    """Catalogue et forge se dégradent et se rétablissent indépendamment."""
    monitor, timers, notifications = make_monitor()

    monitor.register_outcome(RESOURCE_CATALOGUE, available=False)
    monitor.register_outcome(RESOURCE_FORGE, available=False)
    monitor.register_outcome(RESOURCE_CATALOGUE, available=True)

    assert notifications == [
        (RESOURCE_CATALOGUE, False),
        (RESOURCE_FORGE, False),
        (RESOURCE_CATALOGUE, True),
    ]
    assert monitor.degraded == {RESOURCE_FORGE}
    # Le timer forge est bien resté sur l'intervalle de reprise.
    assert timers[RESOURCE_FORGE].intervals == [3 * 60 * 1000]


def test_intervalle_de_reprise_configurable() -> None:
    """L'intervalle de reprise est paramétrable (testé ici avec 5 minutes)."""
    monitor, timers, _notifications = make_monitor(retry_ms=5 * 60 * 1000)
    monitor.register_outcome(RESOURCE_CATALOGUE, available=False)
    assert timers[RESOURCE_CATALOGUE].intervals == [5 * 60 * 1000]
