"""Tests headless des backends de stockage et de la fabrique associée."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.storage import (
    DEFAULT_TIMEOUT_SECONDS,
    LocalStorageBackend,
    build_storage_backend,
    parse_smb_uri,
    smb_unc_path,
)


def test_local_backend_lecture_partage(share_root: Path) -> None:
    """Le backend local liste et lit le faux catalogue via une URI file://."""
    backend = LocalStorageBackend(share_root.as_uri())
    entries = backend.listdir("")
    assert "vim" in entries
    assert "README.txt" in entries
    assert backend.is_dir("vim")
    assert not backend.is_dir("README.txt")
    assert backend.exists("vim/app.yaml")
    assert not backend.exists("vim/manquant.yaml")


def test_local_backend_read_text_utf8(share_root: Path) -> None:
    """La lecture texte décode l'UTF-8 du catalogue."""
    backend = LocalStorageBackend(share_root.as_uri())
    content = backend.read_text("vim/app.yaml")
    assert "application: vim" in content


def test_local_backend_download(share_root: Path, tmp_path: Path) -> None:
    """Le téléchargement copie le fichier et crée les répertoires parents."""
    backend = LocalStorageBackend(share_root.as_uri())
    destination = tmp_path / "sous-dossier" / "fragment.txt"
    backend.download("vim/9.1.0700/vimrc.fragment", destination)
    assert destination.read_text(encoding="utf-8").startswith('" demonstration')


def test_local_backend_uri_invalide() -> None:
    """Un schéma ni vide ni file:// est refusé par le backend local."""
    with pytest.raises(ValueError, match="file"):
        LocalStorageBackend("ftp://exemple.fr/partage")


def test_fabrique_selon_le_schema(share_root: Path) -> None:
    """La fabrique construit un backend local pour file:// et un chemin nu."""
    assert isinstance(build_storage_backend(share_root.as_uri()), LocalStorageBackend)
    assert isinstance(build_storage_backend(str(share_root)), LocalStorageBackend)


def test_fabrique_schema_inconnu() -> None:
    """Un schéma non supporté est refusé explicitement."""
    with pytest.raises(ValueError, match="non supporté"):
        build_storage_backend("http://exemple.fr/catalogue")


def test_timeout_par_defaut_expose() -> None:
    """Le délai de connexion SMB par défaut reste défini et positif."""
    assert DEFAULT_TIMEOUT_SECONDS > 0


def test_parse_smb_uri() -> None:
    """L'URI smb:// est décomposée en hôte et partage (+ sous-chemin)."""
    assert parse_smb_uri("smb://localhost/Workstation_Tooler") == (
        "localhost",
        "Workstation_Tooler",
    )
    assert parse_smb_uri("smb://srv.dom.tld/partage/cat") == ("srv.dom.tld", "partage/cat")


def test_parse_smb_uri_invalide() -> None:
    """Une URI sans hôte ou sans partage est refusée."""
    with pytest.raises(ValueError, match="URI SMB invalide"):
        parse_smb_uri("smb://localhost")
    with pytest.raises(ValueError, match="URI SMB invalide"):
        parse_smb_uri("file:///chemin/local")


def test_smb_unc_path() -> None:
    """Les chemins relatifs du catalogue deviennent des UNC pour smbprotocol."""
    assert smb_unc_path("localhost", "Workstation_Tooler", "") == (
        "\\\\localhost\\Workstation_Tooler"
    )
    assert smb_unc_path("localhost", "Workstation_Tooler", "vim/app.yaml") == (
        "\\\\localhost\\Workstation_Tooler\\vim\\app.yaml"
    )
    assert smb_unc_path("srv", "partage/cat", "k9s/v0.50.0/k9s.tar.gz") == (
        "\\\\srv\\partage\\cat\\k9s\\v0.50.0\\k9s.tar.gz"
    )


def test_session_invite_sans_signature(monkeypatch) -> None:
    """Sans mot de passe (partage public), la session SMB est ouverte sans signature.

    Une session invité ne peut ni signer ni chiffrer : exiger la signature
    ferait rejeter la connexion (« guest does not support encryption or
    signing »), et la vérification secure negotiate doit aussi être levée.
    """
    from engine import storage

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        storage.smbclient,
        "register_session",
        lambda server, **kwargs: captured.update({"server": server, **kwargs}),
    )

    class FakeClientConfig:
        require_secure_negotiate = True

    fake_config = FakeClientConfig()
    monkeypatch.setattr(storage.smbclient, "ClientConfig", lambda: fake_config)
    monkeypatch.delenv("WORKSTATION_TOOLER_SMB_PASSWORD", raising=False)

    storage.SmbStorageBackend("smb://localhost/Workstation_Tooler", username="guest")

    assert captured["server"] == "localhost"
    assert captured["username"] == "guest"
    assert captured["require_signing"] is False
    assert fake_config.require_secure_negotiate is False


def test_session_authentifie_avec_signature(monkeypatch) -> None:
    """Avec un mot de passe (session authentifiée), la signature reste exigée."""
    from engine import storage

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        storage.smbclient,
        "register_session",
        lambda server, **kwargs: captured.update({"server": server, **kwargs}),
    )
    monkeypatch.setenv("WORKSTATION_TOOLER_SMB_PASSWORD", "secret")

    storage.SmbStorageBackend("smb://localhost/Workstation_Tooler", username="pierre")

    assert captured["username"] == "pierre"
    assert captured["password"] == "secret"
    assert captured["require_signing"] is True
