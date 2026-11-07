#!/usr/bin/env python3
"""Script autonome de mise à jour de Workstation Tooler.

Lancé par l'application (``core/app_updater.py``) avec le PID du processus
principal et l'URL d'archive de la nouvelle version, il :

    1. se relocalise dans un répertoire temporaire et relance sa copie (le
       déploiement peut ainsi réécrire ``updater.py`` du dépôt sans conflit
       de fichier en cours d'utilisation, Windows compris) ;
    2. attend l'arrêt du processus applicatif ; passé 15 secondes, propose de
       forcer son arrêt (et repose la question tant qu'il ne meurt pas) ;
    3. télécharge l'archive de la branche par HTTP (GitHub ou GitLab selon le
       fournisseur — aucun jeton n'apparaît dans les arguments ni les URL) ;
    4. l'extrait de façon sûre (rejet des chemins de traverse, retrait du
       dossier racine ajouté par les forges) et la déploie sur place :
       recouvrement, purge des fichiers supprimés en amont, garde contre
       l'écrasement de modifications locales (manifeste de déploiement) ;
    5. réinstalle les dépendances si un ``.venv`` est présent ;
    6. relance l'application (sauf ``--no-relaunch``).

Aucune commande Git n'est exécutée : le poste n'a besoin que d'un accès HTTP
à la forge.

Utilisation :
    python updater.py <pid> --archive-url URL [--app-dir DIR]
                      [--provider github|gitlab] [--no-relaunch] [--relaunched]

Le journal complet est écrit dans ``logs/updater.log`` à la racine de
l'application. Voir ``docs/maj_application.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

#: Intervalle d'interrogation de l'état du processus applicatif (secondes).
POLL_INTERVAL_SECONDS = 0.5

#: Délai avant proposition de forçage de l'arrêt (secondes).
EXIT_TIMEOUT_SECONDS = 15.0

#: Délai maximal du téléchargement de l'archive (secondes, par lecture socket).
DOWNLOAD_TIMEOUT_SECONDS = 120

#: Délai maximal de l'installation des dépendances (secondes).
PIP_TIMEOUT_SECONDS = 600

#: Nom du manifeste de déploiement (fichiers déployés + empreintes SHA-256).
MANIFEST_FILE_NAME = ".updater_manifest.json"

#: En-tête User-Agent présenté à la forge.
USER_AGENT = "Workstation-Tooler-Updater"

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
    except EOFError, OSError:
        # Entrée standard fermée (exécution détachée sans console) : refus sûr.
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
    """Proposition de forçage de l'arrêt après écoulement du délai."""
    return ask_yes_no(
        "Workstation Tooler — Mise à jour",
        "L'application ne s'est pas arrêtée après 15 secondes.\n"
        "Forcer son arrêt pour déployer la mise à jour ?",
    )


