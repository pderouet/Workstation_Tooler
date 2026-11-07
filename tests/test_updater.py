"""Tests headless du script updater.py (aucun réseau, dialogues injectés).

L'intégration Git s'appuie sur un dépôt nu local servant d'« origin » à un
clone de travail : aucun accès à une forge réelle.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

import updater
from updater import (
    build_parser,
    fetch_and_reset,
    install_dependencies,
    is_process_alive,
    relocate_and_rerun,
    update_app,
    venv_python,
    wait_for_exit,
)


def git(*args: str, cwd: Path) -> None:
    """Exécute une commande Git locale avec une identité de test."""
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.fr", *args],
        cwd=str(cwd),
        capture_output=True,
        check=True,
    )


def make_git_sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """Construit un dépôt nu « origin » et un clone en retard d'une version.

    Returns:
        Le couple ``(clone, workdir)`` : le clone déployé (en 0.0.1) et le
        dépôt de travail pousseur (déjà en 0.0.2 sur origin).
    """
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git("init", "--bare", "-b", "main", cwd=origin)

    workdir = tmp_path / "work"
    workdir.mkdir()
    git("init", "-b", "main", cwd=workdir)
    (workdir / "version.txt").write_text("0.0.1\n", encoding="utf-8")
    git("add", ".", cwd=workdir)
    git("commit", "-m", "init", cwd=workdir)
    git("remote", "add", "origin", str(origin), cwd=workdir)
    git("push", "-q", "-u", "origin", "main", cwd=workdir)

    clone = tmp_path / "clone"
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)

    # Nouvelle version publiée sur l'origin après le clonage.
    (workdir / "version.txt").write_text("0.0.2\n", encoding="utf-8")
    (workdir / "nouveau_fichier.txt").write_text("contenu 0.0.2\n", encoding="utf-8")
    git("add", ".", cwd=workdir)
    git("commit", "-m", "bump 0.0.2", cwd=workdir)
    git("push", "-q", "origin", "main", cwd=workdir)
    return clone, workdir


# ----------------------------------------------------------------------
# Arguments et cycle de vie du processus.
# ----------------------------------------------------------------------


def test_parse_arguments_complets() -> None:
    """Les arguments attendus par l'application sont correctement interprétés."""
    args = build_parser().parse_args(
        [
            "4242",
            "--app-dir",
            "/opt/app",
            "--provider",
            "gitlab",
            "--branch",
            "dev",
            "--no-relaunch",
            "--relaunched",
        ]
    )
    assert args.pid == 4242
    assert args.app_dir == "/opt/app"
    assert args.provider == "gitlab"
    assert args.branch == "dev"
    assert args.no_relaunch is True
    assert args.relaunched is True


def test_parse_arguments_defauts() -> None:
    """Valeurs par défaut : github, branche main, avec relance."""
    args = build_parser().parse_args(["4242"])
    assert args.provider == "github"
    assert args.branch == "main"
    assert args.no_relaunch is False
    assert args.app_dir is None


def test_processus_courant_vivant_pid_inexistant_mort() -> None:
    """Le processus courant est vivant ; un PID terminé ne l'est plus."""
    assert is_process_alive(os.getpid()) is True

    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    assert is_process_alive(finished.pid) is False


def test_wait_for_exit_processus_deja_mort() -> None:
    """Un processus déjà terminé rend la main immédiatement, sans question."""
    asked: List[bool] = []
    result = wait_for_exit(
        1234,
        timeout=0.1,
        poll_interval=0.01,
        is_alive=lambda _pid: False,
        ask_force=lambda: (asked.append(True), True)[1],
    )
    assert result is True
    assert asked == []


