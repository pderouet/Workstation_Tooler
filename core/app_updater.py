"""Singleton AppUpdater : mise à jour de l'application Workstation Tooler elle-même.

Compare la version déployée sur le poste (``version.txt`` à la racine du
projet) à la dernière version disponible sur la forge source, puis déclenche
la mise à jour via le script autonome ``updater.py`` (voir
``docs/maj_application.md``).

Toute la chaîne repose sur de simples appels HTTP à la forge — aucune commande
Git n'est exécutée. Deux fournisseurs sont supportés (``forge.provider`` de
``settings.yaml``) :
    - ``github`` (défaut) : fichier brut ``version.txt`` via
      ``raw.githubusercontent.com`` (dépôt public) et archive de la branche via
      l'API tarball ; jeton optionnel ``WORKSTATION_TOOLER_GITHUB_TOKEN`` si le
      dépôt redevient privé ;
    - ``gitlab`` : API v4 en lecture (ID de projet + branche + token en
      lecture seule, voir :data:`GITLAB_READ_TOKEN`).

Le report « Pas aujourd'hui » est une mémoire d'exécution : il disparaît à
l'arrêt du programme, la question est reposée au prochain lancement.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core import SingletonMeta
from core.config_loader import PROJECT_ROOT, ConfigLoader
from core.event_bus import EventBus
from core.logger import Logger
from core.thread_manager import ThreadManager
from engine.version import compare_versions

#: Nom du fichier de version, incrémenté par la CI à chaque push sur la branche principale.
VERSION_FILE_NAME = "version.txt"

#: Nom du script autonome de mise à jour, à la racine du projet.
UPDATER_SCRIPT_NAME = "updater.py"

#: Format de version attendu dans ``version.txt`` (ex. ``0.1.3``).
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

#: Délai maximal des requêtes HTTP (secondes).
HTTP_TIMEOUT_SECONDS = 15

#: Token d'accès GitLab en LECTURE SEULE utilisé pour interroger la version
#: distante et télécharger l'archive de mise à jour.
#:
#: DÉROGATION ASSUMÉE à la règle « aucun secret en dur » d'AGENTS.md :
#: décision du propriétaire du projet, documentée dans ``docs/maj_application.md``.
#: La porter atteinte uniquement à un jeton de rôle minimal (lecture de
#: l'API et du dépôt — ex. rôle « Reporter » avec scope ``read_api`` /
#: ``read_repository``).
#:
#: ATTENTION : le dépôt étant PUBLIC, toute valeur renseignée ici sera exposée
#: au monde entier au premier commit. Lui préférer la variable d'environnement
#: ``WORKSTATION_TOOLER_GITLAB_TOKEN`` (voir :func:`gitlab_read_token`) et
#: laisser cette constante vide.
GITLAB_READ_TOKEN = ""

#: Variable d'environnement prioritaire sur :data:`GITLAB_READ_TOKEN`
#: (recommandée : le dépôt étant public, un token committé serait exposé).
GITLAB_TOKEN_ENV_VAR = "WORKSTATION_TOOLER_GITLAB_TOKEN"

#: Variable d'environnement optionnelle : jeton GitHub si le dépôt redevient
#: privé (inutile tant que le dépôt est public).
GITHUB_TOKEN_ENV_VAR = "WORKSTATION_TOOLER_GITHUB_TOKEN"

#: Ouvreur d'URL (injectable pour les tests).
UrlOpener = Callable[..., Any]


def gitlab_read_token() -> str:
    """Retourne le token GitLab en lecture : variable d'environnement prioritaire.

    Returns:
        La valeur de ``WORKSTATION_TOOLER_GITLAB_TOKEN``, sinon la constante
        :data:`GITLAB_READ_TOKEN` (chaîne vide si aucune source n'est renseignée).
    """
    return os.environ.get(GITLAB_TOKEN_ENV_VAR, "").strip() or GITLAB_READ_TOKEN


def github_read_token() -> str:
    """Retourne le jeton GitHub optionnel (chaîne vide si le dépôt est public).

    Returns:
        La valeur de ``WORKSTATION_TOOLER_GITHUB_TOKEN`` si renseignée.
    """
    return os.environ.get(GITHUB_TOKEN_ENV_VAR, "").strip()


def http_get_text(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = HTTP_TIMEOUT_SECONDS,
    opener: UrlOpener = urllib.request.urlopen,
) -> str:
    """Télécharge une ressource texte par HTTP GET (stdlib ``urllib``).

    Args:
        url: URL de la ressource.
        headers: En-têtes additionnels (authentification, etc.).
        timeout: Délai maximal de la requête (secondes).
        opener: Ouvreur d'URL (injectable pour les tests).

    Returns:
        Le corps de la réponse, décodé en UTF-8.

    Raises:
        OSError: En cas d'erreur HTTP/réseau (``URLError``/``HTTPError``).
    """
    request = urllib.request.Request(url, headers=headers or {})
    with opener(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def read_current_version(version_file: Path) -> Optional[str]:
    """Lit et valide la version locale depuis le fichier ``version.txt``.

    Args:
        version_file: Chemin du fichier de version.

    Returns:
        La version (``x.y.z``), ou ``None`` si le fichier est absent,
        illisible ou mal formé.
    """
    try:
        content = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return content if VERSION_PATTERN.match(content) else None


def _validated_version(body: str) -> str:
    """Valide un contenu ``version.txt`` distant.

    Args:
        body: Corps téléchargé.

    Returns:
        La version (``x.y.z``).

    Raises:
        ValueError: Si le contenu est mal formé.
    """
    version = body.strip()
    if not VERSION_PATTERN.match(version):
        raise ValueError(f"version.txt distant invalide : {version!r}")
    return version


def fetch_latest_version_github(
    repository: str,
    branch: str,
    token: str = "",
    opener: UrlOpener = urllib.request.urlopen,
    timeout: int = HTTP_TIMEOUT_SECONDS,
) -> str:
    """Interroge la version distante via le fichier brut GitHub (HTTP).

    Args:
        repository: Dépôt GitHub au format ``propriétaire/dépôt``.
        branch: Branche suivie (ex. ``main``).
        token: Jeton optionnel (dépôt privé) envoyé en ``Authorization: Bearer``.
        opener: Ouvreur d'URL (injectable pour les tests).
        timeout: Délai maximal de la requête (secondes).

    Returns:
        La version distante (``x.y.z``).

    Raises:
        ValueError: Si le dépôt est mal formé ou le contenu distant invalide.
        OSError: En cas d'erreur HTTP/réseau.
    """
    if "/" not in repository:
        raise ValueError(f"dépôt GitHub mal formé : {repository!r} (attendu 'propriétaire/dépôt').")
    url = f"https://raw.githubusercontent.com/{repository}/{branch}/{VERSION_FILE_NAME}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return _validated_version(http_get_text(url, headers=headers, timeout=timeout, opener=opener))


def fetch_latest_version_gitlab(
    base_url: str,
    project_id: str,
    branch: str,
    token: str,
    opener: UrlOpener = urllib.request.urlopen,
    timeout: int = HTTP_TIMEOUT_SECONDS,
) -> str:
    """Interroge la version distante via l'API v4 de GitLab (lecture seule).

    Args:
        base_url: Racine de l'instance GitLab (ex. ``https://gitlab.example.com``).
        project_id: Identifiant numérique du projet.
        branch: Branche suivie (ex. ``main``).
        token: Jeton d'accès en lecture (en-tête ``PRIVATE-TOKEN``).
        opener: Ouvreur d'URL (injectable pour les tests).
        timeout: Délai maximal de la requête (secondes).

    Returns:
        La version distante (``x.y.z``).

    Raises:
        ValueError: Si la configuration est incomplète ou le contenu mal formé.
        OSError: En cas d'erreur HTTP/réseau (``URLError``/``HTTPError``).
    """
    if not project_id:
        raise ValueError("configuration GitLab incomplète : 'forge.gitlab.project_id' vide.")
    if not token:
        raise ValueError(
            "configuration GitLab incomplète : token absent "
            f"(constante GITLAB_READ_TOKEN ou variable {GITLAB_TOKEN_ENV_VAR})."
        )

    from urllib.parse import quote

    url = (
        f"{base_url.rstrip('/')}/api/v4/projects/{project_id}"
        f"/repository/files/{VERSION_FILE_NAME}/raw?ref={quote(branch, safe='')}"
    )
    return _validated_version(
        http_get_text(url, headers={"PRIVATE-TOKEN": token}, timeout=timeout, opener=opener)
    )


def github_archive_url(repository: str, branch: str) -> str:
    """Construit l'URL d'archive tarball d'une branche GitHub.

    L'API renvoie une redirection signée vers ``codeload`` : elle fonctionne
    anonymement (dépôt public) comme avec le jeton GitHub (dépôt privé).

    Args:
        repository: Dépôt au format ``propriétaire/dépôt``.
        branch: Branche à archiver.

    Returns:
        L'URL de l'archive ``tar.gz``.
    """
    return f"https://api.github.com/repos/{repository}/tarball/{branch}"


def gitlab_archive_url(base_url: str, project_id: str, branch: str) -> str:
    """Construit l'URL d'archive tar.gz d'une branche GitLab (API v4).

    Args:
        base_url: Racine de l'instance GitLab.
        project_id: Identifiant numérique du projet.
        branch: Branche à archiver.

    Returns:
        L'URL de l'archive (le jeton, lui, passe par l'en-tête ``PRIVATE-TOKEN``).
    """
    return (
        f"{base_url.rstrip('/')}/api/v4/projects/{project_id}"
        f"/repository/archive.tar.gz?sha={branch}"
    )


class AppUpdater(metaclass=SingletonMeta):
    """Gère la vérification et l'exécution de la mise à jour de l'application.

    Exemple :
        >>> AppUpdater().start_check_update(on_result=lambda status: print(status))
    """

    def __init__(self) -> None:
        """Connecte le composant aux singletons du socle (logger, bus, threads, config)."""
        self._logger = Logger()
        self._event_bus = EventBus()
        self._thread_manager = ThreadManager()
        self._config = ConfigLoader()
        #: Report « Pas aujourd'hui » : mémoire d'exécution uniquement,
        #: réinitialisée naturellement au redémarrage du programme.
        self._update_dismissed = False

    # ------------------------------------------------------------------
    # Versions locale et distante.
    # ------------------------------------------------------------------

    def get_current_version(self) -> Optional[str]:
        """Retourne la version actuellement déployée sur le poste.

        Returns:
            La version lue dans ``version.txt``, ou ``None`` si indisponible.
        """
        return read_current_version(PROJECT_ROOT / VERSION_FILE_NAME)

    def get_latest_version(self) -> Optional[str]:
        """Retourne la dernière version disponible sur la forge configurée.

        Toute défaillance (réseau, configuration) est journalisée en warning
        puis dégradée en ``None`` (aucune proposition de mise à jour),
        conformément au pattern des autres vérifications.

        Returns:
            La dernière version disponible, ou ``None`` si indéterminable.
        """
        provider = str(self._config.get_setting("forge.provider", default="github")).lower()
        try:
            if provider == "gitlab":
                return fetch_latest_version_gitlab(
                    base_url=str(self._config.get_setting("forge.gitlab.base_url", "")),
                    project_id=str(self._config.get_setting("forge.gitlab.project_id", "")),
                    branch=str(self._config.get_setting("forge.gitlab.branch", default="main")),
                    token=gitlab_read_token(),
                )
            return fetch_latest_version_github(
                repository=str(self._config.get_setting("github.repository", "")),
                branch=str(self._config.get_setting("forge.github.branch", default="main")),
                token=github_read_token(),
            )
        except (ValueError, OSError) as exc:
            self._logger.warning(f"[app] version distante indéterminée (forge={provider}) : {exc}")
            return None

    def check_update(self) -> Dict[str, Any]:
        """Compare la version locale à la dernière version disponible.

        Returns:
            Un dictionnaire ``{"current_version", "latest_version",
            "update_available", "dismissed"}``. ``update_available`` reflète
            l'écart réel (le déclenchement manuel reste possible même reporté) ;
            ``dismissed`` indique que la proposition automatique est suspendue
            pour cette exécution.
        """
        current_version = self.get_current_version()
        latest_version = self.get_latest_version()

        update_available = (
            current_version is not None
            and latest_version is not None
            and compare_versions(current_version, latest_version) < 0
        )
        dismissed = update_available and self._update_dismissed

        if current_version is None:
            self._logger.warning("[app] version locale illisible : version.txt absent ou invalide.")
        else:
            self._logger.info(
                f"[app] version installée={current_version}, dernière version={latest_version}"
            )

        if update_available and not dismissed:
            self._event_bus.update_available.emit("app", current_version or "?", latest_version)

        return {
            "current_version": current_version,
            "latest_version": latest_version,
            "update_available": update_available,
            "dismissed": dismissed,
        }

    def dismiss_update(self) -> None:
        """Mémorise le choix « Pas aujourd'hui » (durée de vie du processus)."""
        self._update_dismissed = True
        self._logger.info("[app] mise à jour reportée (« Pas aujourd'hui ») pour cette exécution.")

    # ------------------------------------------------------------------
    # Mise à jour effective : lancement de updater.py.
    # ------------------------------------------------------------------

    def _archive_url(self, provider: str) -> str:
        """Construit l'URL d'archive de la branche suivie selon le fournisseur.

        Args:
            provider: Fournisseur de la forge (``github`` ou ``gitlab``).

        Returns:
            L'URL (non sensible : aucun jeton n'y figure).

        Raises:
            ValueError: Si la configuration du fournisseur est incomplète.
        """
        if provider == "gitlab":
            return gitlab_archive_url(
                base_url=str(self._config.get_setting("forge.gitlab.base_url", "")),
                project_id=str(self._config.get_setting("forge.gitlab.project_id", "")),
                branch=str(self._config.get_setting("forge.gitlab.branch", default="main")),
            )
        return github_archive_url(
            repository=str(self._config.get_setting("github.repository", "")),
            branch=str(self._config.get_setting("forge.github.branch", default="main")),
        )

    def perform_update(
        self,
        progress_callback: Optional[Callable[[int], None]] = None,
        spawn: Callable[..., Any] = subprocess.Popen,
    ) -> bool:
        """Lance le script autonome ``updater.py`` en lui confiant l'application.

        Le script reçoit le PID du processus principal (celui de l'application
        Qt, threads compris) et l'URL d'archive de la nouvelle version ; il
        attend l'arrêt de l'application avant de télécharger et déployer.
        L'application doit ensuite se fermer proprement : c'est l'UI qui
        déclenche ``QApplication.quit()`` au retour de succès.

        Args:
            progress_callback: Fonction optionnelle appelée avec un
                pourcentage d'avancement (0-100).
            spawn: Constructeur de processus (injectable pour les tests).

        Returns:
            ``True`` si l'updater a bien été lancé.

        Raises:
            FileNotFoundError: Si ``updater.py`` est absent de la racine.
            ValueError: Si la configuration de la forge est incomplète.
            OSError: Si le processus n'a pas pu être lancé.
        """
        updater_path = PROJECT_ROOT / UPDATER_SCRIPT_NAME
        if not updater_path.exists():
            raise FileNotFoundError(f"Script de mise à jour introuvable : {updater_path}")

        provider = str(self._config.get_setting("forge.provider", default="github")).lower()
        auto_restart = bool(self._config.get_setting("update.app_auto_restart", default=True))
        arguments = [
            sys.executable,
            str(updater_path),
            str(os.getpid()),
            "--app-dir",
            str(PROJECT_ROOT),
            "--provider",
            provider,
            "--archive-url",
            self._archive_url(provider),
        ]
        if not auto_restart:
            arguments.append("--no-relaunch")

        # Sortie brute de l'updater (tracebacks non interceptés) dans un fichier
        # distinct de son journal applicatif logs/updater.log (évite la
        # duplication : chaque ligne y est déjà écrite par l'updater lui-même).
        log_file = PROJECT_ROOT / "logs" / "updater_console.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        process_options: Dict[str, Any] = {"cwd": str(PROJECT_ROOT)}
        if os.name == "nt":
            process_options["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            process_options["start_new_session"] = True

        self._logger.info(f"[app] lancement de l'updater (PID applicatif={os.getpid()}).")
        with log_file.open("ab") as console_log:
            spawn(arguments, stdout=console_log, stderr=subprocess.STDOUT, **process_options)

        if progress_callback is not None:
            progress_callback(100)
        return True

    # ------------------------------------------------------------------
    # Déclenchement asynchrone (délégation systématique au ThreadManager).
    # ------------------------------------------------------------------

    def start_check_update(
        self,
        on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> str:
        """Déclenche ``check_update`` en tâche de fond.

        Args:
            on_result: Rappelé avec le résultat de la vérification.
            on_error: Rappelé avec l'exception levée en cas d'échec.

        Returns:
            L'identifiant de la tâche créée par le ``ThreadManager``.
        """
        task_name = "app.verification"
        self._event_bus.task_started.emit(task_name)

        def _on_result(result: Dict[str, Any]) -> None:
            self._event_bus.task_finished.emit(task_name)
            if on_result is not None:
                on_result(result)

        def _on_error(exc: Exception) -> None:
            self._event_bus.task_finished.emit(task_name)
            if on_error is not None:
                on_error(exc)

        return self._thread_manager.run_task(
            self.check_update, on_result=_on_result, on_error=_on_error
        )

    def start_update(
        self,
        on_result: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Déclenche ``perform_update`` en tâche de fond.

        Args:
            on_result: Rappelé avec le résultat booléen de la mise à jour.
            on_error: Rappelé avec l'exception levée en cas d'échec.
            on_progress: Rappelé avec l'avancement de la mise à jour.

        Returns:
            L'identifiant de la tâche créée par le ``ThreadManager``.
        """
        task_name = "app.mise_a_jour"
        self._event_bus.module_status_changed.emit("app", "mise_a_jour")
        self._event_bus.task_started.emit(task_name)

        def _on_result(result: bool) -> None:
            self._event_bus.task_finished.emit(task_name)
            if on_result is not None:
                on_result(result)

        def _on_error(exc: Exception) -> None:
            self._event_bus.task_finished.emit(task_name)
            if on_error is not None:
                on_error(exc)

        return self._thread_manager.run_task(
            self.perform_update, on_result=_on_result, on_error=_on_error, on_progress=on_progress
        )
