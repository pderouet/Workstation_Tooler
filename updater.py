#!/usr/bin/env python3
"""Script autonome de mise à jour de Workstation Tooler.

Lancé par l'application (``core/app_updater.py``) avec le PID du processus
principal, il :

    1. se relocalise dans un répertoire temporaire et relance sa copie (le
       ``git reset --hard`` peut ainsi réécrire ``updater.py`` du dépôt sans
       conflit de fichier en cours d'utilisation, Windows compris) ;
    2. attend l'arrêt du processus applicatif ; passé 15 secondes, propose de
       forcer son arrêt (et repose la question tant qu'il ne meurt pas) ;
    3. déploie la nouvelle version via Git (``fetch`` + ``reset --hard``) ;
    4. réinstalle les dépendances si un ``.venv`` est présent ;
    5. relance l'application (sauf ``--no-relaunch``).

Utilisation :
    python updater.py <pid> [--app-dir DIR] [--provider github|gitlab]
                      [--branch BRANCHE] [--no-relaunch] [--relaunched]

Le journal complet est écrit dans ``logs/updater.log`` à la racine de
l'application. Voir ``docs/maj_application.md``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

#: Intervalle d'interrogation de l'état du processus applicatif (secondes).
POLL_INTERVAL_SECONDS = 0.5

#: Délai avant proposition de forçage de l'arrêt (secondes).
EXIT_TIMEOUT_SECONDS = 15.0

#: Délais maximaux des commandes Git (secondes).
GIT_TIMEOUT_SECONDS = 120
PIP_TIMEOUT_SECONDS = 600

#: Fichier de journal (initialisé par ``setup_logging``).
_LOG_FILE: Optional[Path] = None


def log(message: str) -> None:
    """Journalise une ligne horodatée dans ``logs/updater.log`` et la console."""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    if _LOG_FILE is not None:
        try:
            _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_FILE.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{line}\n")
        except OSError:
            pass  # journal best-effort : jamais bloquant pour la mise à jour.


def setup_logging(app_dir: Path) -> None:
    """Définit l'emplacement du journal (``<app_dir>/logs/updater.log``)."""
    global _LOG_FILE
    _LOG_FILE = app_dir / "logs" / "updater.log"


def console_log_path(app_dir: Path) -> Path:
    """Chemin de la sortie brute de l'updater (tracebacks non interceptés).

    Distinct du journal applicatif : chaque processus de l'updater écrit son
    journal via ``log()`` ; rediriger aussi son stdout vers ``updater.log``
    dupliquerait chaque ligne.
    """
    return app_dir / "logs" / "updater_console.log"


# ----------------------------------------------------------------------
# Dialogues utilisateur (tkinter, repli console).
# ----------------------------------------------------------------------


def _messagebox() -> Optional[Any]:
    """Retourne le module ``tkinter.messagebox``, ou ``None`` si indisponible."""
    try:
        from tkinter import messagebox

        return messagebox
    except Exception:  # ImportError ou absence d'affichage (TclError)
        return None


def ask_yes_no(title: str, message: str) -> bool:
    """Pose une question oui/non (dialogue graphique, repli console)."""
    box = _messagebox()
    if box is not None:
        try:
            return bool(box.askyesno(title, message))
        except Exception:
            pass  # repli console ci-dessous.
    try:
        answer = input(f"{title}\n{message} [O/n] : ")
    except EOFError:
        return False
    return answer.strip().lower() in ("o", "oui", "y", "yes")


def notify(message: str, error: bool = False) -> None:
    """Affiche un message final (dialogue graphique, repli console)."""
    box = _messagebox()
    if box is not None:
        try:
            if error:
                box.showerror("Workstation Tooler", message)
            else:
                box.showinfo("Workstation Tooler", message)
            return
        except Exception:
            pass
    print(message, flush=True)


def default_ask_force() -> bool:
    """Proposition de forçage de l'arrêt après dépaiement du délai."""
    return ask_yes_no(
        "Workstation Tooler — Mise à jour",
        "L'application ne s'est pas arrêtée après 15 secondes.\n"
        "Forcer son arrêt pour déployer la mise à jour ?",
    )


def default_confirm_dirty() -> bool:
    """Avertissement avant écrasement de modifications locales."""
    return ask_yes_no(
        "Workstation Tooler — Mise à jour",
        "Des modifications locales non versionnées ont été détectées dans le dépôt.\n"
        "Elles seront perdues lors du déploiement (git reset --hard). Continuer ?",
    )


# ----------------------------------------------------------------------
# Cycle de vie du processus applicatif.
# ----------------------------------------------------------------------


