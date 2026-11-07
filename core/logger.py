"""Singleton Logger de l'application.

Toute sortie de log doit transiter par ce module afin de garantir un
format homogène et la présence systématique du nom/ID du thread émetteur,
condition indispensable au diagnostic dans une application fortement
multi-threadée (opérations I/O déléguées au ``ThreadManager``).

Les sorties console sont colorées par niveau (ANSI) lorsque le terminal le
supporte : la variable d'environnement ``NO_COLOR`` les désactive,
``FORCE_COLOR`` les force, et un flux non interactif (redirection, tube,
journal de service) n'est jamais coloré. Le fichier de log, lui, reste
strictement monochrome.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional, TextIO

from core import SingletonMeta

DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(thread_name)s] %(message)s"

#: Codes ANSI de coloration de la ligne, par niveau (console uniquement).
LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # vert
    logging.WARNING: "\033[33m",  # jaune
    logging.ERROR: "\033[31m",  # rouge
    logging.CRITICAL: "\033[1;31m",  # rouge gras
}

#: Code ANSI de réinitialisation des attributs d'affichage.
ANSI_RESET = "\033[0m"


def console_supports_color(stream: Optional[TextIO] = None) -> bool:
    """Indique si un flux console mérite la coloration ANSI.

    Priorité : ``NO_COLOR`` (convention https://no-color.org) désactive
    systématiquement, ``FORCE_COLOR`` force, sinon seule un flux interactif
    (tty) est coloré — les redirections et tubes restent monochromes.

    Args:
        stream: Flux à inspecter (défaut : ``sys.stderr``, cible du handler
            console du logger).

    Returns:
        ``True`` si la coloration doit être activée.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream if stream is not None else sys.stderr
    isatty = getattr(stream, "isatty", None)
    return bool(isatty()) if callable(isatty) else False


class ColoredFormatter(logging.Formatter):
    """Formateur colorant la ligne complète selon le niveau du message.

    Args:
        fmt: Chaîne de format (identique à ``logging.Formatter``).
        use_color: Active la coloration ANSI (décidé par l'appelant selon
            la nature du flux de sortie).
    """

    def __init__(self, fmt: str, use_color: bool = True) -> None:
        """Initialise le formateur avec le choix de coloration."""
        super().__init__(fmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        """Formate l'enregistrement, la ligne entière étant colorée si activé.

        Args:
            record: Enregistrement à formater.

        Returns:
            La ligne formatée, avec codes ANSI d'encadrement le cas échéant.
        """
        message = super().format(record)
        if not self._use_color:
            return message
        color = LEVEL_COLORS.get(record.levelno)
        if color is None:
            return message
        return f"{color}{message}{ANSI_RESET}"


class _ThreadNameFilter(logging.Filter):
    """Filtre injectant le nom du thread courant dans chaque enregistrement."""

    def filter(self, record: logging.LogRecord) -> bool:
        current = threading.current_thread()
        record.thread_name = f"{current.name}:{current.ident}"
        return True


class Logger(metaclass=SingletonMeta):
    """Logger applicatif unique, accessible depuis n'importe quel thread.

    Exemple :
        >>> Logger().info("Démarrage de l'application")
    """

    def __init__(
        self,
        log_file: Optional[Path] = None,
        level: int = logging.INFO,
    ) -> None:
        """Initialise le logger sous-jacent (``logging.Logger``) une seule fois.

        Args:
            log_file: Chemin optionnel d'un fichier de log. Si fourni, les
                messages sont également écrits dans ce fichier (sans couleur).
            level: Niveau de log minimal (``logging.INFO`` par défaut).
        """
        if os.name == "nt":
            # Active l'interprétation des séquences ANSI par la console
            # Windows (mode terminal virtuel) ; sans effet ailleurs.
            os.system("")

        self._logger = logging.getLogger("workstation_tooler")
        self._logger.setLevel(level)
        self._logger.addFilter(_ThreadNameFilter())

        if not self._logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                ColoredFormatter(DEFAULT_LOG_FORMAT, use_color=console_supports_color())
            )
            self._logger.addHandler(console_handler)

            if log_file is not None:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT))
                self._logger.addHandler(file_handler)

    def configure(self, log_file: Optional[Path] = None, level: Optional[int] = None) -> None:
        """Reconfigure le logger après sa création initiale (ex. via la config).

        Args:
            log_file: Fichier de log additionnel à ajouter, le cas échéant.
            level: Nouveau niveau de log à appliquer.
        """
        if level is not None:
            self._logger.setLevel(level)

        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            formatter = logging.Formatter(DEFAULT_LOG_FORMAT)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

    def debug(self, message: str) -> None:
        """Journalise un message de niveau DEBUG."""
        self._logger.debug(message)

    def info(self, message: str) -> None:
        """Journalise un message de niveau INFO."""
        self._logger.info(message)

    def warning(self, message: str) -> None:
        """Journalise un message de niveau WARNING."""
        self._logger.warning(message)

    def error(self, message: str) -> None:
        """Journalise un message de niveau ERROR."""
        self._logger.error(message)

    def critical(self, message: str) -> None:
        """Journalise un message de niveau CRITICAL."""
        self._logger.critical(message)
