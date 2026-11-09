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

#: Modes d'authentification SMB supportés (voir :class:`SmbStorageBackend`).
AUTH_MODES = ("session", "credentials", "guest")


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

    Trois modes d'authentification (``auth``, voir :const:`AUTH_MODES`) :
        - ``session`` : authentification implicite avec la session de
          l'utilisateur du poste (SSPI ``Negotiate`` : Kerberos puis NTLM) —
          poste joint au domaine, l'utilisateur doit avoir les droits de
          lecture sur le partage ;
        - ``credentials`` : compte explicite (``username`` et mot de passe lu
          exclusivement depuis la variable d'environnement
          ``WORKSTATION_TOOLER_SMB_PASSWORD``) ;
        - ``guest`` : compte mappé invité côté serveur, sans signature ni
          secure negotiate (partage public de développement/test).

    La session SMB est **paresseuse** : elle n'est établie qu'au premier accès.
    Un partage injoignable ne fait donc pas échouer la construction du
    backend — l'application démarre, et l'erreur remonte aux tâches de fond
    qui consultent le catalogue.
    """

    def __init__(
        self,
        base_uri: str,
        auth: str = "session",
        username: str = "",
        domain: str = "",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Mémorise les paramètres de connexion (aucun accès réseau ici).

        Args:
            base_uri: Racine du catalogue au format ``smb://hôte/partage``.
            auth: Mode d'authentification parmi :const:`AUTH_MODES`.
            username: Nom d'utilisateur SMB (modes ``credentials`` et
                ``guest`` uniquement).
            domain: Domaine NTLM optionnel (combiné au nom d'utilisateur).
            timeout_seconds: Délai maximal de connexion (secondes).

        Raises:
            ValueError: Si l'URI n'est pas une URI SMB valide, si le mode
                d'authentification est inconnu, ou si la combinaison
                mode/identifiants est incohérente.
        """
        self._server, self._share_root = parse_smb_uri(base_uri)

        if auth not in AUTH_MODES:
            raise ValueError(
                f"Mode d'authentification SMB inconnu : {auth!r} "
                f"(modes supportés : {', '.join(AUTH_MODES)})."
            )
        self._auth = auth

        if auth == "session":
            if username or domain:
                raise ValueError(
                    "Les clés 'repository.username' et 'repository.domain' sont "
                    "incompatibles avec le mode d'authentification 'session' "
                    "(la session de l'utilisateur du poste est utilisée)."
                )
            # Sans identifiants, smbprotocol négocie via SSPI/GSSAPI les
            # credentials de l'utilisateur courant (Kerberos, puis NTLM).
            self._username = None
            self._password = None
        else:
            if not username:
                raise ValueError(
                    f"Le mode d'authentification '{auth}' exige 'repository.username'."
                )
            self._username = f"{domain}\\{username}" if domain else username
            if auth == "credentials":
                password = os.environ.get(SMB_PASSWORD_ENV_VAR)
                if not password:
                    raise ValueError(
                        "Le mode d'authentification 'credentials' exige le mot "
                        f"de passe SMB dans la variable d'environnement {SMB_PASSWORD_ENV_VAR}."
                    )
                self._password = password
            else:
                # pyspnego ne propose NTLM que si des identifiants existent :
                # pour un compte mappé invité (sans mot de passe), on passe
                # une chaîne vide plutôt que None.
                self._password = ""

        self._timeout_seconds = timeout_seconds
        self._session_registered = False

    def _ensure_session(self) -> None:
        """Établit la session SMB au premier accès, puis ne fait plus rien.

        Raises:
            OSError: Si le serveur est injoignable ou l'authentification
                refusée — remontée aux appelateurs (tâches de fond).
        """
        if self._session_registered:
            return
        if self._auth == "guest":
            # Une session invité ne peut ni signer ni chiffrer les messages
            # SMB : sans mot de passe (partage public), la signature
            # obligatoire doit être levée, faute de quoi le serveur rejette
            # la session avec « guest which does not support encryption or
            # signing ». La vérification d'intégrité de la négociation
            # (secure negotiate) repose elle aussi sur la clé de signature :
            # sans clé (invité), elle doit être désactivée explicitement.
            smbclient.ClientConfig().require_secure_negotiate = False
            smbclient.register_session(
                self._server,
                username=self._username,
                password=self._password,
                require_signing=False,
                connection_timeout=self._timeout_seconds,
            )
        elif self._auth == "credentials":
            smbclient.register_session(
                self._server,
                username=self._username,
                password=self._password,
                require_signing=True,
                connection_timeout=self._timeout_seconds,
            )
        else:
            # Mode 'session' : sans identifiants, smbprotocol s'authentifie
            # avec la session de l'utilisateur courant (SSPI Negotiate :
            # Kerberos puis NTLM). La signature SMB reste exigée (défaut).
            smbclient.register_session(
                self._server,
                require_signing=True,
                connection_timeout=self._timeout_seconds,
            )
        self._session_registered = True

    def _uri(self, path: str) -> str:
        """Construit le chemin UNC absolu d'un chemin relatif du catalogue."""
        return smb_unc_path(self._server, self._share_root, path)

    def listdir(self, path: str) -> List[str]:
        """Liste les noms d'entrées du répertoire (voir protocole)."""
        self._ensure_session()
        return sorted(smbclient.listdir(self._uri(path)))

    def is_dir(self, path: str) -> bool:
        """Indique si le chemin désigne un répertoire (voir protocole)."""
        self._ensure_session()
        return smbclient.path.isdir(self._uri(path))

    def exists(self, path: str) -> bool:
        """Indique si le chemin existe (voir protocole)."""
        self._ensure_session()
        return smbclient.path.exists(self._uri(path))

    def read_text(self, path: str) -> str:
        """Lit un fichier texte du partage (voir protocole)."""
        self._ensure_session()
        with smbclient.open_file(self._uri(path), mode="rb") as source:
            return source.read().decode("utf-8")

    def download(self, path: str, destination: Path) -> None:
        """Recopie le fichier du partage vers la destination (voir protocole)."""
        self._ensure_session()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with smbclient.open_file(self._uri(path), mode="rb") as source:
            with destination.open("wb") as target:
                shutil.copyfileobj(source, target)


def build_storage_backend(
    uri: str,
    auth: str = "session",
    username: str = "",
    domain: str = "",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> StorageBackend:
    """Construit le backend adapté au schéma de l'URI du catalogue.

    Args:
        uri: Racine du catalogue (``smb://hôte/partage`` ou ``file:///chemin``).
        auth: Mode d'authentification SMB parmi :const:`AUTH_MODES`
            (backend SMB uniquement).
        username: Nom d'utilisateur SMB (modes ``credentials`` et ``guest``
            uniquement, backend SMB uniquement).
        domain: Domaine NTLM optionnel (modes ``credentials`` et ``guest``
            uniquement, backend SMB uniquement).
        timeout_seconds: Délai de connexion SMB (secondes).

    Returns:
        Une instance de backend prête à l'emploi.

    Raises:
        ValueError: Si le schéma de l'URI n'est pas supporté, ou si le mode
            d'authentification SMB est inconnu/incohérent.
    """
    scheme = urlparse(uri).scheme.lower()
    if scheme == "smb":
        return SmbStorageBackend(
            uri,
            auth=auth,
            username=username,
            domain=domain,
            timeout_seconds=timeout_seconds,
        )
    if scheme in ("", "file"):
        return LocalStorageBackend(uri)
    raise ValueError(f"Schéma de catalogue non supporté : {scheme!r} (URI : {uri!r}).")
