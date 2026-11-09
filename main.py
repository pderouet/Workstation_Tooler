"""Point d'entrée principal de Workstation Tooler.

Initialise les singletons du socle (``Logger``, ``EventBus``, ``ConfigLoader``,
``ThreadManager``), construit le moteur de mise à jour branché sur le chemin
réseau du catalogue (``repository.uri`` de ``settings.yaml``) et démarre
l'application PyQt6 avec son icône dans le SystemTray.

Les applications gérées ne sont plus des modules Python : elles sont découvertes
dynamiquement depuis le catalogue distant (voir ``docs/moteur_mise_a_jour.md``).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional, Tuple

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox, QStyle

from core.config_loader import PROJECT_ROOT, ConfigLoader
from core.error_handler import ErrorHandler
from core.event_bus import EventBus
from core.logger import Logger
from core.scheduler import Scheduler
from core.thread_manager import ThreadManager
from engine.repository import RemoteRepository
from engine.storage import DEFAULT_TIMEOUT_SECONDS, build_storage_backend
from engine.update_engine import UpdateEngine
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


def load_tray_icons(app: QApplication) -> dict[str, QIcon]:
    """Charge les variantes d'icône du SystemTray (OK / Info / WIP / Erreur).

    Si les fichiers attendus sont absents (ex. non encore générés via
    ``resources/icons/generate_icon_variants.py``), une icône de secours du
    thème Qt est utilisée afin que l'application reste fonctionnelle.

    Args:
        app: Instance de l'application Qt, utilisée pour l'icône de secours.

    Returns:
        Un dictionnaire ``{"ok", "info", "wip", "error"}`` d'icônes.
    """
    fallback = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    error_fallback = app.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)
    file_by_state = {
        "ok": (ICONS_DIR / "app_icon_ok.ico", fallback),
        "info": (ICONS_DIR / "app_icon_info.ico", fallback),
        "wip": (ICONS_DIR / "app_icon_wip.ico", fallback),
        "error": (ICONS_DIR / "app_icon_err.ico", error_fallback),
    }
    return {
        state: QIcon(str(path)) if path.exists() else state_fallback
        for state, (path, state_fallback) in file_by_state.items()
    }


def bootstrap(
    config: Optional[ConfigLoader] = None,
) -> Tuple[Logger, EventBus, ConfigLoader, ThreadManager, ErrorHandler]:
    """Initialise les singletons du socle applicatif.

    Le niveau de log et le fichier de journal (``logging.level`` et
    ``logging.file`` de la configuration) sont appliqués ici : le fichier
    (relatif à la racine du projet ou absolu) est créé au premier lancement,
    ce qui garantit des journaux persistants même sans console (``pythonw``
    sous Windows).

    Args:
        config: Configuration à utiliser (défaut : le ``ConfigLoader``
            singleton sur ``config/settings.yaml``) — injectable pour les
            tests.

    Returns:
        Un tuple contenant les instances uniques du ``Logger``, de
        l'``EventBus``, du ``ConfigLoader``, du ``ThreadManager`` et de
        l'``ErrorHandler``.
    """
    config = config or ConfigLoader()

    log_level = LOG_LEVELS.get(
        str(config.get_setting("logging.level", default="INFO")).upper(), logging.INFO
    )
    logger = Logger()
    logger.configure(log_file=_log_file_path(config), level=log_level)

    event_bus = EventBus()
    thread_manager = ThreadManager()
    error_handler = ErrorHandler()

    logger.info(
        "Socle applicatif initialisé (Logger, EventBus, ConfigLoader, ThreadManager, ErrorHandler)."
    )
    return logger, event_bus, config, thread_manager, error_handler


def _log_file_path(config: ConfigLoader) -> Optional[Path]:
    """Résout le chemin du fichier de journal depuis la configuration.

    Args:
        config: Configuration générale.

    Returns:
        Le chemin (relatif ramené à la racine du projet), ou ``None`` si la
        clé ``logging.file`` est absente ou vide.
    """
    value = config.get_setting("logging.file")
    if not value:
        return None
    log_path = Path(str(value))
    return log_path if log_path.is_absolute() else PROJECT_ROOT / log_path


def build_repository(config: ConfigLoader) -> RemoteRepository:
    """Construit le repository du catalogue depuis la section ``repository``.

    Le schéma de l'URI détermine le backend : ``smb://`` pour un partage SMB,
    ``file://`` (ou un chemin nu) pour un catalogue local (développement,
    tests).

    Args:
        config: Configuration générale de l'application.

    Returns:
        Le repository prêt à interroger le catalogue.
    """
    uri = str(config.get_setting("repository.uri", default=""))
    if not uri:
        raise ValueError(
            "Aucun chemin de catalogue configuré : renseignez 'repository.uri' "
            "dans config/settings.yaml."
        )
    backend = build_storage_backend(
        uri,
        username=str(config.get_setting("repository.username", default="") or ""),
        domain=str(config.get_setting("repository.domain", default="") or ""),
        timeout_seconds=int(
            config.get_setting("repository.timeout_seconds", default=DEFAULT_TIMEOUT_SECONDS)
        ),
    )
    return RemoteRepository(backend)


def main() -> int:
    """Lance l'application Workstation Tooler.

    Returns:
        Le code de sortie du processus.
    """
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    logger, event_bus, config, thread_manager, error_handler = bootstrap()

    repository = build_repository(config)
    engine = UpdateEngine(
        logger=logger,
        event_bus=event_bus,
        thread_manager=thread_manager,
        repository=repository,
    )

    if not QSystemTrayIconAvailable():
        QMessageBox.critical(
            None, "Workstation Tooler", "Le SystemTray n'est pas disponible sur ce poste."
        )
        return 1

    icons = load_tray_icons(app)
    tray_icon = TrayIcon(engine=engine, icons=icons)
    tray_icon.setVisible(True)

    # Chargement asynchrone du catalogue : l'UI se peuple via catalog_loaded.
    engine.start_load_catalog(
        on_result=lambda _catalog: None,
        on_error=lambda exc: error_handler.handle_exception(exc, context="catalogue"),
    )

    scheduler = Scheduler()
    scheduler.configure(engine=engine)
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
