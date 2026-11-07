"""Accès structuré au catalogue distant des mises à jour.

Connaît l'agencement du catalogue (un dossier par application contenant un
``app.yaml`` et un dossier par version contenant un ``manifest.yaml``) et
délègue les lectures effectives au :class:`~engine.storage.StorageBackend`.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from engine.models import AppMetadata, VersionManifest, parse_app_metadata, parse_version_manifest
from engine.storage import StorageBackend

#: Nom du fichier de métadonnées, à la racine du dossier de chaque application.
APP_METADATA_FILENAME = "app.yaml"

#: Nom du manifest, à la racine du dossier de chaque version.
MANIFEST_FILENAME = "manifest.yaml"


class RemoteRepository:
    """Fournit une vue typée du catalogue décrit par le backend de stockage."""

    def __init__(self, backend: StorageBackend) -> None:
        """Initialise le repository sur le backend fourni.

        Args:
            backend: Backend d'accès à la racine du catalogue (SMB ou local).
        """
        self._backend = backend

    def list_application_names(self) -> List[str]:
        """Liste les applications du catalogue (dossiers contenant un ``app.yaml``).

        Returns:
            Les noms d'applications, triés.

        Raises:
            OSError: Si la racine du catalogue est inaccessible.
        """
        names: List[str] = []
        for entry in self._backend.listdir(""):
            if self._backend.is_dir(entry) and self._backend.exists(
                f"{entry}/{APP_METADATA_FILENAME}"
            ):
                names.append(entry)
        return sorted(names)

    def load_app_metadata(self, application: str) -> AppMetadata:
        """Charge et valide le ``app.yaml`` d'une application.

        Args:
            application: Nom de l'application (dossier).

        Returns:
            Les métadonnées de l'application.

        Raises:
            ManifestError: Si le fichier ne respecte pas le schéma.
            OSError: Si le fichier est inaccessible.
        """
        raw_text = self._backend.read_text(f"{application}/{APP_METADATA_FILENAME}")
        return parse_app_metadata(application, raw_text)

    def list_versions(self, application: str) -> List[str]:
        """Liste les versions déclarées d'une application (dossiers avec manifest).

        Args:
            application: Nom de l'application.

        Returns:
            Les noms des dossiers de version, triés.

        Raises:
            OSError: Si le dossier de l'application est inaccessible.
        """
        versions: List[str] = []
        for entry in self._backend.listdir(application):
            version_dir = f"{application}/{entry}"
            if self._backend.is_dir(version_dir) and self._backend.exists(
                f"{version_dir}/{MANIFEST_FILENAME}"
            ):
                versions.append(entry)
        return sorted(versions)

    def load_manifest(self, application: str, version: str) -> VersionManifest:
        """Charge et valide le ``manifest.yaml`` d'une version donnée.

        Les manifests sont chargés à la demande (et mis en cache par le
        :class:`~engine.update_engine.UpdateEngine`), pas au chargement du
        catalogue : seule la version concernée paie le coût de lecture.

        Args:
            application: Nom de l'application.
            version: Nom du dossier de version.

        Returns:
            Le manifest de la version.

        Raises:
            ManifestError: Si le fichier ne respecte pas le schéma.
            OSError: Si le fichier est inaccessible.
        """
        raw_text = self._backend.read_text(f"{application}/{version}/{MANIFEST_FILENAME}")
        return parse_version_manifest(application, version, raw_text)

    def fetch_file(self, application: str, version: str, source: str, destination: Path) -> None:
        """Recopie localement un fichier d'une version du catalogue.

        Args:
            application: Nom de l'application.
            version: Nom du dossier de version.
            source: Chemin du fichier, relatif au dossier de la version.
            destination: Fichier local de destination.
        """
        self._backend.download(f"{application}/{version}/{source}", destination)
