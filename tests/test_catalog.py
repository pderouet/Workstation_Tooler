"""Tests headless du repository et du chargement du catalogue (backend local)."""

from __future__ import annotations

from pathlib import Path

from engine.catalog import CatalogLoader
from engine.models import ActionKind, Catalog
from engine.repository import RemoteRepository


def test_repository_liste_applications(repository: RemoteRepository) -> None:
    """Seuls les dossiers racine contenant un app.yaml sont des applications."""
    names = repository.list_application_names()
    assert "vim" in names
    assert "k9s" in names
    assert "no_versions_tool" in names
    assert "broken_tool" in names  # présent mais invalide : détecté au chargement.
    assert "README.txt" not in names


def test_repository_versions_sans_manifest_ignorees(repository: RemoteRepository) -> None:
    """Un dossier de version sans manifest.yaml n'est pas une version."""
    versions = repository.list_versions("vim")
    assert versions == ["9.1.0500", "9.1.0700"]


def test_repository_charge_metadata_et_manifest(repository: RemoteRepository) -> None:
    """Les YAML sont chargés, validés et convertis en modèles typés."""
    metadata = repository.load_app_metadata("vim")
    assert metadata.display_name == "Vim"

    manifest = repository.load_manifest("vim", "9.1.0700")
    assert manifest.version == "9.1.0700"
    assert manifest.files[0].action is ActionKind.DECOMPRESS


def test_repository_fetch_file(repository: RemoteRepository, tmp_path: Path) -> None:
    """Un fichier d'une version est recopié localement."""
    destination = tmp_path / "vimrc.fragment"
    repository.fetch_file("vim", "9.1.0700", "vimrc.fragment", destination)
    assert destination.exists()


def test_catalog_charge_les_applications_valides(repository: RemoteRepository) -> None:
    """Le catalogue référence les applications valides avec leurs versions."""
    catalog: Catalog = CatalogLoader(repository).load()
    assert set(catalog.applications) == {"vim", "k9s", "disabled_tool"}
    assert catalog.applications["vim"].versions == ["9.1.0500", "9.1.0700"]
    assert catalog.applications["vim"].latest_version == "9.1.0700"
    assert catalog.applications["k9s"].latest_version == "v0.50.0"


def test_catalog_ignore_et_trace_les_applications_invalides(
    repository: RemoteRepository,
) -> None:
    """Une app.yaml invalide ou une absence de versions mène à une exclusion tracée."""
    catalog = CatalogLoader(repository).load()
    assert "broken_tool" in catalog.skipped
    assert "déclaration illisible" in catalog.skipped["broken_tool"]
    assert "no_versions_tool" in catalog.skipped
    assert "aucune version" in catalog.skipped["no_versions_tool"]


def test_catalog_enabled_applications_exclut_desactivees(
    repository: RemoteRepository,
) -> None:
    """Les applications marquées enabled: false restent connues mais inactives."""
    catalog = CatalogLoader(repository).load()
    enabled_names = {app.metadata.name for app in catalog.enabled_applications()}
    assert enabled_names == {"vim", "k9s"}
    assert "disabled_tool" in catalog.applications
