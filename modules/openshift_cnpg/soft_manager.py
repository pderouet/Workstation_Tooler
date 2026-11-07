"""Logique de mise à jour spécifique au plugin OpenShift CloudNativePG (CNPG)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from modules.base_module import BaseModule, ProgressCallback


class OpenShiftCnpgModule(BaseModule):
    """Gère l'installation, la désinstallation et la configuration du plugin ``kubectl-cnpg``."""

    name = "openshift_cnpg"
    display_name = "OpenShift CNPG"

    def get_installed_version(self) -> Optional[str]:
        """Interroge le plugin ``kubectl-cnpg`` local pour connaître sa version.

        Returns:
            La version retournée par ``kubectl-cnpg version``, ou ``None``
            si le plugin est introuvable ou l'appel a échoué.
        """
        cnpg_path = shutil.which("kubectl-cnpg")
        if cnpg_path is None:
            return None
        try:
            result = subprocess.run(
                [cnpg_path, "version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.SubprocessError, OSError:
            return None
        return result.stdout.strip() or None

    def get_latest_version(self) -> Optional[str]:
        """Retourne la version cible configurée pour le plugin CNPG.

        Note:
            Si ``target_version`` vaut ``"latest"``, l'interrogation des
            releases GitHub du projet ``cloudnative-pg/cloudnative-pg``
            doit être implémentée ici pour résoudre la véritable dernière
            version.

        Returns:
            La version cible configurée, ou ``None`` si elle doit encore
            être résolue dynamiquement.
        """
        target_version = self.module_config().get("target_version", "latest")
        return None if target_version == "latest" else target_version

    def install(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Installe le plugin ``kubectl-cnpg`` à la version cible.

        Note:
            Le téléchargement du binaire depuis les releases GitHub
            CloudNativePG doit être branché ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si l'installation s'est terminée avec succès.
        """
        return self._run_simulated_steps(
            ("Téléchargement", "Vérification", "Installation"), progress_callback
        )

    def uninstall(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Désinstalle le plugin ``kubectl-cnpg``.

        Note:
            La suppression effective du binaire doit être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la désinstallation s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Suppression",), progress_callback)

    def reconfigure(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Réapplique la configuration du plugin CNPG (alias, contextes par défaut).

        Note:
            La régénération effective des fichiers de configuration doit
            être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la reconfiguration s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Régénération config",), progress_callback)
