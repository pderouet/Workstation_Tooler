"""Exécuteurs des mots-clés d'action déclarés dans les manifests.

Chaque fichier d'une version est d'abord recopié localement par le moteur
(téléchargement depuis le chemin réseau vers un répertoire temporaire), puis
l'exécuteur correspondant à son action s'applique au système de fichiers
local :

    - ``copy`` : copie du fichier vers sa cible (permissions optionnelles) ;
    - ``decompress`` : décompression d'une archive (``zip``, ``tar.gz``,
      ``tgz``, ``tar.bz2``, ``tar.xz``, ``tar``, ou ``gz`` simple) vers un
      répertoire cible ;
    - ``ensure_content`` : garantit que le contenu du fragment source est
      présent dans le fichier cible (création, ajout, ou aucune action).

Les extractions sont durcies contre les chemins de traverses (``..``,
chemins absolus) : le contenu d'une archive ne doit jamais s'échapper de son
répertoire cible.
"""

from __future__ import annotations

import gzip
import os
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from engine.models import ActionKind, FileAction

#: Extensions d'archives gérées par :func:`decompress_archive`.
_TAR_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar")


def expand_target(target: str) -> Path:
    """Résout un chemin cible déclaré dans un manifest.

    Args:
        target: Chemin cible, pouvant contenir ``~`` et des variables
            d'environnement (``${HOME}``, etc.).

    Returns:
        Le chemin local résolu.
    """
    return Path(os.path.expandvars(os.path.expanduser(target)))


def execute_file_action(action: FileAction, downloaded: Path) -> bool:
    """Exécute l'action déclarée sur un fichier déjà recopié localement.

    Args:
        action: Action déclarée dans le manifest.
        downloaded: Fichier source, déjà téléchargé localement.

    Returns:
        ``True`` si la cible a été modifiée (ou créée), ``False`` si aucune
        modification n'était nécessaire (ex. contenu déjà présent).

    Raises:
        ValueError: Si l'action ou le format d'archive n'est pas géré.
        OSError: Si une opération fichier échoue.
    """
    if action.action is ActionKind.COPY:
        copy_file(downloaded, action.target, action.mode)
        return True
    if action.action is ActionKind.DECOMPRESS:
        decompress_archive(downloaded, action.target)
        return True
    if action.action is ActionKind.ENSURE_CONTENT:
        return ensure_content(downloaded, action.target)
    raise ValueError(f"Action non gérée : {action.action!r}.")


def copy_file(source: Path, target: str, mode: str = "") -> None:
    """Copie un fichier vers sa cible, en créant les répertoires parents.

    Args:
        source: Fichier local à copier.
        target: Chemin cible (avec expansion ``~`` et ``${VAR}``).
        mode: Permissions octales optionnelles appliquées après copie
            (ex. ``"755"``).
    """
    target_path = expand_target(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target_path)
    if mode:
        target_path.chmod(int(mode, 8))


def decompress_archive(source: Path, target: str) -> None:
    """Décompresse une archive vers un répertoire cible.

    Le format est déduit de l'extension du fichier source.

    Args:
        source: Archive locale à extraire.
        target: Répertoire cible (avec expansion ``~`` et ``${VAR}``).

    Raises:
        ValueError: Si le format d'archive n'est pas reconnu.
        OSError: Si l'extraction échoue.
    """
    target_dir = expand_target(target)
    target_dir.mkdir(parents=True, exist_ok=True)

    name = source.name.lower()
    if name.endswith(".zip"):
        _extract_zip(source, target_dir)
    elif name.endswith(_TAR_SUFFIXES):
        with tarfile.open(source) as archive:
            # Filtre "data" (Python 3.12+) : refuse chemins absolus, traverses
            # de répertoires et liens dangereux avant extraction.
            archive.extractall(target_dir, filter="data")
    elif name.endswith(".gz"):
        _decompress_gzip(source, target_dir)
    else:
        raise ValueError(
            f"Format d'archive non reconnu pour '{source.name}' "
            "(attendus : .zip, .tar.gz, .tgz, .tar.bz2, .tar.xz, .tar, .gz)."
        )


def ensure_content(source: Path, target: str) -> bool:
    """Garantit la présence du contenu du fragment source dans le fichier cible.

    Comportement :
        - cible absente : création avec le contenu du fragment ;
        - contenu déjà présent dans la cible : aucune modification ;
        - sinon : ajout du fragment en fin de fichier, précédé d'un passage à
          la ligne si la cible ne se termine pas déjà par une ligne vide.

    Args:
        source: Fragment local dont le contenu doit exister dans la cible.
        target: Fichier cible (avec expansion ``~`` et ``${VAR}``).

    Returns:
        ``True`` si la cible a été créée ou modifiée, ``False`` si le contenu
        était déjà présent.
    """
    fragment = source.read_text(encoding="utf-8")
    target_path = expand_target(target)

    if not target_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(fragment, encoding="utf-8")
        return True

    existing = target_path.read_text(encoding="utf-8")
    if fragment in existing:
        return False

    separator = "" if existing.endswith("\n") or not existing else "\n"
    with target_path.open("a", encoding="utf-8") as target_file:
        target_file.write(f"{separator}{fragment}")
    return True


def _extract_zip(source: Path, target_dir: Path) -> None:
    """Extrait une archive zip après validation des chemins de ses membres."""
    with zipfile.ZipFile(source) as archive:
        for member in archive.namelist():
            _check_member_path(member)
        archive.extractall(target_dir)


def _decompress_gzip(source: Path, target_dir: Path) -> None:
    """Décompresse un fichier ``.gz`` simple (sans conteneur tar)."""
    destination = target_dir / source.name[: -len(".gz")]
    with gzip.open(source, "rb") as compressed, destination.open("wb") as output:
        shutil.copyfileobj(compressed, output)


def _check_member_path(member: str) -> None:
    """Refuse un membre d'archive au chemin dangereux pour l'extraction zip.

    Args:
        member: Chemin du membre tel que déclaré dans l'archive.

    Raises:
        ValueError: Si le chemin est absolu, contient une traverse ``..`` ou
            un séparateur/lettre de lecteur suspect.
    """
    normalized = PurePosixPath(member.replace("\\", "/"))
    if (
        normalized.is_absolute()
        or ".." in normalized.parts
        or ":" in member
        or member.startswith(("/", "\\"))
    ):
        raise ValueError(f"Chemin de membre d'archive refusé (traverse) : {member!r}.")
