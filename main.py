"""Point d'entrée principal de Workstation Tooler.

Initialise les singletons du socle (``Logger``, ``EventBus``, ``ConfigLoader``,
``ThreadManager``), charge dynamiquement les modules disponibles dans le
paquet ``modules/`` et démarre l'application PyQt6 avec son icône dans le
SystemTray.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import sys
from pathlib import Path
from types import ModuleType
from typing import List, Type

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox, QStyle

import modules as modules_package
from core.config_loader import ConfigLoader
from core.error_handler import ErrorHandler
from core.event_bus import EventBus
from core.logger import Logger
from core.scheduler import Scheduler
from core.thread_manager import ThreadManager
from modules.base_module import BaseModule
from ui.tray_icon import TrayIcon

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

#: Dossier contenant les icônes du SystemTray (variantes OK/Info/WIP).
ICONS_DIR = Path(__file__).resolve().parent / "resources" / "icons"


def discover_modules() -> List[BaseModule]:
    """Découvre et instancie dynamiquement tous les modules de mise à jour.

    Chaque sous-paquet de ``modules/`` contenant un fichier ``soft_manager.py``
    défini une sous-classe de ``BaseModule`` est automatiquement chargé, sans
    qu'il soit nécessaire de modifier ce fichier pour ajouter un nouvel outil.

    Returns:
        La liste des instances de modules découvertes.
    """
    discovered: List[BaseModule] = []
    package_path = Path(modules_package.__file__).parent

    for module_info in pkgutil.iter_modules([str(package_path)]):
        if not module_info.ispkg:
            continue

        soft_manager_name = f"modules.{module_info.name}.soft_manager"
        try:
            soft_manager: ModuleType = importlib.import_module(soft_manager_name)
        except ModuleNotFoundError:
            continue  # Le sous-paquet ne fournit pas de soft_manager.py.

        module_class: Type[BaseModule] | None = None
        for _, candidate in inspect.getmembers(soft_manager, inspect.isclass):
            is_base_module_subclass = (
                issubclass(candidate, BaseModule) and candidate is not BaseModule
            )
            is_defined_here = candidate.__module__ == soft_manager_name
            if is_base_module_subclass and is_defined_here:
                module_class = candidate
                break

        if module_class is not None:
            discovered.append(module_class())

    return discovered


def load_tray_icons(app: QApplication) -> dict[str, QIcon]:
    """Charge les trois variantes d'icône du SystemTray (OK / Info / WIP).

    Si les fichiers attendus sont absents (ex. non encore générés via
    ``resources/icons/generate_icon_variants.py``), une icône de secours du
    thème Qt est utilisée afin que l'application reste fonctionnelle.

    Args:
        app: Instance de l'application Qt, utilisée pour l'icône de secours.

    Returns:
        Un dictionnaire ``{"ok": QIcon, "info": QIcon, "wip": QIcon}``.
    """
    fallback = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    file_by_state = {
        "ok": ICONS_DIR / "app_icon_ok.ico",
        "info": ICONS_DIR / "app_icon_info.ico",
        "wip": ICONS_DIR / "app_icon_wip.ico",
    }
    return {
        state: QIcon(str(path)) if path.exists() else fallback
        for state, path in file_by_state.items()
    }


def bootstrap() -> tuple[Logger, EventBus, ConfigLoader, ThreadManager, ErrorHandler]:
    """Initialise les singletons du socle applicatif.

    Returns:
        Un tuple contenant les instances uniques du ``Logger``, de
        l'``EventBus``, du ``ConfigLoader``, du ``ThreadManager`` et de
        l'``ErrorHandler``.
    """
    config = ConfigLoader()

    log_level_name = str(config.get_setting("logging.level", default="INFO")).upper()
    logger = Logger(level=LOG_LEVELS.get(log_level_name, logging.INFO))

    event_bus = EventBus()
    thread_manager = ThreadManager()
    error_handler = ErrorHandler()

    logger.info(
        "Socle applicatif initialisé (Logger, EventBus, ConfigLoader, ThreadManager, ErrorHandler)."
    )
    return logger, event_bus, config, thread_manager, error_handler


def main() -> int:
    """Lance l'application Workstation Tooler.

    Returns:
        Le code de sortie du processus.
    """
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    logger, event_bus, config, thread_manager, error_handler = bootstrap()

    loaded_modules = discover_modules()
    for module in loaded_modules:
        module.attach(logger, event_bus, config, thread_manager)

    logger.info(f"{len(loaded_modules)} module(s) chargé(s) : {[m.name for m in loaded_modules]}")

    if not QSystemTrayIconAvailable():
        QMessageBox.critical(
            None, "Workstation Tooler", "Le SystemTray n'est pas disponible sur ce poste."
        )
        return 1

    icons = load_tray_icons(app)
    tray_icon = TrayIcon(modules=loaded_modules, icons=icons)
    tray_icon.setVisible(True)

    scheduler = Scheduler()
    scheduler.configure(modules=loaded_modules)
    scheduler.start()

    exit_code = app.exec()
    scheduler.stop()
    thread_manager.shutdown()
    return exit_code


def QSystemTrayIconAvailable() -> bool:
    """Vérifie la disponibilité du SystemTray sur le poste courant.

    Returns:
        ``True`` si le SystemTray est disponible.
    """
    from PyQt6.QtWidgets import QSystemTrayIcon

    return QSystemTrayIcon.isSystemTrayAvailable()


if __name__ == "__main__":
    sys.exit(main())
