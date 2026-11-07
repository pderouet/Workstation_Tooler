"""Logique de mise à jour spécifique à l'éditeur Vim."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from modules.base_module import BaseModule, ProgressCallback


class VimModule(BaseModule):
    """Gère l'installation, la désinstallation et la configuration de Vim."""

    name = "vim"

    def get_installed_version(self) -> Optional[str]:
        """Interroge le binaire ``vim`` local pour connaître sa version.

        Returns:
            La première ligne retournée par ``vim --version``, ou ``None``
            si le binaire est introuvable ou l'appel a échoué.
        """
        vim_path = shutil.which("vim")
        if vim_path is None:
            return None
        try:
            result = subprocess.run(
                [vim_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.SubprocessError, OSError:
            return None
        return result.stdout.splitlines()[0] if result.stdout else None

    def get_latest_version(self) -> Optional[str]:
        """Retourne la version cible configurée pour Vim.

        Note:
            Si ``target_version`` vaut ``"latest"``, l'interrogation du
            dépôt de paquets de l'OS (ou d'un miroir interne) doit être
            implémentée ici pour résoudre la véritable dernière version.

        Returns:
            La version cible configurée, ou ``None`` si elle doit encore
            être résolue dynamiquement.
        """
        target_version = self.module_config().get("target_version", "latest")
        return None if target_version == "latest" else target_version

    def install(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Installe Vim à la version cible.

        Note:
            L'appel réel au gestionnaire de paquets (ex. ``apt``, ``choco``
            ou dépôt interne) doit être branché ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si l'installation s'est terminée avec succès.
        """
        return self._run_simulated_steps(
            ("Téléchargement", "Vérification", "Installation"), progress_callback
        )

    def uninstall(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Désinstalle Vim.

        Note:
            L'appel réel au gestionnaire de paquets doit être branché ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la désinstallation s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Sauvegarde config", "Suppression"), progress_callback)

    def reconfigure(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Réapplique la configuration Vim (``.vimrc``, plugins).

        Note:
            La régénération effective des fichiers de configuration doit
            être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la reconfiguration s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Régénération config",), progress_callback)
