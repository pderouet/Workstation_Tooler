"""Modèles de données du catalogue distant et parsing des manifests YAML.

Le catalogue distant décrit chaque application par un ``app.yaml`` (métadonnées
et détection de version) et chaque version par un ``manifest.yaml`` (fichiers
et actions à appliquer). Ce module transforme ces YAML en modèles de données
immuables, avec une validation stricte : tout champ inconnu, manquant ou
incohérent lève une :class:`ManifestError` afin qu'une application mal
déclarée soit signalée plutôt qu'interprétée silencieusement de travers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import yaml

from engine.version import latest_version


class ManifestError(ValueError):
    """Erreur de lecture ou de validation d'un manifest du catalogue."""


class ActionKind(str, Enum):
    """Mot-clé d'action applicable à un fichier du manifest."""

    DECOMPRESS = "decompress"
    COPY = "copy"
    ENSURE_CONTENT = "ensure_content"


@dataclass(frozen=True)
class VersionDetection:
    """Déclaration de la commande détectant la version installée d'une application.

    Attributes:
        binary: Nom du binaire à exécuter (résolu via ``PATH``).
        pattern: Expression régulière appliquée à la sortie standard ; le
            premier groupe capturé (ou la correspondance entière s'il n'y en a
            pas) fournit le numéro de version.
        args: Arguments passés au binaire.
        fallback_binary: Binaire de substitution si ``binary`` est introuvable
            (ex. ``powershell`` pour ``pwsh``).
        timeout_seconds: Délai maximal d'exécution de la commande.
    """

    binary: str
    pattern: str
    args: Tuple[str, ...] = ()
    fallback_binary: str = ""
    timeout_seconds: int = 5


@dataclass(frozen=True)
class FileAction:
    """Action à appliquer à un fichier d'une version donnée.

    Attributes:
        source: Chemin du fichier dans le dossier de la version (relatif,
            sans composant ``..``).
        action: Mot-clé d'action (``copy``, ``decompress`` ou ``ensure_content``).
        target: Chemin cible local (avec expansion ``~`` et ``${VAR}``).
        mode: Permissions octales optionnelles appliquées après copie
            (ex. ``"755"``).
    """

    source: str
    action: ActionKind
    target: str
    mode: str = ""


@dataclass(frozen=True)
class VersionManifest:
    """Contenu d'un ``manifest.yaml`` : fichiers d'une version d'une application.

    Attributes:
        application: Nom de l'application (dossier parent).
        version: Version concernée (nom du dossier).
        files: Actions de fichiers, exécutées dans l'ordre de déclaration.
    """

    application: str
    version: str
    files: Tuple[FileAction, ...]


@dataclass(frozen=True)
class AppMetadata:
    """Contenu d'un ``app.yaml`` : métadonnées d'une application.

    Attributes:
        name: Nom unique de l'application (nom du dossier).
        display_name: Libellé lisible affiché dans l'UI.
        enabled: ``False`` : l'application est ignorée par le moteur.
        detection: Déclaration de la détection de version installée.
    """

    name: str
    display_name: str
    enabled: bool
    detection: VersionDetection


@dataclass
class Application:
    """Application du catalogue : métadonnées et versions disponibles.

    Attributes:
        metadata: Métadonnées lues dans ``app.yaml``.
        versions: Noms des dossiers de version déclarés sur le partage.
    """

    metadata: AppMetadata
    versions: List[str] = field(default_factory=list)

    @property
    def latest_version(self) -> Optional[str]:
        """Version la plus élevée parmi les versions disponibles."""
        return latest_version(self.versions)


@dataclass
class Catalog:
    """Catalogue complet chargé depuis le chemin réseau.

    Attributes:
        applications: Applications valides et actives, indexées par nom.
        skipped: Applications ignorées (clé ``<application>/<raison>``),
            avec la raison de l'exclusion, à des fins de diagnostic.
    """

    applications: Dict[str, Application] = field(default_factory=dict)
    skipped: Dict[str, str] = field(default_factory=dict)

    def enabled_applications(self) -> List[Application]:
        """Retourne les applications actives du catalogue."""
        return [app for app in self.applications.values() if app.metadata.enabled]


