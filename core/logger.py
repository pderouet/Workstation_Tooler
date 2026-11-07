"""Singleton Logger de l'application.

Toute sortie de log doit transiter par ce module afin de garantir un
format homogène et la présence systématique du nom/ID du thread émetteur,
condition indispensable au diagnostic dans une application fortement
multi-threadée (opérations I/O déléguées au ``ThreadManager``).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from core import SingletonMeta

DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(thread_name)s] %(message)s"


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
                messages sont également écrits dans ce fichier.
            level: Niveau de log minimal (``logging.INFO`` par défaut).
        """
        self._logger = logging.getLogger("workstation_tooler")
        self._logger.setLevel(level)
        self._logger.addFilter(_ThreadNameFilter())

        if not self._logger.handlers:
            formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self._logger.addHandler(console_handler)

            if log_file is not None:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(log_file, encoding="utf-8")
                file_handler.setFormatter(formatter)
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
