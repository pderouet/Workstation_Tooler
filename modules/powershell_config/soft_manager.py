"""Logique de déploiement de la configuration standard PowerShell du poste.

Contrairement aux autres modules, celui-ci ne gère pas un binaire tiers
mais le profil et les modules PowerShell déployés sur le poste de travail
(``$PROFILE``, modules communs, alias standardisés de l'entreprise).
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from modules.base_module import BaseModule, ProgressCallback


class PowerShellConfigModule(BaseModule):
    """Gère le déploiement, la suppression et la régénération du profil PowerShell."""

    name = "powershell_config"
    display_name = "Configuration PowerShell"

    def get_installed_version(self) -> Optional[str]:
        """Retourne la version du moteur PowerShell installé sur le poste.

        Returns:
            La version retournée par ``pwsh -Version`` (PowerShell 7+) ou
            ``powershell -Command $PSVersionTable.PSVersion`` (Windows
            PowerShell), ou ``None`` si aucun moteur n'est détecté.
        """
        pwsh_path = shutil.which("pwsh") or shutil.which("powershell")
        if pwsh_path is None:
            return None
        try:
            result = subprocess.run(
                [
                    pwsh_path,
                    "-NoLogo",
                    "-NoProfile",
                    "-Command",
                    "$PSVersionTable.PSVersion.ToString()",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.SubprocessError, OSError:
            return None
        return result.stdout.strip() or None

    def get_latest_version(self) -> Optional[str]:
        """Retourne la version cible de la configuration PowerShell standard.

        Note:
            Si ``target_version`` vaut ``"latest"``, la résolution de la
            dernière version du paquet de configuration interne (dépôt Git
            dédié, partage réseau, etc.) doit être implémentée ici.

        Returns:
            La version cible configurée, ou ``None`` si elle doit encore
            être résolue dynamiquement.
        """
        target_version = self.module_config().get("target_version", "latest")
        return None if target_version == "latest" else target_version

    def install(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Déploie le profil et les modules PowerShell standards.

        Note:
            La copie effective du profil (``$PROFILE``), des modules
            communs et des alias standardisés doit être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si le déploiement s'est terminé avec succès.
        """
        return self._run_simulated_steps(
            ("Téléchargement", "Vérification", "Déploiement"), progress_callback
        )

    def uninstall(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Retire la configuration PowerShell standard du poste.

        Note:
            La suppression effective du profil et des modules déployés
            doit être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la suppression s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Sauvegarde profil", "Suppression"), progress_callback)

    def reconfigure(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Régénère le profil PowerShell à partir du modèle de référence.

        Note:
            La régénération effective du profil et des modules doit être
            implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la régénération s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Régénération profil",), progress_callback)
