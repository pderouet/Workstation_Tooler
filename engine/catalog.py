"""Chargement du catalogue des applications depuis le chemin réseau.

Le catalogue est la photographie des applications déclarées sur le partage :
métadonnées (``app.yaml``) et liste des versions disponibles. Les manifests
des versions ne sont pas chargés ici : ils le sont à la demande, au moment
d'une mise à jour (voir :class:`~engine.update_engine.UpdateEngine`).

Le chargement est résilient : une application mal déclarée est journalisée
dans ``Catalog.skipped`` et ignorée, sans empêcher le traitement des autres.
"""

from __future__ import annotations

from engine.models import Application, Catalog, ManifestError
from engine.repository import RemoteRepository


class CatalogLoader:
    """Parcourt le repository et construit le :class:`~engine.models.Catalog`."""

    def __init__(self, repository: RemoteRepository) -> None:
        """Initialise le chargeur sur le repository fourni.

        Args:
            repository: Accès structuré au catalogue distant.
        """
        self._repository = repository

    def load(self) -> Catalog:
        """Charge l'intégralité du catalogue depuis le chemin réseau.

        Une application est ignorée (et consignée dans ``skipped``) si son
        ``app.yaml`` est invalide ou illisible, ou si aucune version valide
        n'est déclarée.

        Returns:
            Le catalogue chargé (applications valides + exclusions).

        Raises:
            OSError: Si la racine du catalogue est elle-même inaccessible —
                dans ce cas, aucune application n'a pu être examinée et
                l'appelant doit le signaler (ErrorHandler).
        """
        catalog = Catalog()
        for name in self._repository.list_application_names():
            try:
                metadata = self._repository.load_app_metadata(name)
                versions = self._repository.list_versions(name)
            except (ManifestError, OSError) as exc:
                catalog.skipped[name] = f"déclaration illisible : {exc}"
                continue

            if not versions:
                catalog.skipped[name] = "aucune version valide (dossier avec manifest.yaml)"
                continue

            catalog.applications[name] = Application(metadata=metadata, versions=versions)

        return catalog
