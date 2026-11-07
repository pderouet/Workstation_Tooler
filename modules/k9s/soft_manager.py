"""Logique de mise à jour spécifique à l'outil de supervision Kubernetes K9s."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from modules.base_module import BaseModule, ProgressCallback


class K9sModule(BaseModule):
    """Gère l'installation, la désinstallation et la configuration de K9s."""

    name = "k9s"
    display_name = "K9s"

    def get_installed_version(self) -> Optional[str]:
        """Interroge le binaire ``k9s`` local pour connaître sa version.

        Returns:
            La version retournée par ``k9s version --short``, ou ``None``
            si le binaire est introuvable ou l'appel a échoué.
        """
        k9s_path = shutil.which("k9s")
        if k9s_path is None:
            return None
        try:
            result = subprocess.run(
                [k9s_path, "version", "--short"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.SubprocessError, OSError:
            return None
        return result.stdout.strip() or None

    def get_latest_version(self) -> Optional[str]:
        """Retourne la version cible configurée pour K9s.

        Note:
            Si ``target_version`` vaut ``"latest"``, l'interrogation des
            releases GitHub du projet ``derailed/k9s`` doit être
            implémentée ici pour résoudre la véritable dernière version.

        Returns:
            La version cible configurée, ou ``None`` si elle doit encore
            être résolue dynamiquement.
        """
        target_version = self.module_config().get("target_version", "latest")
        return None if target_version == "latest" else target_version

    def install(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Installe K9s à la version cible.

        Note:
            Le téléchargement du binaire depuis les releases GitHub
            ``derailed/k9s`` doit être branché ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si l'installation s'est terminée avec succès.
        """
        return self._run_simulated_steps(
            ("Téléchargement", "Vérification", "Installation"), progress_callback
        )

    def uninstall(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Désinstalle K9s.

        Note:
            La suppression effective du binaire doit être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la désinstallation s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Suppression",), progress_callback)

    def reconfigure(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Réapplique la configuration K9s (``skins``, alias de ressources).

        Note:
            La régénération effective des fichiers de configuration doit
            être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la reconfiguration s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Régénération config",), progress_callback)
