"""Backends d'accès au chemin réseau hébergeant le catalogue des mises à jour.

Deux implémentations interchangeables derrière le protocole :class:`StorageBackend` :
    - :class:`SmbStorageBackend` : partage SMB via le module ``smbclient``
      (paquet ``smbprotocol``) — chemin réseau de production ;
    - :class:`LocalStorageBackend` : système de fichiers local (URI ``file://``
      ou chemin direct) — développement, tests, catalogue déjà monté.

Toutes les méthodes reçoivent des chemins relatifs à la racine du catalogue,
au format POSIX (ex. ``"vim/9.1.0700/manifest.yaml"``).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath
from typing import List, Protocol, runtime_checkable
from urllib.parse import unquote, urlparse

import smbclient

#: Variable d'environnement fournissant le mot de passe SMB (jamais en configuration).
SMB_PASSWORD_ENV_VAR = "WORKSTATION_TOOLER_SMB_PASSWORD"

#: Délai de connexion SMB par défaut (secondes).
DEFAULT_TIMEOUT_SECONDS = 30


@runtime_checkable
class StorageBackend(Protocol):
    """Interface d'accès en lecture au catalogue des mises à jour."""

    def listdir(self, path: str) -> List[str]:
        """Liste les noms d'entrées (fichiers et dossiers) d'un répertoire.

        Args:
            path: Chemin relatif du répertoire (``""`` désigne la racine).

        Returns:
            Les noms des entrées, sans le préfixe de chemin.
        """
        ...

    def is_dir(self, path: str) -> bool:
        """Indique si le chemin désigne un répertoire."""
        ...

    def exists(self, path: str) -> bool:
        """Indique si le chemin existe (fichier ou répertoire)."""
        ...

    def read_text(self, path: str) -> str:
        """Lit un fichier texte du catalogue (encodage UTF-8).

        Args:
            path: Chemin relatif du fichier.

        Returns:
            Le contenu du fichier.

        Raises:
            OSError: Si le fichier est inaccessible.
        """
        ...

    def download(self, path: str, destination: Path) -> None:
        """Copie un fichier du catalogue vers un chemin local.

        Args:
            path: Chemin relatif du fichier source.
            destination: Fichier local de destination (répertoires parents créés).
        """
        ...