def is_process_alive(pid: int) -> bool:
    """Indique si le processus identifié par ``pid`` est encore en vie.

    Args:
        pid: Identifiant du processus.

    Returns:
        ``True`` si le processus existe (y compris sans droit d'inspection).
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # le processus existe mais appartient à un autre utilisateur.
    return True


def kill_process(pid: int) -> None:
    """Termine forcément le processus applicatif.

    Args:
        pid: Identifiant du processus à arrêter.

    Raises:
        OSError: Si l'arrêt forcé échoue.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=15, check=True
        )
    else:
        os.kill(pid, signal.SIGKILL)


def wait_for_exit(
    pid: int,
    timeout: float = EXIT_TIMEOUT_SECONDS,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    is_alive: Callable[[int], bool] = is_process_alive,
    ask_force: Callable[[], bool] = default_ask_force,
    force_kill: Callable[[int], None] = kill_process,
) -> bool:
    """Attend la fin du processus applicatif, en proposant le forçage à timeout.

    Au terme de chaque délai ``timeout``, l'utilisateur est invité à forcer
    l'arrêt ; s'il refuse, une nouvelle période d'attente démarre avant que la
    question ne soit reposée.

    Args:
        pid: Identifiant du processus attendu.
        timeout: Délai (secondes) avant chaque proposition de forçage.
        poll_interval: Intervalle d'interrogation (secondes).
        is_alive: Test d'existence du processus (injectable pour les tests).
        ask_force: Proposition de forçage (injectable pour les tests).
        force_kill: Arrêt forcé (injectable pour les tests).

    Returns:
        ``True`` lorsque le processus est terminé.
    """
    deadline = time.monotonic() + timeout
    while is_alive(pid):
        if time.monotonic() >= deadline:
            if ask_force():
                log(f"arrêt forcé du processus {pid} demandé par l'utilisateur.")
                force_kill(pid)
            deadline = time.monotonic() + timeout
        time.sleep(poll_interval)
    return True


# ----------------------------------------------------------------------
# Déploiement Git et finalisation.
# ----------------------------------------------------------------------


def run_git(
    app_dir: Path,
    args: List[str],
    extra_config: Optional[Dict[str, str]] = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    timeout: int = GIT_TIMEOUT_SECONDS,
) -> str:
    """Exécute une commande Git dans le dépôt de l'application.

    Args:
        app_dir: Racine du clone Git.
        args: Arguments de la commande Git (ex. ``["fetch", "origin", "main"]``).
        extra_config: Options ``-c clé=valeur`` additionnelles.
        runner: Exécuteur (injectable pour les tests).
        timeout: Délai maximal (secondes).

    Returns:
        La sortie standard de la commande.

    Raises:
        subprocess.SubprocessError: Si la commande échoue ou expire.
        OSError: Si Git est indisponible.
    """
    command = ["git", "-C", str(app_dir)]
    for key, value in (extra_config or {}).items():
        command += ["-c", f"{key}={value}"]
    command += args
    completed = runner(command, capture_output=True, text=True, timeout=timeout, check=True)
    return completed.stdout


