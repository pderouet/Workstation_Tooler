"""Interface graphique de l'application : icône dans le SystemTray.

Cette interface est volontairement « fine » : elle ne contient aucune
logique métier. Elle se contente de déclencher des actions (sur l'``AppUpdater``
ou sur les modules, qui délèguent elles-mêmes au ``ThreadManager``) et de
réagir aux signaux de l'``EventBus`` pour informer l'utilisateur et refléter
l'état courant via l'icône (OK / Info / WIP).

Structure du menu contextuel :
    Mise à jour Application
    ------------------------
    Installation      > <module 1> | <module 2> | ...
    Désinstallation   > <module 1> | <module 2> | ...
    Réinstallation    > <module 1> | <module 2> | ...
    Reconfigurer      > <module 1> | <module 2> | ...
    ------------------------
    Quitter
"""

from __future__ import annotations

from typing import Dict, List, Set

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon, QWidget

from core.app_updater import AppUpdater
from core.error_handler import ErrorHandler
from core.event_bus import EventBus
from core.logger import Logger
from modules.base_module import BaseModule


class TrayIcon(QSystemTrayIcon):
    """Icône du SystemTray exposant les actions de gestion des modules."""

    def __init__(
        self,
        modules: List[BaseModule],
        icons: Dict[str, QIcon],
        parent: QWidget | None = None,
    ) -> None:
        """Construit le menu contextuel à partir des modules chargés.

        Args:
            modules: Liste des modules de mise à jour déjà attachés au socle.
            icons: Dictionnaire des icônes d'état, avec les clés ``"ok"``,
                ``"info"`` et ``"wip"``.
            parent: Widget parent optionnel.
        """
        super().__init__(icons["ok"], parent)
        self._icons = icons
        self._logger = Logger()
        self._event_bus = EventBus()
        self._error_handler = ErrorHandler()
        self._app_updater = AppUpdater()
        self._modules: Dict[str, BaseModule] = {module.name: module for module in modules}

        self._active_tasks: Set[str] = set()
        self._pending_updates: Set[str] = set()

        self.setToolTip("Workstation Tooler")
        self._build_menu()
        self._connect_event_bus()
        self._refresh_icon()

    def _build_menu(self) -> None:
        """Construit le menu contextuel : mise à jour appli, puis actions par module."""
        menu = QMenu()

        update_app_action = QAction("Mise à jour Application", menu)
        update_app_action.triggered.connect(self._on_update_app)
        menu.addAction(update_app_action)

        menu.addSeparator()

        self._add_module_submenu(
            menu, "Installation", lambda m: self._on_module_action(m, "install")
        )
        self._add_module_submenu(
            menu, "Désinstallation", lambda m: self._on_module_action(m, "uninstall")
        )
        self._add_module_submenu(
            menu, "Réinstallation", lambda m: self._on_module_action(m, "reinstall")
        )
        self._add_module_submenu(
            menu, "Reconfigurer", lambda m: self._on_module_action(m, "reconfigure")
        )

        menu.addSeparator()

        quit_action = QAction("Quitter", menu)
        quit_action.triggered.connect(self._on_quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _add_module_submenu(self, menu: QMenu, title: str, on_triggered) -> None:
        """Ajoute un sous-menu contenant une entrée par module chargé.

        Args:
            menu: Menu parent auquel ajouter le sous-menu.
            title: Libellé du sous-menu (ex. ``"Installation"``).
            on_triggered: Fonction appelée avec le module sélectionné.
        """
        submenu = menu.addMenu(title)
        for module in self._modules.values():
            action = QAction(module.display_name, submenu)
            action.triggered.connect(lambda _checked=False, m=module: on_triggered(m))
            submenu.addAction(action)

    def _connect_event_bus(self) -> None:
        """Connecte les signaux de l'``EventBus`` aux réactions de l'UI."""
        self._event_bus.error_occurred.connect(self._on_error_occurred)
        self._event_bus.update_finished.connect(self._on_update_finished)
        self._event_bus.update_available.connect(self._on_update_available)
        self._event_bus.module_status_changed.connect(self._on_module_status_changed)
        self._event_bus.task_started.connect(self._on_task_started)
        self._event_bus.task_finished.connect(self._on_task_finished)

    # ------------------------------------------------------------------
    # Actions déclenchées par le menu.
    # ------------------------------------------------------------------

    def _on_update_app(self, *_args) -> None:
        """Déclenche la vérification puis la mise à jour de l'application."""

        def _after_check(status: dict) -> None:
            if not status.get("update_available"):
                self.showMessage(
                    "Workstation Tooler",
                    "Aucune mise à jour disponible.",
                    QSystemTrayIcon.MessageIcon.Information,
                )
                return
            self._app_updater.start_update(
                on_result=lambda success: self._event_bus.update_finished.emit(
                    "app",
                    success,
                    "Mise à jour de l'application terminée."
                    if success
                    else "Échec de la mise à jour.",
                ),
                on_error=lambda exc: self._error_handler.handle_exception(exc, context="app"),
            )

        self._app_updater.start_check_update(
            on_result=_after_check,
            on_error=lambda exc: self._error_handler.handle_exception(exc, context="app"),
        )

    def _on_module_action(self, module: BaseModule, action: str) -> None:
        """Déclenche une action de cycle de vie (install/uninstall/reinstall/reconfigure).

        Args:
            module: Module concerné.
            action: Nom de l'action (``"install"``, ``"uninstall"``,
                ``"reinstall"`` ou ``"reconfigure"``).
        """
        action_labels = {
            "install": "Installation",
            "uninstall": "Désinstallation",
            "reinstall": "Réinstallation",
            "reconfigure": "Reconfiguration",
        }
        starters = {
            "install": module.start_install,
            "uninstall": module.start_uninstall,
            "reinstall": module.start_reinstall,
            "reconfigure": module.start_reconfigure,
        }
        label = action_labels[action]
        starter = starters[action]

        starter(
            on_result=lambda success, m=module, lbl=label: self._event_bus.update_finished.emit(
                m.name, success, f"{lbl} terminée." if success else f"{lbl} en échec."
            ),
            on_error=lambda exc, m=module: self._error_handler.handle_exception(
                exc, context=m.name
            ),
        )

    # ------------------------------------------------------------------
    # Réactions aux signaux de l'EventBus.
    # ------------------------------------------------------------------

    def _on_update_finished(self, target_name: str, success: bool, message: str) -> None:
        """Affiche une notification de fin d'opération et met à jour l'état des mises à jour en attente."""
        icon = (
            QSystemTrayIcon.MessageIcon.Information
            if success
            else QSystemTrayIcon.MessageIcon.Warning
        )
        self.showMessage(target_name, message, icon)
        if success:
            self._pending_updates.discard(target_name)
            self._refresh_icon()

    def _on_update_available(
        self, target_name: str, current_version: str, latest_version: str
    ) -> None:
        """Enregistre qu'une mise à jour est disponible et notifie l'utilisateur."""
        self._pending_updates.add(target_name)
        self._refresh_icon()
        self.showMessage(
            target_name,
            f"Mise à jour disponible : {current_version} -> {latest_version}",
            QSystemTrayIcon.MessageIcon.Information,
        )

    def _on_module_status_changed(self, module_name: str, status: str) -> None:
        """Journalise les changements de statut d'un module."""
        self._logger.info(f"[{module_name}] statut -> {status}")

    def _on_error_occurred(self, title: str, message: str) -> None:
        """Affiche une erreur applicative sous forme de notification."""
        self.showMessage(title, message, QSystemTrayIcon.MessageIcon.Critical)

    def _on_task_started(self, task_name: str) -> None:
        """Marque une tâche de fond comme active et bascule l'icône en WIP."""
        self._active_tasks.add(task_name)
        self._refresh_icon()

    def _on_task_finished(self, task_name: str) -> None:
        """Marque une tâche de fond comme terminée et restaure l'icône d'état stable."""
        self._active_tasks.discard(task_name)
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        """Choisit l'icône à afficher selon l'état courant (WIP > Info > OK)."""
        if self._active_tasks:
            self.setIcon(self._icons["wip"])
        elif self._pending_updates:
            self.setIcon(self._icons["info"])
        else:
            self.setIcon(self._icons["ok"])

    def _on_quit(self) -> None:
        """Ferme proprement l'application."""
        from PyQt6.QtWidgets import QApplication

        confirmation = QMessageBox.question(
            None,
            "Quitter",
            "Voulez-vous vraiment quitter Workstation Tooler ?",
        )
        if confirmation == QMessageBox.StandardButton.Yes:
            QApplication.quit()
