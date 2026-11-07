"""Singleton ConfigLoader : chargement des fichiers de configuration YAML.

Charge au démarrage les fichiers ``config/settings.yaml`` (configuration
générale) et ``config/modules_config.yaml`` (configuration par module), et
expose un accès en lecture simple au reste de l'application.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from core import SingletonMeta

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_MODULES_CONFIG_PATH = PROJECT_ROOT / "config" / "modules_config.yaml"


class ConfigLoader(metaclass=SingletonMeta):
    """Charge et expose la configuration de l'application.

    Exemple :
        >>> ConfigLoader().get_setting("logging.level", default="INFO")
    """

    def __init__(
        self,
        settings_path: Path = DEFAULT_SETTINGS_PATH,
        modules_config_path: Path = DEFAULT_MODULES_CONFIG_PATH,
    ) -> None:
        """Charge les fichiers de configuration fournis.

        Args:
            settings_path: Chemin du fichier de configuration générale.
            modules_config_path: Chemin du fichier de configuration des modules.
        """
        self._settings_path = settings_path
        self._modules_config_path = modules_config_path
        self._settings: Dict[str, Any] = {}
        self._modules_config: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        """Recharge les fichiers de configuration depuis le disque."""
        self._settings = self._load_yaml(self._settings_path)
        self._modules_config = self._load_yaml(self._modules_config_path)

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        """Charge un fichier YAML et retourne un dictionnaire vide s'il est absent.

        Args:
            path: Chemin du fichier YAML à charger.

        Returns:
            Le contenu du fichier sous forme de dictionnaire.
        """
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as config_file:
            content = yaml.safe_load(config_file)
        return content or {}

    def get_setting(self, dotted_key: str, default: Optional[Any] = None) -> Any:
        """Récupère une valeur de la configuration générale.

        Args:
            dotted_key: Clé à récupérer, les niveaux imbriqués étant séparés
                par des points (ex. ``"logging.level"``).
            default: Valeur retournée si la clé est absente.

        Returns:
            La valeur trouvée ou ``default``.
        """
        return self._resolve(self._settings, dotted_key, default)

    def get_module_config(self, module_name: str, default: Optional[Any] = None) -> Any:
        """Récupère la configuration propre à un module.

        Args:
            module_name: Nom du module (ex. ``"openshift"``).
            default: Valeur retournée si le module n'a pas de configuration.

        Returns:
            Le dictionnaire de configuration du module ou ``default``.
        """
        return self._modules_config.get("modules", {}).get(module_name, default)

    @staticmethod
    def _resolve(data: Dict[str, Any], dotted_key: str, default: Optional[Any]) -> Any:
        """Résout une clé à points dans un dictionnaire imbriqué."""
        current: Any = data
        for part in dotted_key.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current