def has_local_changes(app_dir: Path, runner: Callable[..., Any] = subprocess.run) -> bool:
    """Indique si le dépôt contient des modifications non versionnées."""
    completed = runner(
        ["git", "-C", str(app_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        check=True,
    )
    return bool(completed.stdout.strip())


def get_gitlab_read_token(app_dir: Path) -> str:
    """Récupère le token GitLab (lecture seule) partagé avec l'application.

    Importe ``core.app_updater`` depuis le dépôt applicatif afin que le token
    n'ait qu'un seul emplacement de définition.

    Args:
        app_dir: Racine du dépôt applicatif.

    Returns:
        Le token, ou une chaîne vide si l'import est impossible.
    """
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    try:
        from core.app_updater import GITLAB_READ_TOKEN

        return GITLAB_READ_TOKEN
    except Exception as exc:  # PyQt6/PyYAML absents, dépôt incomplet...
        log(f"token GitLab inaccessible ({type(exc).__name__}: {exc}) : fetch anonyme.")
        return ""


def fetch_and_reset(
    app_dir: Path,
    branch: str,
    provider: str,
    token_provider: Optional[Callable[[], str]] = None,
    runner: Callable[..., Any] = subprocess.run,
) -> None:
    """Récupère la branche distante puis aligne le dépôt dessus (reset --hard).

    Args:
        app_dir: Racine du clone Git.
        branch: Branche distante suivie.
        provider: ``github`` (credentials du clone) ou ``gitlab`` (token injecté
            en en-tête HTTP, jamais dans les arguments ni la configuration).
        token_provider: Fournisseur du token GitLab (défaut : import applicatif).
        runner: Exécuteur (injectable pour les tests).

    Raises:
        subprocess.SubprocessError: Si une commande Git échoue.
    """
    extra_config: Dict[str, str] = {}
    if provider == "gitlab":
        token = token_provider() if token_provider is not None else get_gitlab_read_token(app_dir)
        if token:
            extra_config["http.extraheader"] = f"Authorization: Bearer {token}"
        else:
            log("avertissement : token GitLab absent, tentative de fetch anonyme.")
    run_git(
        app_dir, ["fetch", "--quiet", "origin", branch], extra_config=extra_config, runner=runner
    )
    run_git(app_dir, ["reset", "--hard", "FETCH_HEAD"], runner=runner)


def venv_python(app_dir: Path) -> Optional[Path]:
    """Retourne l'interprète du ``.venv`` de l'application, s'il existe."""
    candidates = [
        app_dir / ".venv" / "bin" / "python",  # POSIX
        app_dir / ".venv" / "Scripts" / "python.exe",  # Windows
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def install_dependencies(app_dir: Path, runner: Callable[..., Any] = subprocess.run) -> bool:
    """Réinstalle les dépendances runtime du ``.venv`` après déploiement.

    Args:
        app_dir: Racine du dépôt applicatif.
        runner: Exécuteur (injectable pour les tests).

    Returns:
        ``True`` si l'installation a réussi (ou sans venv, sans rien faire).
    """
    interpreter = venv_python(app_dir)
    if interpreter is None:
        log("aucun .venv détecté : dépendances non réinstallées.")
        return False
    completed = runner(
        [str(interpreter), "-m", "pip", "install", "-q", "-r", "requirements.txt"],
        cwd=str(app_dir),
        capture_output=True,
        text=True,
        timeout=PIP_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        log(f"avertissement : pip install en échec (code {completed.returncode}).")
        return False
    log("dépendances réinstallées.")
    return True


def relaunch_app(app_dir: Path, spawn: Callable[..., Any] = subprocess.Popen) -> bool:
    """Relance l'application (``main.py``) dans un processus détaché.

    Args:
        app_dir: Racine du dépôt applicatif.
        spawn: Constructeur de processus (injectable pour les tests).

    Returns:
        ``True`` si le lancement a été effectué.
    """
    interpreter = venv_python(app_dir) or Path(sys.executable)
    command = [str(interpreter), "main.py"]
    options: Dict[str, Any] = {"cwd": str(app_dir)}
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    # La sortie console de l'application relancée rejoint la sortie brute
    # (l'application tient son propre journal applicatif).
    app_console_log = console_log_path(app_dir)
    app_console_log.parent.mkdir(parents=True, exist_ok=True)
    with app_console_log.open("ab") as console_log:
        spawn(command, stdout=console_log, stderr=subprocess.STDOUT, **options)
    log(f"application relancée : {' '.join(command)}")
    return True


# ----------------------------------------------------------------------
# Orchestration.
# ----------------------------------------------------------------------


def update_app(
    app_dir: Path,
    pid: int,
    branch: str,
    provider: str,
    relaunch: bool,
    is_alive: Callable[[int], bool] = is_process_alive,
    ask_force: Callable[[], bool] = default_ask_force,
    force_kill: Callable[[int], None] = kill_process,
    confirm_dirty: Optional[Callable[[], bool]] = None,
    token_provider: Optional[Callable[[], str]] = None,
    runner: Callable[..., Any] = subprocess.run,
) -> bool:
    """Exécute le cycle complet de mise à jour après arrêt de l'application.

    Args:
        app_dir: Racine du clone Git de l'application.
        pid: PID du processus applicatif à attendre.
        branch: Branche distante à déployer.
        provider: Fournisseur de la forge (``github`` ou ``gitlab``).
        relaunch: Relancer l'application après déploiement.
        is_alive: Test d'existence du processus (injectable pour les tests).
        ask_force: Proposition de forçage (injectable pour les tests).
        force_kill: Arrêt forcé (injectable pour les tests).
        confirm_dirty: Confirmation d'écrasement des modifications locales
            (défaut : dialogue graphique).
        token_provider: Fournisseur du token GitLab (injectable pour les tests).
        runner: Exécuteur de commandes (injectable pour les tests).

    Returns:
        ``True`` si le déploiement a été effectué, ``False`` si annulé.

    Raises:
        subprocess.SubprocessError: Si une commande Git échoue.
        OSError: Si Git est indisponible.
    """
    log(
        f"attente de l'arrêt du processus {pid} (forçage proposé après "
        f"{EXIT_TIMEOUT_SECONDS:.0f} s)."
    )
    wait_for_exit(pid, is_alive=is_alive, ask_force=ask_force, force_kill=force_kill)
    log("application arrêtée.")

    if has_local_changes(app_dir, runner=runner):
        decide = confirm_dirty if confirm_dirty is not None else default_confirm_dirty
        if not decide():
            log("mise à jour annulée : modifications locales à conserver.")
            return False
        log("modifications locales écrasées sur confirmation de l'utilisateur.")

    log(f"déploiement Git (provider={provider}, branche={branch})...")
    fetch_and_reset(app_dir, branch, provider, token_provider=token_provider, runner=runner)

    version_file = app_dir / "version.txt"
    if version_file.exists():
        log(f"version déployée : {version_file.read_text(encoding='utf-8').strip()}")

    install_dependencies(app_dir, runner=runner)

    if relaunch:
        relaunch_app(app_dir)
    else:
        notify("La mise à jour de Workstation Tooler est terminée.")
    return True


# ----------------------------------------------------------------------
# Auto-relocalisation puis point d'entrée.
# ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments en ligne de commande."""
    parser = argparse.ArgumentParser(
        prog="updater.py", description="Mise à jour autonome de Workstation Tooler."
    )
    parser.add_argument("pid", type=int, help="PID du processus applicatif à attendre.")
    parser.add_argument(
        "--app-dir",
        default=None,
        help="Racine du dépôt applicatif (défaut : dossier du script).",
    )
    parser.add_argument(
        "--provider", choices=["github", "gitlab"], default="github", help="Forge source."
    )
    parser.add_argument("--branch", default="main", help="Branche distante à déployer.")
    parser.add_argument(
        "--no-relaunch", action="store_true", help="Ne pas relancer l'application après."
    )
    parser.add_argument(
        "--relaunched",
        action="store_true",
        help=argparse.SUPPRESS,  # usage interne.
    )
    return parser


def relocate_and_rerun(
    pid: int, app_dir: Path, provider: str, branch: str, no_relaunch: bool
) -> None:
    """Copie le script hors du dépôt puis relance la copie détachée.

    Évite tout conflit de « fichier en cours d'utilisation » lorsque le
    ``git reset --hard`` réécrit ``updater.py`` (verrou Windows notamment).

    Args:
        pid: PID du processus applicatif.
        app_dir: Racine du dépôt applicatif.
        provider: Forge source (github ou gitlab).
        branch: Branche distante.
        no_relaunch: Ne pas relancer l'application après mise à jour.
    """
    temp_dir = Path(tempfile.gettempdir()) / "workstation_tooler_updater"
    temp_dir.mkdir(parents=True, exist_ok=True)
    copy_path = temp_dir / "updater.py"
    shutil.copy2(Path(__file__).resolve(), copy_path)
    log(f"relocalisation du script vers {copy_path} (évite le verrou sur updater.py).")

    command = [
        sys.executable,
        str(copy_path),
        str(pid),
        "--app-dir",
        str(app_dir),
        "--provider",
        provider,
        "--branch",
        branch,
        "--relaunched",
    ]
    if no_relaunch:
        command.append("--no-relaunch")

    options: Dict[str, Any] = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    # Sortie brute de la copie dans un fichier distinct du journal applicatif
    # (sinon chaque ligne serait dupliquée : print + log()).
    console_log_file = console_log_path(app_dir)
    console_log_file.parent.mkdir(parents=True, exist_ok=True)
    with console_log_file.open("ab") as console_log:
        subprocess.Popen(command, stdout=console_log, stderr=subprocess.STDOUT, **options)
    sys.exit(0)


def main(argv: Optional[List[str]] = None) -> int:
    """Point d'entrée du script de mise à jour.

    Args:
        argv: Arguments (défaut : ligne de commande réelle).

    Returns:
        Le code de sortie du processus.
    """
    args = build_parser().parse_args(argv)
    app_dir = Path(args.app_dir).resolve() if args.app_dir else Path(__file__).resolve().parent
    setup_logging(app_dir)

    if not args.relaunched:
        relocate_and_rerun(args.pid, app_dir, args.provider, args.branch, args.no_relaunch)

    log(
        f"updater démarré (app_dir={app_dir}, pid={args.pid}, "
        f"provider={args.provider}, branche={args.branch}, relance={not args.no_relaunch})."
    )
    try:
        success = update_app(
            app_dir=app_dir,
            pid=args.pid,
            branch=args.branch,
            provider=args.provider,
            relaunch=not args.no_relaunch,
        )
    except Exception as exc:  # remontée à l'utilisateur + journal, pas d'exception muette.
        log(f"ÉCHEC de la mise à jour : {type(exc).__name__}: {exc}")
        notify(f"La mise à jour de Workstation Tooler a échoué : {exc}", error=True)
        return 1

    if not success:
        return 1
    log("mise à jour terminée avec succès.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
