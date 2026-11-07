"""Tests headless du singleton ConfigLoader (logique pure, sans Qt).

Valide la lecture du fichier de configuration réel du projet et le
comportement du patron Singleton via ``SingletonMeta``.
"""

from __future__ import annotations

from pathlib import Path

from core.config_loader import ConfigLoader

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def make_config_loader() -> ConfigLoader:
    """Retourne l'instance unique du ConfigLoader sur la config réelle."""
    return ConfigLoader(settings_path=SETTINGS_PATH)


def test_get_setting_cle_imbriquee_existante() -> None:
    """Une clé à points résout les niveaux imbriqués du settings.yaml."""
    config = make_config_loader()
    assert config.get_setting("logging.level") == "INFO"


def test_get_setting_cle_absente_retourne_defaut() -> None:
    """Une clé absente retourne la valeur par défaut fournie."""
    config = make_config_loader()
    assert config.get_setting("cle.absente", default="secours") == "secours"


def test_get_setting_chemin_reseau_du_catalogue() -> None:
    """Le chemin réseau du catalogue est exposé par la configuration locale."""
    config = make_config_loader()
    assert config.get_setting("repository.uri") == "smb://localhost/Workstation_Tooler"


def test_config_loader_est_un_singleton() -> None:
    """Deux instanciations retournent la même instance (SingletonMeta)."""
    config_1 = make_config_loader()
    config_2 = make_config_loader()
    assert config_1 is config_2
