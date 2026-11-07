"""Interface graphique de l'application : icône dans le SystemTray.

Cette interface est volontairement « fine » : elle ne contient aucune
logique métier. Elle déclenche des actions sur l'``AppUpdater`` ou sur
l'``UpdateEngine`` (qui délèguent eux-mêmes au ``ThreadManager``) et réagit
aux signaux de l'``EventBus`` pour informer l'utilisateur et refléter l'état
courant via l'icône (OK / Info / WIP).

Structure du menu contextuel :
    Mise à jour Application
    Vérifier les mises à jour
    Tout mettre à jour
    ------------------------
    Mettre à jour           > <application 1> | <application 2> | ...
    Réappliquer la config   > <application 1> | <application 2> | ...
    ------------------------
    Quitter

Les sous-menus d'applications sont (re)construits à réception du signal
``catalog_loaded`` : le contenu du menu reflète le catalogue distant.
"""

from __future__ import annotations

from typing import Dict, List, Set

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon, QWidget

from core.app_updater import AppUpdater
from core.error_handler import ErrorHandler
from core.event_bus import EventBus
from core.logger import Logger
from engine.update_engine import UpdateEngine


class TrayIcon(QSystemTrayIcon):
    """Icône du SystemTray exposant les actions du moteur de mise à jour."""

    def __init__(
        self,
        engine: UpdateEngine,
        icons: Dict[str, QIcon],
        parent: QWidget | None = None,
    ) -> None:
        """Construit le menu contextuel autour du moteur de mise à jour.

        Args:
            engine: Moteur de mise à jour branché sur le catalogue distant.
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
        self._engine = engine

        #: Applications actives du catalogue, nom technique -> libellé UI.
        self._applications: Dict[str, str] = {}

        self._active_tasks: Set[str] = set()
        self._pending_updates: Set[str] = set()

        self.setToolTip("Workstation Tooler")
        self._build_menu()
        self._connect_event_bus()
        self._refresh_icon()

    # ------------------------------------------------------------------
    # Construction du menu (reconstruit à chaque chargement de catalogue).
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        """Construit le menu contextuel : mises à jour, puis actions par application."""
        menu = QMenu()

        update_app_action = QAction("Mise à jour Application", menu)
        update_app_action.triggered.connect(self._on_update_app)
        menu.addAction(update_app_action)

        check_action = QAction("Vérifier les mises à jour", menu)
        check_action.triggered.connect(self._on_check_updates)
        menu.addAction(check_action)

        update_all_action = QAction("Tout mettre à jour", menu)
        update_all_action.triggered.connect(self._on_update_all)
        menu.addAction(update_all_action)

        menu.addSeparator()

        self._add_application_submenu(menu, "Mettre à jour", self._on_update_application)
        self._add_application_submenu(
            menu, "Réappliquer la config", self._on_reconfigure_application
        )

        menu.addSeparator()

        quit_action = QAction("Quitter", menu)
        quit_action.triggered.connect(self._on_quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)

    def _add_application_submenu(self, menu: QMenu, title: str, on_triggered) -> None:
        """Ajoute un sous-menu contenant une entrée par application du catalogue.

        Tant que le catalogue n'est pas chargé, le sous-menu affiche une
        entrée désactivée informant du chargement en cours.

        Args:
            menu: Menu parent auquel ajouter le sous-menu.
            title: Libellé du sous-menu (ex. ``"Mettre à jour"``).
            on_triggered: Fonction appelée avec le nom de l'application
                sélectionnée.
        """
        submenu = menu.addMenu(title)
        if not self._applications:
            placeholder = QAction("Catalogue en cours de chargement…", submenu)
            placeholder.setEnabled(False)
            submenu.addAction(placeholder)
            return

        for name, display_name in self._applications.items():
            action = QAction(display_name, submenu)
            action.triggered.connect(lambda _checked=False, app_name=name: on_triggered(app_name))
            submenu.addAction(action)

    def _connect_event_bus(self) -> None:
        """Connecte les signaux de l'``EventBus`` aux réactions de l'UI."""
        self._event_bus.error_occurred.connect(self._on_error_occurred)
        self._event_bus.update_finished.connect(self._on_update_finished)
        self._event_bus.update_available.connect(self._on_update_available)
        self._event_bus.catalog_loaded.connect(self._on_catalog_loaded)
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

    def _on_check_updates(self, *_args) -> None:
        """Déclenche la vérification des mises à jour de toutes les applications."""
        self._engine.start_check_updates(
            on_result=self._on_check_result,
            on_error=lambda exc: self._error_handler.handle_exception(exc, context="moteur"),
        )

    def _on_check_result(self, status: dict) -> None:
        """Informe l'utilisateur lorsque la vérification ne trouve rien à faire."""
        updates: List[str] = status.get("updates_available", [])
        if not updates:
            self.showMessage(
                "Workstation Tooler",
                "Aucune mise à jour disponible.",
                QSystemTrayIcon.MessageIcon.Information,
            )

    def _on_update_all(self, *_args) -> None:
        """Déclenche la mise à jour de toutes les applications obsolètes ou absentes."""
        self._engine.start_update_all(
            on_result=self._on_update_all_result,
            on_error=lambda exc: self._error_handler.handle_exception(exc, context="moteur"),
        )

    def _on_update_all_result(self, results: dict) -> None:
        """Résume le résultat global des mises à jour en une notification."""
        if not results:
            self.showMessage(
                "Workstation Tooler",
                "Aucune mise à jour disponible.",
                QSystemTrayIcon.MessageIcon.Information,
            )
            return
        success = all(results.values())
        succeeded = sum(1 for ok in results.values() if ok)
        message = (
            f"Mises à jour terminées : {succeeded}/{len(results)} réussie(s)."
            if success
            else f"Mises à jour terminées avec échecs : {succeeded}/{len(results)} réussie(s)."
        )
        self._event_bus.update_finished.emit("global", success, message)

    def _on_update_application(self, application: str) -> None:
        """Déclenche la mise à jour d'une application du catalogue."""
        self._engine.start_update_application(
            application,
            on_result=lambda success, name=application: self._event_bus.update_finished.emit(
                name,
                success,
                "Mise à jour terminée." if success else "Mise à jour en échec.",
            ),
            on_error=lambda exc, name=application: self._error_handler.handle_exception(
                exc, context=name
            ),
        )

    def _on_reconfigure_application(self, application: str) -> None:
        """Réapplique la configuration (actions ``ensure_content``) d'une application."""
        self._engine.start_reconfigure_application(
            application,
            on_result=lambda success, name=application: self._event_bus.update_finished.emit(
                name,
                success,
                "Configuration réappliquée." if success else "Reconfiguration en échec.",
            ),
            on_error=lambda exc, name=application: self._error_handler.handle_exception(
                exc, context=name
            ),
        )

    # ------------------------------------------------------------------
    # Réactions aux signaux de l'EventBus.
    # ------------------------------------------------------------------

    def _on_catalog_loaded(self, applications: list) -> None:
        """Remplace les sous-menus d'applications par le contenu du catalogue chargé."""
        self._applications = {entry["name"]: entry["display_name"] for entry in applications}
        self._logger.info(
            f"[tray] catalogue reçu : {sorted(self._applications)} ; reconstruction du menu."
        )
        self._build_menu()

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

    def _on_module_status_changed(self, target_name: str, status: str) -> None:
        """Journalise les changements de statut d'une cible (application, catalogue)."""
        self._logger.info(f"[{target_name}] statut -> {status}")

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