def test_wait_for_exit_force_apres_delai() -> None:
    """À l'expiration du délai, le forçage est proposé puis exécuté."""
    alive = {"status": True}

    def fake_is_alive(_pid: int) -> bool:
        return alive["status"]

    def fake_force(pid: int) -> None:
        alive["status"] = False

    forced: List[int] = []
    result = wait_for_exit(
        4242,
        timeout=0.05,
        poll_interval=0.01,
        is_alive=fake_is_alive,
        ask_force=lambda: True,
        force_kill=lambda pid: (fake_force(pid), forced.append(pid)),
    )
    assert result is True
    assert forced == [4242]


def test_wait_for_exit_refus_puis_nouvelle_proposition() -> None:
    """Un refus de forçage relance une période d'attente avant de reposer la question."""
    alive = {"status": True}
    answers = iter([False, True])

    result = wait_for_exit(
        4242,
        timeout=0.05,
        poll_interval=0.01,
        is_alive=lambda _pid: alive["status"],
        ask_force=lambda: next(answers),
        force_kill=lambda _pid: alive.update(status=False),
    )
    assert result is True  # sorti au deuxième tour, après acceptation.


# ----------------------------------------------------------------------
# Déploiement Git.
# ----------------------------------------------------------------------


def recording_runner():
    """Exécuteur factice enregistrant les commandes et répondant succès."""
    commands: List[List[str]] = []

    def runner(command: List[str], **_kwargs: Any) -> subprocess.CompletedProcess:
        commands.append(list(command))
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="")

    runner.commands = commands  # type: ignore[attr-defined]
    return runner


def test_fetch_and_reset_github_sans_option() -> None:
    """Fournisseur GitHub : fetch simple, aucune option -c ajoutée."""
    runner = recording_runner()
    fetch_and_reset(Path("/opt/app"), "main", "github", runner=runner)
    commands = runner.commands  # type: ignore[attr-defined]
    assert commands[0] == ["git", "-C", "/opt/app", "fetch", "--quiet", "origin", "main"]
    assert commands[1] == ["git", "-C", "/opt/app", "reset", "--hard", "FETCH_HEAD"]
    assert not any("-c" in command for command in commands)


def test_fetch_and_reset_gitlab_avec_token_en_en_tete() -> None:
    """Fournisseur GitLab : le token passe par http.extraheader, jamais en clair dans l'URL."""
    runner = recording_runner()
    fetch_and_reset(
        Path("/opt/app"),
        "dev",
        "gitlab",
        token_provider=lambda: "jeton-secret",
        runner=runner,
    )
    commands = runner.commands  # type: ignore[attr-defined]
    assert commands[0][:3] == ["git", "-C", "/opt/app"]
    # Le secret n'apparaît que dans l'unique argument d'en-tête HTTP.
    arguments_avec_secret = [arg for arg in commands[0] if "jeton-secret" in arg]
    assert arguments_avec_secret == ["http.extraheader=Authorization: Bearer jeton-secret"]
    assert commands[1] == ["git", "-C", "/opt/app", "reset", "--hard", "FETCH_HEAD"]


def test_fetch_and_reset_gitlab_sans_token_anonyme() -> None:
    """Sans token GitLab, le fetch tente une connexion anonyme (avertie)."""
    runner = recording_runner()
    fetch_and_reset(Path("/opt/app"), "main", "gitlab", token_provider=lambda: "", runner=runner)
    assert not any("-c" in command for command in runner.commands)  # type: ignore[attr-defined]


# ----------------------------------------------------------------------
# Venv, dépendances, relance.
# ----------------------------------------------------------------------


def test_venv_python_detete(tmp_path: Path) -> None:
    """L'interprète du venv est trouvé selon la plateforme."""
    expected = tmp_path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    expected.parent.mkdir(parents=True)
    expected.write_text("#!/bin/sh\n", encoding="utf-8")
    assert venv_python(tmp_path) == expected
    assert venv_python(tmp_path / "ailleurs") is None


