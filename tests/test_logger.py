"""Tests headless de la coloration console du Logger (formateur + détection).

Aucune écriture réelle sur la console : le formateur est testé sur des
enregistrements construits, et la détection de coloration sur des flux factices.
"""

from __future__ import annotations

import logging

from core.logger import ANSI_RESET, LEVEL_COLORS, ColoredFormatter, console_supports_color


def make_record(level: int, message: str) -> logging.LogRecord:
    """Construit un enregistrement de log minimal pour un niveau donné."""
    return logging.LogRecord(
        name="workstation_tooler",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_ligne_coloree_par_niveau() -> None:
    """Chaque niveau standard encadre la ligne de son code ANSI."""
    formatter = ColoredFormatter("%(levelname)s %(message)s", use_color=True)
    for level, color in LEVEL_COLORS.items():
        line = formatter.format(make_record(level, "boum"))
        assert line.startswith(color)
        assert line.endswith(ANSI_RESET)
        assert "boum" in line


def test_couleurs_distinctes_par_niveau() -> None:
    """DEBUG et CRITICAL notamment portent des couleurs différentes."""
    assert LEVEL_COLORS[logging.DEBUG] != LEVEL_COLORS[logging.CRITICAL]
    assert LEVEL_COLORS[logging.ERROR] != LEVEL_COLORS[logging.WARNING]


def test_sans_couleur_le_formateur_restitu_la_ligne() -> None:
    """use_color=False (fichier, flux non interactif) : aucun code ANSI."""
    formatter = ColoredFormatter("%(levelname)s %(message)s", use_color=False)
    line = formatter.format(make_record(logging.ERROR, "problème"))
    assert line == "ERROR problème"


def test_niveau_inconnu_non_colore() -> None:
    """Un niveau hors table reste inchangé plutôt que de crasher."""
    formatter = ColoredFormatter("%(message)s", use_color=True)
    line = formatter.format(make_record(42, "niveau exotique"))
    assert line == "niveau exotique"


class FakeStream:
    """Flux factice pilotant isatty pour la détection de coloration."""

    def __init__(self, isatty: bool) -> None:
        self._isatty = isatty

    def isatty(self) -> bool:
        return self._isatty


def test_detection_couleur_tty(monkeypatch) -> None:
    """Sans variable d'environnement, seul un flux interactif est coloré."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert console_supports_color(FakeStream(isatty=True)) is True
    assert console_supports_color(FakeStream(isatty=False)) is False


def test_detection_couleur_no_color_prioritaire(monkeypatch) -> None:
    """NO_COLOR désactive la coloration, même sur un tty avec FORCE_COLOR."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert console_supports_color(FakeStream(isatty=True)) is False


def test_detection_couleur_force_color(monkeypatch) -> None:
    """FORCE_COLOR colorise même un flux non interactif (redirection)."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert console_supports_color(FakeStream(isatty=False)) is True