def default_confirm_modified(count: int) -> bool:
    """Garde contre l'écrasement de fichiers modifiés localement."""
    return ask_yes_no(
        "Workstation Tooler — Mise à jour",
        f"{count} fichier(s) déployé(s) ont été modifiés localement.\n"
        "Le déploiement écrasera ces modifications. Continuer ?",
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
# Téléchargement et extraction de la release.
# ----------------------------------------------------------------------


def _app_updater_module(app_dir: Path) -> Optional[Any]:
    """Importe ``core.app_updater`` depuis le dépôt applicatif (tokens partagés).

    Args:
        app_dir: Racine du dépôt applicatif.

    Returns:
        Le module, ou ``None`` si l'import est impossible (dépendances absentes).
    """
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    try:
        import core.app_updater as app_updater_module

        return app_updater_module
    except Exception as exc:  # PyQt6/PyYAML absents, dépôt incomplet...
        log(f"module applicatif inaccessible ({type(exc).__name__}: {exc}).")
        return None


def forge_headers(provider: str, app_dir: Path) -> Dict[str, str]:
    """Construit les en-têtes HTTP de téléchargement selon le fournisseur.

    Args:
        provider: ``github`` ou ``gitlab``.
        app_dir: Racine du dépôt applicatif (import des lecteurs de jetons).

    Returns:
        Les en-têtes (``User-Agent`` + authentification le cas échéant). Les
        jetons ne figurent jamais dans les URL ni les arguments de processus.
    """
    headers = {"User-Agent": USER_AGENT}
    app_updater = _app_updater_module(app_dir)
    if app_updater is None:
        return headers
    try:
        if provider == "gitlab":
            token = app_updater.gitlab_read_token()
            if token:
                headers["PRIVATE-TOKEN"] = token
        else:
            token = app_updater.github_read_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
    except Exception as exc:
        log(f"avertissement : jeton {provider} inaccessible ({exc}) : téléchargement anonyme.")
    return headers


def download_archive(
    url: str,
    destination: Path,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DOWNLOAD_TIMEOUT_SECONDS,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> None:
    """Télécharge l'archive de la nouvelle version par HTTP GET.

    Args:
        url: URL de l'archive (fournie par l'application, sans jeton).
        destination: Fichier local de destination.
        headers: En-têtes de requête (authentification forge).
        timeout: Délai maximal (secondes).
        opener: Ouvreur d'URL (injectable pour les tests).

    Raises:
        OSError: En cas d'erreur HTTP/réseau.
    """
    request = urllib.request.Request(url, headers=headers or {})
    with opener(request, timeout=timeout) as response:
        with destination.open("wb") as target:
            shutil.copyfileobj(response, target)


def extract_release(archive_path: Path, destination: Path) -> List[str]:
    """Extrait l'archive d'une release en retirant son dossier racine.

    GitHub et GitLab servent des archives dont tout le contenu est emballé
    sous un unique dossier racine (``<projet>-<sha>``) : il est retiré pour
    que les fichiers atterrissent directement dans ``destination``.
    L'extraction est durcie par le filtre ``data`` de ``tarfile`` (rejet des
    chemins absolus et des traverses de répertoires).

    Args:
        archive_path: Archive ``tar.gz`` téléchargée.
        destination: Répertoire d'extraction (créé au besoin).

    Returns:
        Les chemins relatifs POSIX des fichiers extraits.

    Raises:
        tarfile.TarError: Si l'archive est illisible ou contient un membre dangereux.
        ValueError: Si un membre présente un chemin de traverse.
    """
    destination.mkdir(parents=True, exist_ok=True)
    extracted: List[str] = []
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if members:
            roots = {member.name.split("/", 1)[0] for member in members}
            if len(roots) == 1:
                root_name = roots.pop()
                # Retrait du dossier racine uniquement si l'archive en contient
                # un (un fichier unique à la racine ne doit pas disparaître).
                if any("/" in member.name for member in members):
                    members = [member for member in members if member.name != root_name]
                    for member in members:
                        member.name = member.name[len(root_name) + 1 :]
        archive.extractall(destination, members=members, filter="data")

    for path in destination.rglob("*"):
        if path.is_file():
            extracted.append(path.relative_to(destination).as_posix())
    return sorted(extracted)


# ----------------------------------------------------------------------
# Manifeste de déploiement, recouvrement et purge.
# ----------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    """Calcule l'empreinte SHA-256 d'un fichier.

    Args:
        path: Fichier à hacher.

    Returns:
        L'empreinte hexadécimale.
    """
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(app_dir: Path) -> Dict[str, str]:
    """Charge le manifeste du dernier déploiement (vide s'il n'existe pas)."""
    manifest_file = app_dir / MANIFEST_FILE_NAME
    if not manifest_file.exists():
        return {}
    try:
        content = json.loads(manifest_file.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return {}
    files = content.get("files", {})
    return files if isinstance(files, dict) else {}


def save_manifest(app_dir: Path, files: Dict[str, str]) -> None:
    """Écrit le manifeste de déploiement (chemins relatifs → SHA-256)."""
    manifest_file = app_dir / MANIFEST_FILE_NAME
    payload = {"files": dict(sorted(files.items()))}
    manifest_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def find_locally_modified_files(
    app_dir: Path, release_files: List[str], manifest: Dict[str, str]
) -> List[str]:
    """Identifie les fichiers déployés modifiés localement depuis le dernier déploiement.

    Args:
        app_dir: Racine de l'application.
        release_files: Fichiers de la nouvelle release (chemins relatifs).
        manifest: Manifeste du déploiement précédent.

    Returns:
        Les chemins relatifs dont le contenu local ne correspond plus à
        l'empreinte enregistrée (liste vide sans manifeste : première mise à
        jour, aucune référence de comparaison).
    """
    modified: List[str] = []
    for relative in release_files:
        recorded = manifest.get(relative)
        if recorded is None:
            continue
        local_file = app_dir / relative
        if local_file.is_file() and sha256_file(local_file) != recorded:
            modified.append(relative)
    return sorted(modified)


def deploy_release(
    app_dir: Path,
    release_dir: Path,
    confirm_modified: Callable[[int], bool] = default_confirm_modified,
) -> bool:
    """Déploie une release extraite sur l'installation locale.

    Recouvre les fichiers existants, purge ceux qui figuraient au manifeste
    précédent mais ont disparu de la nouvelle release, puis enregistre le
    nouveau manifeste. Les éléments hors manifeste (``.venv``, ``logs/``,
    ``.git``, fichiers personnels) ne sont jamais touchés.

    Args:
        app_dir: Racine de l'application.
        release_dir: Répertoire de la release extraite.
        confirm_modified: Garde appelée avec le nombre de fichiers déployés
            modifiés localement (retour ``False`` = abandon).

    Returns:
        ``True`` si le déploiement a été effectué, ``False`` si annulé.
    """
    previous_manifest = load_manifest(app_dir)
    release_files = sorted(
        path.relative_to(release_dir).as_posix()
        for path in release_dir.rglob("*")
        if path.is_file()
    )

    modified = find_locally_modified_files(app_dir, release_files, previous_manifest)
    if modified and not confirm_modified(len(modified)):
        log(f"déploiement annulé : fichiers modifiés localement ({', '.join(modified)}).")
        return False

    # Recouvrement : copie de chaque fichier de la release (parents créés).
    for relative in release_files:
        source = release_dir / relative
        target = app_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    # Purge : suppression des fichiers du déploiement précédent absents de la
    # nouvelle release (équivalent HTTP du « reset --hard » pour les retraits).
    for relative in sorted(set(previous_manifest) - set(release_files)):
        stale_file = app_dir / relative
        if stale_file.is_file():
            stale_file.unlink()
            log(f"fichier obsolète supprimé : {relative}")
        _remove_empty_parents(stale_file.parent, app_dir)

    new_manifest = {relative: sha256_file(app_dir / relative) for relative in release_files}
    save_manifest(app_dir, new_manifest)
    log(f"{len(release_files)} fichier(s) déployé(s), manifeste mis à jour.")
    return True


def _remove_empty_parents(directory: Path, stop_at: Path) -> None:
    """Supprime les répertoires parents devenus vides, sans dépasser ``stop_at``."""
    directory = directory.resolve()
    stop_at = stop_at.resolve()
    while directory != stop_at and stop_at in directory.parents:
        try:
            directory.rmdir()
        except OSError:
            return  # non vide (ou indisponible) : on s'arrête discrètement.
        directory = directory.parent


# ----------------------------------------------------------------------
# Venv, dépendances, relance.
# ----------------------------------------------------------------------


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
    provider: str,
    archive_url: str,
    relaunch: bool,
    is_alive: Callable[[int], bool] = is_process_alive,
    ask_force: Callable[[], bool] = default_ask_force,
    force_kill: Callable[[int], None] = kill_process,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> bool:
    """Exécute le cycle complet de mise à jour après arrêt de l'application.

    Args:
        app_dir: Racine de l'installation applicative.
        pid: PID du processus applicatif à attendre.
        provider: Fournisseur de la forge (``github`` ou ``gitlab``) — détermine
            l'authentification du téléchargement.
        archive_url: URL HTTP(S) de l'archive de la nouvelle version.
        relaunch: Relancer l'application après déploiement.
        is_alive: Test d'existence du processus (injectable pour les tests).
        ask_force: Proposition de forçage (injectable pour les tests).
        force_kill: Arrêt forcé (injectable pour les tests).
        opener: Ouvreur d'URL (injectable pour les tests).

    Returns:
        ``True`` si le déploiement a été effectué, ``False`` si annulé.

    Raises:
        OSError: En cas d'erreur HTTP/réseau ou d'accès fichier.
        tarfile.TarError: Si l'archive téléchargée est illisible ou dangereuse.
    """
    log(
        f"attente de l'arrêt du processus {pid} (forçage proposé après "
        f"{EXIT_TIMEOUT_SECONDS:.0f} s)."
    )
    wait_for_exit(pid, is_alive=is_alive, ask_force=ask_force, force_kill=force_kill)
    log("application arrêtée.")

    headers = forge_headers(provider, app_dir)
    with tempfile.TemporaryDirectory(prefix="workstation_tooler_release_") as temp_dir:
        staging = Path(temp_dir)
        archive_file = staging / "release.tar.gz"
        log(f"téléchargement de {archive_url} (fournisseur={provider})...")
        download_archive(archive_url, archive_file, headers=headers, opener=opener)

        release_dir = staging / "release"
        release_files = extract_release(archive_file, release_dir)
        log(f"archive extraite : {len(release_files)} fichier(s).")

        if not deploy_release(app_dir, release_dir):
            return False

    version_file = app_dir / "version.txt"
    if version_file.exists():
        log(f"version déployée : {version_file.read_text(encoding='utf-8').strip()}")

    install_dependencies(app_dir)

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
        "--archive-url",
        required=True,
        help="URL HTTP(S) de l'archive (tar.gz) de la nouvelle version.",
    )
    parser.add_argument(
        "--app-dir",
        default=None,
        help="Racine de l'installation applicative (défaut : dossier du script).",
    )
    parser.add_argument(
        "--provider", choices=["github", "gitlab"], default="github", help="Forge source."
    )
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
    pid: int, app_dir: Path, provider: str, archive_url: str, no_relaunch: bool
) -> None:
    """Copie le script hors du dépôt puis relance la copie détachée.

    Évite tout conflit de « fichier en cours d'utilisation » lorsque le
    déploiement réécrit ``updater.py`` (verrou Windows notamment).

    Args:
        pid: PID du processus applicatif.
        app_dir: Racine de l'installation applicative.
        provider: Forge source (github ou gitlab).
        archive_url: URL de l'archive de la nouvelle version.
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
        "--archive-url",
        archive_url,
        "--app-dir",
        str(app_dir),
        "--provider",
        provider,
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
        relocate_and_rerun(args.pid, app_dir, args.provider, args.archive_url, args.no_relaunch)

    log(
        f"updater démarré (app_dir={app_dir}, pid={args.pid}, "
        f"provider={args.provider}, relance={not args.no_relaunch})."
    )
    try:
        success = update_app(
            app_dir=app_dir,
            pid=args.pid,
            provider=args.provider,
            archive_url=args.archive_url,
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
