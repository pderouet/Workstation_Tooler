"""Logique de mise à jour spécifique au client Kubernetes/OpenShift FreeLens."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from modules.base_module import BaseModule, ProgressCallback


class FreeLensModule(BaseModule):
    """Gère l'installation, la désinstallation et la configuration de FreeLens."""

    name = "freelens"
    display_name = "FreeLens"

    def get_installed_version(self) -> Optional[str]:
        """Interroge le binaire ``freelens`` local pour connaître sa version.

        Returns:
            La version retournée par ``freelens --version``, ou ``None`` si
            le binaire est introuvable ou l'appel a échoué.
        """
        freelens_path = shutil.which("freelens")
        if freelens_path is None:
            return None
        try:
            result = subprocess.run(
                [freelens_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.SubprocessError, OSError:
            return None
        return result.stdout.strip() or None

    def get_latest_version(self) -> Optional[str]:
        """Retourne la version cible configurée pour FreeLens.

        Note:
            Si ``target_version`` vaut ``"latest"``, l'interrogation des
            releases GitHub de FreeLens doit être implémentée ici pour
            résoudre la véritable dernière version.

        Returns:
            La version cible configurée, ou ``None`` si elle doit encore
            être résolue dynamiquement.
        """
        target_version = self.module_config().get("target_version", "latest")
        return None if target_version == "latest" else target_version

    def install(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Installe FreeLens à la version cible.

        Note:
            Le téléchargement de l'installeur depuis le dépôt interne ou
            les releases GitHub doit être branché ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si l'installation s'est terminée avec succès.
        """
        return self._run_simulated_steps(
            ("Téléchargement", "Vérification", "Installation"), progress_callback
        )

    def uninstall(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Désinstalle FreeLens.

        Note:
            La suppression effective de l'installation doit être
            implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la désinstallation s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Sauvegarde config", "Suppression"), progress_callback)

    def reconfigure(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Réapplique la configuration FreeLens (clusters, extensions).

        Note:
            La régénération effective des fichiers de configuration doit
            être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la reconfiguration s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Régénération config",), progress_callback)
