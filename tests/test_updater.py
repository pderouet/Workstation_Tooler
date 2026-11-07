"""Tests headless du script updater.py en mode HTTP (aucun réseau, aucun Git).

Les archives sont de vraies tar.gz générées dans ``tmp_path`` (avec le dossier
racine qu'ajoutent GitHub et GitLab) ; l'ouvreur d'URL est une doublure.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import updater
from updater import (
    MANIFEST_FILE_NAME,
    USER_AGENT,
    build_parser,
    deploy_release,
    download_archive,
    extract_release,
    find_locally_modified_files,
    forge_headers,
    install_dependencies,
    is_process_alive,
    load_manifest,
    relocate_and_rerun,
    sha256_file,
    update_app,
    venv_python,
    wait_for_exit,
)


class FakeResponse:
    """Réponse HTTP factice : source binaire avec fin de fichier (read par blocs)."""

    def __init__(self, body: bytes) -> None:
        self._remaining = body

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            data, self._remaining = self._remaining, b""
        else:
            data, self._remaining = self._remaining[:size], self._remaining[size:]
        return data

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


def make_release_archive(path: Path, root_name: str, files: Dict[str, bytes]) -> bytes:
    """Écrit une archive tar.gz dont le contenu est emballé sous ``root_name/``.

    Reproduit le format servi par GitHub (tarball) et GitLab (archive.tar.gz).
    """
    with tarfile.open(path, "w:gz") as archive:
        root = tarfile.TarInfo(root_name)
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for name, content in files.items():
            info = tarfile.TarInfo(f"{root_name}/{name}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path.read_bytes()


# ----------------------------------------------------------------------
# Arguments et cycle de vie du processus.
# ----------------------------------------------------------------------


def test_parse_arguments_complets() -> None:
    """Les arguments attendus par l'application sont correctement interprétés."""
    args = build_parser().parse_args(
        [
            "4242",
            "--archive-url",
            "https://forge/release.tar.gz",
            "--app-dir",
            "/opt/app",
            "--provider",
            "gitlab",
            "--no-relaunch",
            "--relaunched",
        ]
    )
    assert args.pid == 4242
    assert args.archive_url == "https://forge/release.tar.gz"
    assert args.app_dir == "/opt/app"
    assert args.provider == "gitlab"
    assert args.no_relaunch is True
    assert args.relaunched is True


def test_parse_arguments_url_archive_requise() -> None:
    """L'URL d'archive est obligatoire : sans elle, argparse refuse."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["4242"])


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
    forced: List[int] = []

    result = wait_for_exit(
        4242,
        timeout=0.05,
        poll_interval=0.01,
        is_alive=lambda _pid: alive["status"],
        ask_force=lambda: True,
        force_kill=lambda pid: (alive.update(status=False), forced.append(pid)),
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
# En-têtes de forge et téléchargement.
# ----------------------------------------------------------------------


class FakeAppUpdaterModule:
    """Doublure de core.app_updater pour les lecteurs de jetons."""

    def __init__(self, gitlab: str = "", github: str = "") -> None:
        self._gitlab = gitlab
        self._github = github

    def gitlab_read_token(self) -> str:
        return self._gitlab

    def github_read_token(self) -> str:
        return self._github


def test_forge_headers_gitlab_et_github(monkeypatch, tmp_path: Path) -> None:
    """Chaque fournisseur présente son jeton dans l'en-tête attendu."""
    monkeypatch.setattr(
        updater,
        "_app_updater_module",
        lambda _app_dir: FakeAppUpdaterModule(gitlab="jeton-gl", github="jeton-gh"),
    )

    gitlab_headers = forge_headers("gitlab", tmp_path)
    assert gitlab_headers["PRIVATE-TOKEN"] == "jeton-gl"
    assert gitlab_headers["User-Agent"] == USER_AGENT

    github_headers = forge_headers("github", tmp_path)
    assert github_headers["Authorization"] == "Bearer jeton-gh"


def test_forge_headers_anonyme_sans_jeton(monkeypatch, tmp_path: Path) -> None:
    """Sans jeton (dépôt public GitHub), aucune en-tête d'authentification."""
    monkeypatch.setattr(updater, "_app_updater_module", lambda _app_dir: FakeAppUpdaterModule())
    assert forge_headers("github", tmp_path) == {"User-Agent": USER_AGENT}


def test_forge_headers_sans_module_applicatif(monkeypatch, tmp_path: Path) -> None:
    """Si le module applicatif est indisponible, le téléchargement reste anonyme."""
    monkeypatch.setattr(updater, "_app_updater_module", lambda _app_dir: None)
    headers = forge_headers("gitlab", tmp_path)
    assert headers == {"User-Agent": USER_AGENT}


def test_download_archive_ecrit_les_octets(tmp_path: Path) -> None:
    """Le téléchargement recopie le corps de la réponse vers le fichier local."""
    destination = tmp_path / "release.tar.gz"

    def opener(request: Any, timeout: int) -> FakeResponse:
        assert request.full_url == "https://forge/release.tar.gz"
        assert request.headers.get("User-agent") == USER_AGENT
        return FakeResponse(b"contenu-archive")

    download_archive(
        "https://forge/release.tar.gz",
        destination,
        headers={"User-Agent": USER_AGENT},
        opener=opener,
    )
    assert destination.read_bytes() == b"contenu-archive"


