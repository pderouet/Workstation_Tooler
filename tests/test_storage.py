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


class DoublureClientConfig:
    """Doublure du ClientConfig global de smbclient (secure negotiate)."""

    require_secure_negotiate = True


def doublures_session_smb(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], DoublureClientConfig]:
    """Remplace ``register_session``/``ClientConfig`` et retourne les captures."""
    from engine import storage

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        storage.smbclient,
        "register_session",
        lambda server, **kwargs: captured.update({"server": server, **kwargs}),
    )
    fake_config = DoublureClientConfig()
    monkeypatch.setattr(storage.smbclient, "ClientConfig", lambda: fake_config)
    return captured, fake_config


def test_session_utilisateur_courante_au_premier_acces(monkeypatch) -> None:
    """En mode 'session', aucun identifiant n'est passé : SSO session du poste.

    La construction n'établit AUCUNE connexion (un partage injoignable ne fait
    pas planter l'application) ; le premier accès enregistre la session sans
    username ni mot de passe (SSPI Negotiate côté Windows : Kerberos puis
    NTLM avec la session de l'utilisateur), signature exigée et secure
    negotiate laissé actif.
    """
    captured, fake_config = doublures_session_smb(monkeypatch)
    from engine import storage

    backend = storage.SmbStorageBackend("smb://serveur.dom.tld/Workstation_Tooler")
    assert captured == {}  # aucune connexion à la construction.

    backend._ensure_session()
    assert captured["server"] == "serveur.dom.tld"
    assert "username" not in captured
    assert "password" not in captured
    assert captured["require_signing"] is True
    assert fake_config.require_secure_negotiate is True  # non touché.

    # Un second appel ne réenregistre pas la session.
    backend._ensure_session()
    register_calls = list(captured.items())
    backend._ensure_session()
    assert list(captured.items()) == register_calls


def test_session_invite_sans_signature_en_mode_guest(monkeypatch) -> None:
    """En mode 'guest', la session différée s'ouvre sans signature ni secure negotiate.

    La session invité — qui ne peut ni signer ni chiffrer — s'établit au
    premier accès avec le compte mappé côté serveur et un mot de passe vide
    (pyspnego exige des identifiants existants pour proposer NTLM).
    """
    captured, fake_config = doublures_session_smb(monkeypatch)
    from engine import storage

    backend = storage.SmbStorageBackend(
        "smb://localhost/Workstation_Tooler", auth="guest", username="guest"
    )
    assert captured == {}  # aucune connexion à la construction.

    backend._ensure_session()
    assert captured["server"] == "localhost"
    assert captured["username"] == "guest"
    assert captured["password"] == ""
    assert captured["require_signing"] is False
    assert fake_config.require_secure_negotiate is False


def test_session_authentifiee_avec_signature_au_premier_acces(monkeypatch) -> None:
    """En mode 'credentials', compte explicite et signature exigée."""
    captured, _ = doublures_session_smb(monkeypatch)
    from engine import storage

    monkeypatch.setenv("WORKSTATION_TOOLER_SMB_PASSWORD", "secret")
    backend = storage.SmbStorageBackend(
        "smb://localhost/Workstation_Tooler", auth="credentials", username="pierre"
    )
    assert captured == {}
    backend._ensure_session()

    assert captured["username"] == "pierre"
    assert captured["password"] == "secret"
    assert captured["require_signing"] is True


def test_auth_mode_inconnu_refuse() -> None:
    """Un mode d'authentification hors AUTH_MODES est refusé."""
    from engine import storage

    with pytest.raises(ValueError, match="Mode d'authentification SMB inconnu"):
        storage.SmbStorageBackend("smb://localhost/Workstation_Tooler", auth="anonymous")


def test_auth_session_refuse_identifiants() -> None:
    """Le mode 'session' refuse username/domain (l'ancienne ambiguïté guest)."""
    from engine import storage

    with pytest.raises(ValueError, match="incompatibles"):
        storage.SmbStorageBackend("smb://localhost/Workstation_Tooler", username="guest")
    with pytest.raises(ValueError, match="incompatibles"):
        storage.SmbStorageBackend("smb://localhost/Workstation_Tooler", domain="DOM")


def test_auth_credentials_exige_nom_utilisateur_et_mot_de_passe(monkeypatch) -> None:
    """Le mode 'credentials' exige un username et la variable d'environnement."""
    from engine import storage

    monkeypatch.delenv("WORKSTATION_TOOLER_SMB_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="exige 'repository.username'"):
        storage.SmbStorageBackend("smb://localhost/Workstation_Tooler", auth="credentials")
    with pytest.raises(ValueError, match="WORKSTATION_TOOLER_SMB_PASSWORD"):
        storage.SmbStorageBackend(
            "smb://localhost/Workstation_Tooler", auth="credentials", username="pierre"
        )


def test_auth_guest_exige_nom_utilisateur() -> None:
    """Le mode 'guest' exige le nom du compte mappé invité côté serveur."""
    from engine import storage

    with pytest.raises(ValueError, match="exige 'repository.username'"):
        storage.SmbStorageBackend("smb://localhost/Workstation_Tooler", auth="guest")
