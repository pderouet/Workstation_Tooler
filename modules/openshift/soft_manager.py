"""Logique de mise à jour spécifique à l'outil OpenShift CLI (``oc``)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from modules.base_module import BaseModule, ProgressCallback


class OpenShiftModule(BaseModule):
    """Gère l'installation, la désinstallation et la configuration du binaire ``oc``."""

    name = "openshift"

    def get_installed_version(self) -> Optional[str]:
        """Interroge le binaire ``oc`` local pour connaître sa version.

        Returns:
            La chaîne de version retournée par ``oc version --client``, ou
            ``None`` si le binaire est introuvable ou l'appel a échoué.
        """
        oc_path = shutil.which("oc")
        if oc_path is None:
            return None
        try:
            result = subprocess.run(
                [oc_path, "version", "--client", "-o", "json"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.SubprocessError, OSError:
            return None
        return result.stdout.strip() or None

    def get_latest_version(self) -> Optional[str]:
        """Retourne la version cible configurée pour ``oc``.

        Note:
            Si ``target_version`` vaut ``"latest"`` dans ``modules_config.yaml``,
            l'interrogation du miroir interne (ou de l'API Red Hat) doit être
            implémentée ici pour résoudre la véritable dernière version.

        Returns:
            La version cible configurée, ou ``None`` si elle doit encore
            être résolue dynamiquement.
        """
        target_version = self.module_config().get("target_version", "latest")
        return None if target_version == "latest" else target_version

    def install(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Installe le binaire ``oc`` à la version cible.

        Note:
            Le téléchargement depuis le miroir interne et le dépôt du
            binaire dans le ``PATH`` doivent être implémentés ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si l'installation s'est terminée avec succès.
        """
        return self._run_simulated_steps(
            ("Téléchargement", "Vérification", "Installation"), progress_callback
        )

    def uninstall(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Désinstalle le binaire ``oc``.

        Note:
            La suppression effective du binaire et des fichiers de
            configuration associés doit être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la désinstallation s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Sauvegarde config", "Suppression"), progress_callback)

    def reconfigure(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Réapplique la configuration ``oc`` (kubeconfig, contextes, plugins).

        Note:
            La régénération effective des fichiers de configuration doit
            être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la reconfiguration s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Régénération config",), progress_callback)