class LocalStorageBackend:
    """Backend sur système de fichiers local (URI ``file://`` ou chemin direct)."""

    def __init__(self, base_uri: str) -> None:
        """Initialise le backend sur la racine donnée.

        Args:
            base_uri: Racine du catalogue, soit ``file:///chemin/absolu``, soit
                un chemin directement utilisable (absolu ou relatif).

        Raises:
            ValueError: Si l'URI utilise un schéma autre que ``file`` (ou vide).
        """
        parsed = urlparse(base_uri)
        if parsed.scheme.lower() in ("", "file"):
            raw_path = unquote(parsed.path) if parsed.scheme else base_uri
            self._base = Path(raw_path).expanduser().absolute()
        else:
            raise ValueError(
                f"LocalStorageBackend attend une URI 'file://' ou un chemin, reçu : {base_uri!r}."
            )

    def _resolve(self, path: str) -> Path:
        """Résout un chemin relatif POSIX contre la racine du catalogue."""
        return self._base.joinpath(*PurePosixPath(path).parts)

    def listdir(self, path: str) -> List[str]:
        """Liste les noms d'entrées du répertoire (voir protocole)."""
        return sorted(entry.name for entry in os.scandir(self._resolve(path)))

    def is_dir(self, path: str) -> bool:
        """Indique si le chemin désigne un répertoire (voir protocole)."""
        return self._resolve(path).is_dir()

    def exists(self, path: str) -> bool:
        """Indique si le chemin existe (voir protocole)."""
        return self._resolve(path).exists()

    def read_text(self, path: str) -> str:
        """Lit un fichier texte local (voir protocole)."""
        return self._resolve(path).read_text(encoding="utf-8")

    def download(self, path: str, destination: Path) -> None:
        """Copie le fichier local vers la destination (voir protocole)."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._resolve(path), destination)


def parse_smb_uri(uri: str) -> tuple[str, str]:
    """Décompose une URI ``smb://hôte/partage[/sous-chemin]``.

    Args:
        uri: URI SMB fournie par la configuration.

    Returns:
        Le couple ``(hôte, chemin_dans_le_partage)`` — le premier segment du
        chemin étant le nom du partage.

    Raises:
        ValueError: Si l'URI n'est pas une URI SMB valide (schéma, hôte ou
            partage manquant).
    """
    parsed = urlparse(uri)
    if parsed.scheme.lower() != "smb" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"URI SMB invalide (attendu 'smb://hôte/partage') : {uri!r}.")
    return parsed.netloc, parsed.path.strip("/")


def smb_unc_path(server: str, share_root: str, path: str) -> str:
    """Construit le chemin UNC attendu par smbprotocol.

    smbprotocol n'accepte pas les URI ``smb://`` : ses fonctions attendent un
    chemin UNC ``\\\\hôte\\partage\\chemin``.

    Args:
        server: Hôte SMB (ex. ``localhost``).
        share_root: Nom du partage, suivi le cas échéant du sous-chemin.
        path: Chemin relatif au sein du catalogue (``""`` pour la racine).

    Returns:
        Le chemin UNC complet.
    """
    relative = path.strip("/")
    full_path = f"{share_root.strip('/')}/{relative}" if relative else share_root.strip("/")
    return f"\\\\{server}\\{full_path.replace('/', '\\')}"


class SmbStorageBackend:
    """Backend sur partage SMB via le module ``smbclient`` (paquet ``smbprotocol``).

    La configuration expose une URI ``smb://hôte/partage`` (format naturel pour
    l'utilisateur) ; smbprotocol, en revanche, attend des chemins UNC
    (``\\\\hôte\\partage\\chemin``), la conversion est faite ici.

    La session SMB est enregistrée à la construction : authentification NTLM
    avec le nom d'utilisateur fourni et le mot de passe lu exclusivement
    depuis la variable d'environnement ``WORKSTATION_TOOLER_SMB_PASSWORD``.
    """

    def __init__(
        self,
        base_uri: str,
        username: str = "",
        domain: str = "",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialise la session et mémorise la racine du catalogue.

        Args:
            base_uri: Racine du catalogue au format ``smb://hôte/partage``.
            username: Nom d'utilisateur SMB. smbprotocol ne gère pas la
                session anonyme pure : pour un partage public, renseigner un
                compte mappé invité côté serveur (ex. ``map to guest``).
            domain: Domaine NTLM optionnel (combiné au nom d'utilisateur).
            timeout_seconds: Délai maximal de connexion (secondes).

        Raises:
            ValueError: Si l'URI n'est pas une URI SMB valide.
        """
        self._server, self._share_root = parse_smb_uri(base_uri)

        full_username = f"{domain}\\{username}" if domain and username else username
        # pyspnego ne propose NTLM que si des identifiants existent : lorsqu'un
        # utilisateur est renseigné sans mot de passe (partage public mappé
        # invité côté serveur), on passe une chaîne vide plutôt que None.
        password = os.environ.get(SMB_PASSWORD_ENV_VAR, "") if full_username else None
        # Une session invité ne peut ni signer ni chiffrer les messages SMB :
        # sans mot de passe (partage public), la signature obligatoire doit
        # être levée, faute de quoi le serveur rejette la session avec
        # « guest which does not support encryption or signing ».
        guest_session = full_username and not password
        if guest_session:
            # La vérification d'intégrité de la négociation (secure negotiate)
            # repose elle aussi sur la clé de signature : sans clé (invité),
            # elle doit être désactivée explicitement.
            smbclient.ClientConfig().require_secure_negotiate = False
        smbclient.register_session(
            self._server,
            username=full_username or None,
            password=password,
            require_signing=not guest_session,
            connection_timeout=timeout_seconds,
        )

    def _uri(self, path: str) -> str:
        """Construit le chemin UNC absolu d'un chemin relatif du catalogue."""
        return smb_unc_path(self._server, self._share_root, path)

    def listdir(self, path: str) -> List[str]:
        """Liste les noms d'entrées du répertoire (voir protocole)."""
        return sorted(smbclient.listdir(self._uri(path)))

    def is_dir(self, path: str) -> bool:
        """Indique si le chemin désigne un répertoire (voir protocole)."""
        return smbclient.path.isdir(self._uri(path))

    def exists(self, path: str) -> bool:
        """Indique si le chemin existe (voir protocole)."""
        return smbclient.path.exists(self._uri(path))

    def read_text(self, path: str) -> str:
        """Lit un fichier texte du partage (voir protocole)."""
        with smbclient.open_file(self._uri(path), mode="rb") as source:
            return source.read().decode("utf-8")

    def download(self, path: str, destination: Path) -> None:
        """Recopie le fichier du partage vers la destination (voir protocole)."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with smbclient.open_file(self._uri(path), mode="rb") as source:
            with destination.open("wb") as target:
                shutil.copyfileobj(source, target)


def build_storage_backend(
    uri: str,
    username: str = "",
    domain: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> StorageBackend:
    """Construit le backend adapté au schéma de l'URI du catalogue.

    Args:
        uri: Racine du catalogue (``smb://hôte/partage`` ou ``file:///chemin``).
        username: Nom d'utilisateur SMB (backend SMB uniquement).
        domain: Domaine NTLM optionnel (backend SMB uniquement).
        timeout_seconds: Délai de connexion SMB (secondes).

    Returns:
        Une instance de backend prête à l'emploi.

    Raises:
        ValueError: Si le schéma de l'URI n'est pas supporté.
    """
    scheme = urlparse(uri).scheme.lower()
    if scheme == "smb":
        return SmbStorageBackend(
            uri, username=username, domain=domain, timeout_seconds=timeout_seconds
        )
    if scheme in ("", "file"):
        return LocalStorageBackend(uri)
    raise ValueError(f"Schéma de catalogue non supporté : {scheme!r} (URI : {uri!r}).")