# ----------------------------------------------------------------------
# Extraction des archives de release.
# ----------------------------------------------------------------------


def test_extract_release_retire_le_dossier_racine(tmp_path: Path) -> None:
    """Le dossier racine ajouté par la forge est retiré : fichiers à plat."""
    archive = tmp_path / "release.tar.gz"
    make_release_archive(
        archive,
        "Workstation_Tooler-abc123",
        {"version.txt": b"0.0.2\n", "core/__init__.py": b"...\n", "updater.py": b"# maj\n"},
    )

    destination = tmp_path / "extraction"
    files = extract_release(archive, destination)

    assert files == ["core/__init__.py", "updater.py", "version.txt"]
    assert (destination / "version.txt").read_bytes() == b"0.0.2\n"
    assert not (destination / "Workstation_Tooler-abc123").exists()


def test_extract_release_fichier_unique_non_deguise(tmp_path: Path) -> None:
    """Une archive sans dossier racine (fichier unique) reste intacte."""
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("version.txt")
        payload = b"0.0.3\n"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    destination = tmp_path / "extraction"
    files = extract_release(archive, destination)

    assert files == ["version.txt"]
    assert (destination / "version.txt").read_bytes() == b"0.0.3\n"


def test_extract_release_refuse_la_traverse(tmp_path: Path) -> None:
    """Un membre d'archive hors de la cible (..) est rejeté (filtre data)."""
    archive = tmp_path / "piege.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.addfile(tarfile.TarInfo("root"))
        info = tarfile.TarInfo("root/../malicieux.txt")
        payload = b"hors cible"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(tarfile.TarError):
        extract_release(archive, tmp_path / "extraction")
    assert not (tmp_path / "malicieux.txt").exists()


# ----------------------------------------------------------------------
# Manifeste, recouvrement, purge.
# ----------------------------------------------------------------------


def write_app(tmp_path: Path, version: str, extra: Optional[Dict[str, str]] = None) -> Path:
    """Construit une installation applicative factice avec son manifeste."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "version.txt").write_text(f"{version}\n", encoding="utf-8")
    for name, content in (extra or {}).items():
        target = app_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    manifest = {
        "files": {
            path.relative_to(app_dir).as_posix(): sha256_file(path)
            for path in app_dir.rglob("*")
            if path.is_file()
        }
    }
    (app_dir / MANIFEST_FILE_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return app_dir


def test_manifest_aller_retour_et_corrompu(tmp_path: Path) -> None:
    """Le manifeste charge ce qui a été écrit ; un fichier corrompu vaut vide."""
    updater.save_manifest(tmp_path, {"a.txt": "h1", "b/c.txt": "h2"})
    assert load_manifest(tmp_path) == {"a.txt": "h1", "b/c.txt": "h2"}

    (tmp_path / MANIFEST_FILE_NAME).write_text("{invalide", encoding="utf-8")
    assert load_manifest(tmp_path) == {}


def test_deploy_release_recouvre_purge_et_manifeste(tmp_path: Path) -> None:
    """Recouvrement des fichiers, purge des retraits amont, manifeste actualisé."""
    app_dir = write_app(tmp_path, "0.0.1", {"obsolete.txt": "vieux"})
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "version.txt").write_text("0.0.2\n", encoding="utf-8")
    (release_dir / "nouveau.txt").write_text("nouveau\n", encoding="utf-8")

    assert deploy_release(app_dir, release_dir, confirm_modified=lambda _n: True) is True

    assert (app_dir / "version.txt").read_text(encoding="utf-8") == "0.0.2\n"
    assert (app_dir / "nouveau.txt").exists()
    assert not (app_dir / "obsolete.txt").exists()  # purge du retrait amont.
    manifest = load_manifest(app_dir)
    # Le manifeste liste les fichiers déployés, sans se référencer lui-même.
    assert set(manifest) == {"version.txt", "nouveau.txt"}


def test_deploy_release_sans_manifeste_recouvre_sans_garde(tmp_path: Path) -> None:
    """Première mise à jour (aucun manifeste) : recouvrement direct, pas de garde."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "version.txt").write_text("0.0.1-modifie\n", encoding="utf-8")
    (app_dir / "settings.local").write_text("préservé\n", encoding="utf-8")

    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "version.txt").write_text("0.0.2\n", encoding="utf-8")

    confirm_calls: List[int] = []
    assert (
        deploy_release(
            app_dir, release_dir, confirm_modified=lambda n: (confirm_calls.append(n), True)[1]
        )
        is True
    )
    assert confirm_calls == []  # aucune référence : pas de garde.
    assert (app_dir / "version.txt").read_text(encoding="utf-8") == "0.0.2\n"
    assert (app_dir / "settings.local").exists()  # hors manifeste : intact.