# ----------------------------------------------------------------------
# Parsing / validation des manifests.
# ----------------------------------------------------------------------

_APP_KEYS = frozenset({"application", "display_name", "enabled", "version_detection"})
_DETECTION_KEYS = frozenset({"binary", "fallback_binary", "args", "pattern", "timeout_seconds"})
_MANIFEST_KEYS = frozenset({"version", "files"})
_FILE_KEYS = frozenset({"source", "action", "target", "mode"})

_MODE_PATTERN = re.compile(r"^[0-7]{3,4}$")


def parse_app_metadata(application_name: str, raw_text: str) -> AppMetadata:
    """Valide et convertit le contenu d'un ``app.yaml`` en :class:`AppMetadata`.

    Args:
        application_name: Nom du dossier de l'application (référence de
            validation du champ ``application``).
        raw_text: Contenu brut du fichier YAML.

    Returns:
        Les métadonnées de l'application.

    Raises:
        ManifestError: Si le YAML est invalide ou ne respecte pas le schéma.
    """
    data = _load_yaml_dict(raw_text, context=f"app.yaml de '{application_name}'")
    _reject_unknown_keys(data, _APP_KEYS, context=f"app.yaml de '{application_name}'")

    declared_name = _optional_str(
        data, "application", default=application_name, context="application"
    )
    if declared_name != application_name:
        raise ManifestError(
            f"app.yaml de '{application_name}' : le champ 'application' "
            f"({declared_name!r}) ne correspond pas au nom du dossier."
        )

    display_name = _optional_str(
        data,
        "display_name",
        default=_default_display_name(application_name),
        context="display_name",
    )

    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ManifestError(f"app.yaml de '{application_name}' : 'enabled' doit être un booléen.")

    detection_data = data.get("version_detection")
    if not isinstance(detection_data, dict):
        raise ManifestError(
            f"app.yaml de '{application_name}' : 'version_detection' est requis (section)."
        )
    detection = _parse_detection(detection_data, application_name)

    return AppMetadata(
        name=application_name,
        display_name=display_name,
        enabled=enabled,
        detection=detection,
    )


def parse_version_manifest(application: str, version: str, raw_text: str) -> VersionManifest:
    """Valide et convertit le contenu d'un ``manifest.yaml`` en :class:`VersionManifest`.

    Args:
        application: Nom de l'application propriétaire de la version.
        version: Nom du dossier de la version (référence de validation du
            champ ``version``).
        raw_text: Contenu brut du fichier YAML.

    Returns:
        Le manifest de la version.

    Raises:
        ManifestError: Si le YAML est invalide ou ne respecte pas le schéma.
    """
    context = f"manifest.yaml de '{application}/{version}'"
    data = _load_yaml_dict(raw_text, context=context)
    _reject_unknown_keys(data, _MANIFEST_KEYS, context=context)

    declared_version = _optional_str(data, "version", default=version, context="version")
    if declared_version != version:
        raise ManifestError(
            f"{context} : le champ 'version' ({declared_version!r}) ne correspond "
            f"pas au nom du dossier de version."
        )

    files_data = data.get("files")
    if not isinstance(files_data, list) or not files_data:
        raise ManifestError(f"{context} : 'files' doit être une liste non vide.")

    files: List[FileAction] = []
    for index, entry in enumerate(files_data):
        entry_context = f"{context} (fichier #{index + 1})"
        if not isinstance(entry, dict):
            raise ManifestError(
                f"{entry_context} : chaque entrée de 'files' doit être une section."
            )
        _reject_unknown_keys(entry, _FILE_KEYS, context=entry_context)
        files.append(_parse_file_action(entry, entry_context))

    return VersionManifest(application=application, version=version, files=tuple(files))


