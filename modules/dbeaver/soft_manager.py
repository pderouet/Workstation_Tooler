"""Logique de mise à jour spécifique au client de base de données DBeaver."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from modules.base_module import BaseModule, ProgressCallback


class DBeaverModule(BaseModule):
    """Gère l'installation, la désinstallation et la configuration de DBeaver."""

    name = "dbeaver"

    def get_installed_version(self) -> Optional[str]:
        """Interroge le binaire ``dbeaver`` local pour connaître sa version.

        Returns:
            La première ligne retournée par ``dbeaver -version``, ou
            ``None`` si le binaire est introuvable ou l'appel a échoué.
        """
        dbeaver_path = shutil.which("dbeaver")
        if dbeaver_path is None:
            return None
        try:
            result = subprocess.run(
                [dbeaver_path, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except subprocess.SubprocessError, OSError:
            return None
        return result.stdout.splitlines()[0] if result.stdout else None

    def get_latest_version(self) -> Optional[str]:
        """Retourne la version cible configurée pour DBeaver.

        Note:
            Si ``target_version`` vaut ``"latest"``, l'interrogation du
            dépôt interne (ou de l'API GitHub de DBeaver) doit être
            implémentée ici pour résoudre la véritable dernière version.

        Returns:
            La version cible configurée, ou ``None`` si elle doit encore
            être résolue dynamiquement.
        """
        target_version = self.module_config().get("target_version", "latest")
        return None if target_version == "latest" else target_version

    def install(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Installe DBeaver à la version cible.

        Note:
            Le téléchargement de l'archive/installeur DBeaver depuis le
            dépôt interne doit être branché ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si l'installation s'est terminée avec succès.
        """
        return self._run_simulated_steps(
            ("Téléchargement", "Vérification", "Installation"), progress_callback
        )

    def uninstall(self, progress_callback: Optional[ProgressCallback] = None) -> bool:
        """Désinstalle DBeaver.

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
        """Réapplique la configuration DBeaver (connexions, préférences).

        Note:
            La régénération effective des fichiers de configuration doit
            être implémentée ici.

        Args:
            progress_callback: Fonction appelée avec un pourcentage (0-100).

        Returns:
            ``True`` si la reconfiguration s'est terminée avec succès.
        """
        return self._run_simulated_steps(("Régénération config",), progress_callback)