def test_deploy_release_garde_fichiers_modifies_localement(tmp_path: Path) -> None:
    """Un fichier déployé modifié localement déclenche la garde (refus = abandon)."""
    app_dir = write_app(tmp_path, "0.0.1")
    (app_dir / "version.txt").write_text("0.0.1-modifie\n", encoding="utf-8")  # dérive locale.

    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "version.txt").write_text("0.0.2\n", encoding="utf-8")

    confirm_calls: List[int] = []
    assert (
        deploy_release(
            app_dir, release_dir, confirm_modified=lambda n: (confirm_calls.append(n), False)[1]
        )
        is False
    )
    assert confirm_calls == [1]
    assert (app_dir / "version.txt").read_text(encoding="utf-8") == "0.0.1-modifie\n"


def test_find_locally_modified_files_sans_manifeste(tmp_path: Path) -> None:
    """Sans manifeste, aucun fichier n'est considéré modifié."""
    app_dir = write_app(tmp_path, "0.0.1")
    (app_dir / MANIFEST_FILE_NAME).unlink()
    assert find_locally_modified_files(app_dir, ["version.txt"], load_manifest(app_dir)) == []


# ----------------------------------------------------------------------
# Cycle complet (sans Git, ouvreur HTTP factice).
# ----------------------------------------------------------------------


def test_update_app_cycle_http_complet(tmp_path: Path) -> None:
    """Télécharge, extrait, déploie : version à jour, purge et manifeste écrits."""
    app_dir = write_app(tmp_path, "0.0.1", {"ancien_module.py": "supprimé en 0.0.2"})

    archive_bytes = make_release_archive(
        tmp_path / "release.tar.gz",
        "Workstation_Tooler-def456",
        {"version.txt": b"0.0.2\n", "nouveau_module.py": b"print('ok')\n"},
    )

    requested: Dict[str, Any] = {}

    def opener(request: Any, timeout: int) -> FakeResponse:
        requested["url"] = request.full_url
        return FakeResponse(archive_bytes)

    success = update_app(
        app_dir=app_dir,
        pid=1234,
        provider="github",
        archive_url="https://forge.example.com/release.tar.gz",
        relaunch=False,
        is_alive=lambda _pid: False,
        opener=opener,
    )

    assert success is True
    assert requested["url"] == "https://forge.example.com/release.tar.gz"
    assert (app_dir / "version.txt").read_text(encoding="utf-8") == "0.0.2\n"
    assert (app_dir / "nouveau_module.py").exists()
    assert not (app_dir / "ancien_module.py").exists()  # purge du retrait amont.
    assert set(load_manifest(app_dir)) == {"version.txt", "nouveau_module.py"}


def test_update_app_abandonne_sur_garde_refusee(tmp_path: Path) -> None:
    """Une modification locale refusée interrompt le déploiement, rien n'écrase."""
    app_dir = write_app(tmp_path, "0.0.1")
    (app_dir / "version.txt").write_text("0.0.1-local\n", encoding="utf-8")

    archive_bytes = make_release_archive(
        tmp_path / "release.tar.gz", "Workstation_Tooler-def456", {"version.txt": b"0.0.2\n"}
    )

    success = update_app(
        app_dir=app_dir,
        pid=1234,
        provider="github",
        archive_url="https://forge.example.com/release.tar.gz",
        relaunch=False,
        is_alive=lambda _pid: False,
        opener=lambda _r, timeout=10: FakeResponse(archive_bytes),
    )
    # En environnement sans dialogue, le repli console (EOF) refuse : abandon propre.
    assert success is False
    assert (app_dir / "version.txt").read_text(encoding="utf-8") == "0.0.1-local\n"


# ----------------------------------------------------------------------
# Venv, dépendances, relance, auto-relocalisation.
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


def test_relocate_copie_et_relance_detachee(tmp_path: Path, monkeypatch) -> None:
    """La phase 1 copie le script hors du dépôt et relance la copie avec --relaunched."""
    updater.setup_logging(tmp_path)
    spawned: Dict[str, Any] = {}

    def fake_popen(command: List[str], **kwargs: Any) -> None:
        spawned["command"] = list(command)
        spawned["kwargs"] = kwargs

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)

    with pytest.raises(SystemExit) as exit_info:
        relocate_and_rerun(
            4242, tmp_path, "gitlab", "https://forge/release.tar.gz", no_relaunch=True
        )

    assert exit_info.value.code == 0
    copy_path = Path(spawned["command"][1])
    assert copy_path.exists()  # la copie temporaire est réellement créée.
    assert copy_path != Path(updater.__file__).resolve()
    assert spawned["command"][2] == "4242"
    assert "--relaunched" in spawned["command"]
    assert "--no-relaunch" in spawned["command"]
    archive_index = spawned["command"].index("--archive-url")
    assert spawned["command"][archive_index + 1] == "https://forge/release.tar.gz"
    assert "--app-dir" in spawned["command"] and str(tmp_path) in spawned["command"]
    if os.name != "nt":
        assert spawned["kwargs"]["start_new_session"] is True