# ----------------------------------------------------------------------
# Helpers de validation.
# ----------------------------------------------------------------------


def _load_yaml_dict(raw_text: str, context: str) -> Dict[str, Any]:
    """Charge un manifest YAML en s'assurant d'obtenir une section racine.

    Args:
        raw_text: Contenu brut du fichier YAML.
        context: Description du fichier pour les messages d'erreur.

    Returns:
        La section racine du document YAML.

    Raises:
        ManifestError: Si le YAML est illisible ou que la racine n'est pas une
            section (mapping).
    """
    try:
        content = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"{context} : YAML invalide ({exc}).") from exc
    if not isinstance(content, dict):
        raise ManifestError(f"{context} : la racine du document doit être une section.")
    return content


def _reject_unknown_keys(data: Dict[str, Any], allowed: frozenset, context: str) -> None:
    """Rejette explicitement les clés hors schéma plutôt que de les ignorer."""
    unknown = set(data) - allowed
    if unknown:
        raise ManifestError(f"{context} : clés inconnues {sorted(unknown)}.")


def _parse_detection(data: Dict[str, Any], application_name: str) -> VersionDetection:
    """Valide la section ``version_detection`` d'un ``app.yaml``."""
    context = f"app.yaml de '{application_name}' (version_detection)"
    _reject_unknown_keys(data, _DETECTION_KEYS, context=context)

    binary = _require_str(data, "binary", context)
    pattern = _require_str(data, "pattern", context)
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ManifestError(f"{context} : 'pattern' n'est pas une regex valide ({exc}).") from exc

    fallback_binary = _optional_str(data, "fallback_binary", default="", context="fallback_binary")

    args_data = data.get("args", [])
    if not isinstance(args_data, list) or not all(isinstance(a, str) for a in args_data):
        raise ManifestError(f"{context} : 'args' doit être une liste de chaînes.")

    timeout = data.get("timeout_seconds", 5)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ManifestError(
            f"{context} : 'timeout_seconds' doit être un entier strictement positif."
        )

    return VersionDetection(
        binary=binary,
        pattern=pattern,
        args=tuple(args_data),
        fallback_binary=fallback_binary,
        timeout_seconds=timeout,
    )


def _parse_file_action(entry: Dict[str, Any], context: str) -> FileAction:
    """Valide une entrée de la liste ``files`` d'un manifest."""
    source = _require_str(entry, "source", context)
    source_parts = PurePosixPath(source).parts
    if source.startswith(("/", "\\")) or ".." in source_parts:
        raise ManifestError(f"{context} : 'source' doit être un chemin relatif sans '..'.")

    action_name = _require_str(entry, "action", context)
    try:
        action = ActionKind(action_name)
    except ValueError:
        valid = ", ".join(kind.value for kind in ActionKind)
        raise ManifestError(
            f"{context} : 'action' inconnue {action_name!r} (valides : {valid})."
        ) from None

    target = _require_str(entry, "target", context)

    mode = _optional_str(entry, "mode", default="", context="mode")
    if mode and not _MODE_PATTERN.match(mode):
        raise ManifestError(f"{context} : 'mode' doit être octal (ex. '755').")

    return FileAction(source=source, action=action, target=target, mode=mode)


def _require_str(data: Dict[str, Any], key: str, context: str) -> str:
    """Extrait une clé obligatoire et non vide, sous forme de chaîne."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{context} : '{key}' est requis (chaîne non vide).")
    return value


def _optional_str(data: Dict[str, Any], key: str, default: str, context: str) -> str:
    """Extrait une clé optionnelle ; la valeur fournie doit rester une chaîne."""
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, str):
        raise ManifestError(f"{context} : doit être une chaîne.")
    return value


def _default_display_name(application_name: str) -> str:
    """Déduit un libellé lisible du nom technique de l'application."""
    return application_name.replace("_", " ").title()