def test_install_dependencies_succes_et_echec(tmp_path: Path) -> None:
    """pip install réussi → True ; code non nul → False sans lever."""
    interpreter = tmp_path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("#!/bin/sh\n", encoding="utf-8")

    ok = install_dependencies(tmp_path, runner=lambda _c, **_k: subprocess.CompletedProcess([], 0))
    assert ok is True

    failed = install_dependencies(
        tmp_path, runner=lambda _c, **_k: subprocess.CompletedProcess([], 1)
    )
    assert failed is False


def test_install_dependencies_sans_venv(tmp_path: Path) -> None:
    """Sans .venv, aucune commande n'est lancée."""
    called: List[Any] = []
    assert (
        install_dependencies(tmp_path, runner=lambda command, **_k: called.append(command)) is False
    )
    assert called == []


# ----------------------------------------------------------------------
# Cycle complet (intégration Git locale).
# ----------------------------------------------------------------------


def test_update_app_deploie_la_nouvelle_version(tmp_path: Path) -> None:
    """Le cycle complet déploie effectivement origin/main dans le clone."""
    clone, _workdir = make_git_sandbox(tmp_path)

    success = update_app(
        app_dir=clone,
        pid=1234,
        branch="main",
        provider="github",
        relaunch=False,
        is_alive=lambda _pid: False,
    )

    assert success is True
    assert (clone / "version.txt").read_text(encoding="utf-8").strip() == "0.0.2"
    assert (clone / "nouveau_fichier.txt").exists()


def test_update_app_abort_sur_modifications_locales_refusees(tmp_path: Path) -> None:
    """Un dépôt sale avec refus de confirmation laisse tout en l'état."""
    clone, _workdir = make_git_sandbox(tmp_path)
    (clone / "version.txt").write_text("0.0.1-modifie\n", encoding="utf-8")

    success = update_app(
        app_dir=clone,
        pid=1234,
        branch="main",
        provider="github",
        relaunch=False,
        is_alive=lambda _pid: False,
        confirm_dirty=lambda: False,
    )

    assert success is False
    assert (clone / "version.txt").read_text(encoding="utf-8") == "0.0.1-modifie\n"


def test_update_app_deploie_sur_modifications_acceptees(tmp_path: Path) -> None:
    """Un dépôt sale avec confirmation écrase les modifications locales."""
    clone, _workdir = make_git_sandbox(tmp_path)
    (clone / "version.txt").write_text("0.0.1-modifie\n", encoding="utf-8")

    success = update_app(
        app_dir=clone,
        pid=1234,
        branch="main",
        provider="github",
        relaunch=False,
        is_alive=lambda _pid: False,
        confirm_dirty=lambda: True,
    )

    assert success is True
    assert (clone / "version.txt").read_text(encoding="utf-8").strip() == "0.0.2"


# ----------------------------------------------------------------------
# Auto-relocalisation.
# ----------------------------------------------------------------------


def test_relocate_copie_et_relance_detachee(tmp_path: Path, monkeypatch) -> None:
    """La phase 1 copie le script hors du dépôt et relance la copie avec --relaunched."""
    updater.setup_logging(tmp_path)
    spawned: Dict[str, Any] = {}

    def fake_popen(command: List[str], **kwargs: Any) -> None:
        spawned["command"] = list(command)
        spawned["kwargs"] = kwargs

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)

    with pytest.raises(SystemExit) as exit_info:
        relocate_and_rerun(4242, tmp_path, "gitlab", "dev", no_relaunch=True)

    assert exit_info.value.code == 0
    copy_path = Path(spawned["command"][1])
    assert copy_path.exists()  # la copie temporaire est réellement créée.
    assert copy_path != Path(updater.__file__).resolve()
    assert spawned["command"][2] == "4242"
    assert "--relaunched" in spawned["command"]
    assert "--no-relaunch" in spawned["command"]
    assert "--app-dir" in spawned["command"] and str(tmp_path) in spawned["command"]
    if os.name != "nt":
        assert spawned["kwargs"]["start_new_session"] is True
