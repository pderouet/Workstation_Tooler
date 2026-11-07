"""Tests headless des exécuteurs d'actions (copy, decompress, ensure_content)."""

from __future__ import annotations

import gzip
import tarfile
import zipfile
from pathlib import Path

import pytest

from engine.actions import (
    copy_file,
    decompress_archive,
    ensure_content,
    execute_file_action,
    expand_target,
)
from engine.models import ActionKind, FileAction


def test_expand_target_variable_et_home(tmp_path: Path, monkeypatch) -> None:
    """Les cibles acceptent ~ et les variables d'environnement."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WT_CIBLE", str(tmp_path / "var"))
    assert expand_target("~/fichier") == tmp_path / "home" / "fichier"
    assert expand_target("${WT_CIBLE}/sous/fichier") == tmp_path / "var" / "sous" / "fichier"


def test_copy_file_cree_les_parents_et_applique_le_mode(tmp_path: Path) -> None:
    """La copie crée l'arborescence cible et applique les permissions octales."""
    source = tmp_path / "source.txt"
    source.write_text("contenu", encoding="utf-8")

    copy_file(source, str(tmp_path / "a" / "b" / "cible.txt"), mode="755")

    target = tmp_path / "a" / "b" / "cible.txt"
    assert target.read_text(encoding="utf-8") == "contenu"
    assert (target.stat().st_mode & 0o777) == 0o755


def test_decompress_tar_gz(tmp_path: Path) -> None:
    """Une archive tar.gz est extraite en respectant l'arborescence interne."""
    archive = tmp_path / "outil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        payload = tmp_path / "bin-outil"
        payload.write_text("#!/bin/sh\necho outil\n", encoding="utf-8")
        tar.add(payload, arcname="bin/outil")

    destination = tmp_path / "extraction"
    decompress_archive(archive, str(destination))

    extracted = destination / "bin" / "outil"
    assert extracted.read_text(encoding="utf-8").startswith("#!/bin/sh")


def test_decompress_zip(tmp_path: Path) -> None:
    """Une archive zip est extraite en respectant l'arborescence interne."""
    archive = tmp_path / "outil.zip"
    with zipfile.ZipFile(archive, "w") as zip_archive:
        zip_archive.writestr("dossier/binaire", "contenu binaire")

    destination = tmp_path / "extraction"
    decompress_archive(archive, str(destination))

    assert (destination / "dossier" / "binaire").read_text(encoding="utf-8") == ("contenu binaire")


def test_decompress_zip_refuse_la_traverse(tmp_path: Path) -> None:
    """Un membre zip hors du répertoire cible (..) est refusé avant extraction."""
    archive = tmp_path / "piege.zip"
    with zipfile.ZipFile(archive, "w") as zip_archive:
        zip_archive.writestr("../malicieux.txt", "hors cible")

    with pytest.raises(ValueError, match="traverse"):
        decompress_archive(archive, str(tmp_path / "extraction"))
    assert not (tmp_path / "malicieux.txt").exists()


def test_decompress_gzip_simple(tmp_path: Path) -> None:
    """Un fichier .gz simple est décompressé en un fichier du même nom sans suffixe."""
    compressed = tmp_path / "notes.txt.gz"
    with gzip.open(compressed, "wb") as gz:
        gz.write("contenu decompressé".encode("utf-8"))

    destination = tmp_path / "extraction"
    decompress_archive(compressed, str(destination))

    assert (destination / "notes.txt").read_text(encoding="utf-8") == "contenu decompressé"


def test_decompress_format_inconnu(tmp_path: Path) -> None:
    """Une extension non reconnue est refusée explicitement."""
    source = tmp_path / "outil.exe"
    source.write_bytes(b"MZ...")
    with pytest.raises(ValueError, match="Format d'archive non reconnu"):
        decompress_archive(source, str(tmp_path / "extraction"))


def test_ensure_content_cree_la_cible_absente(tmp_path: Path) -> None:
    """Une cible absente est créée avec le contenu exact du fragment."""
    fragment = tmp_path / "fragment.conf"
    fragment.write_text("parametre=valeur\n", encoding="utf-8")
    target = tmp_path / "conf" / "outil.conf"

    assert ensure_content(fragment, str(target)) is True
    assert target.read_text(encoding="utf-8") == "parametre=valeur\n"


def test_ensure_content_deja_present_sans_effet(tmp_path: Path) -> None:
    """Un contenu déjà présent n'entraîne ni ajout ni duplication."""
    fragment = tmp_path / "fragment.conf"
    fragment.write_text("parametre=valeur\n", encoding="utf-8")
    target = tmp_path / "outil.conf"
    target.write_text("existant=1\nparametre=valeur\n", encoding="utf-8")

    assert ensure_content(fragment, str(target)) is False
    assert target.read_text(encoding="utf-8") == "existant=1\nparametre=valeur\n"


def test_ensure_content_ajoute_avec_separateur(tmp_path: Path) -> None:
    """Le fragment est ajouté en fin de fichier, précédé d'un passage à la ligne."""
    fragment = tmp_path / "fragment.conf"
    fragment.write_text("parametre=valeur\n", encoding="utf-8")
    target = tmp_path / "outil.conf"
    target.write_text("existant=1\n", encoding="utf-8")

    assert ensure_content(fragment, str(target)) is True
    assert target.read_text(encoding="utf-8") == "existant=1\nparametre=valeur\n"


def test_execute_file_action_dispatch(tmp_path: Path) -> None:
    """L'exécuteur générique route vers le bon exécuteur selon l'action."""
    source = tmp_path / "binaire"
    source.write_text("un binaire", encoding="utf-8")

    action = FileAction(source="binaire", action=ActionKind.COPY, target=str(tmp_path / "cible"))
    assert execute_file_action(action, source) is True
    assert (tmp_path / "cible").read_text(encoding="utf-8") == "un binaire"
