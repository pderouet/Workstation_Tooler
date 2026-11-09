"""Tests headless du bootstrap applicatif (socle sans affichage).

Vérifie le câblage du journal : ``logging.file`` doit produire un fichier de
log persistant (promesse du README, indispensable sous Windows/``pythonw``
où il n'y a pas de console).

``ConfigLoader`` étant un singleton, chaque test réinitialise l'instance pour
pouvoir injecter son propre fichier de configuration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import SingletonMeta
from core.config_loader import PROJECT_ROOT, ConfigLoader
from main import _log_file_path, bootstrap


@pytest.fixture(autouse=True)
def restore_config_singleton():
    """Restaure le ConfigLoader singleton réel après chaque test.

    Les tests de ce module réinitialisent le singleton pour injecter leurs
    propres YAML ; les tests ultérieurs (ex. ``test_config_loader``) comptent
    sur l'instance pointant vers ``config/settings.yaml``.
    """
    yield
    SingletonMeta._instances.pop(ConfigLoader, None)
    ConfigLoader(settings_path=PROJECT_ROOT / "config" / "settings.yaml")


def make_config(tmp_path: Path, yaml_content: str) -> ConfigLoader:
    """Construit une instance fraîche de ConfigLoader sur un YAML temporaire."""
    SingletonMeta._instances.pop(ConfigLoader, None)  # reset du singleton.
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(yaml_content, encoding="utf-8")
    return ConfigLoader(settings_path=settings_file)


def test_bootstrap_cree_le_fichier_de_log(tmp_path: Path) -> None:
    """logging.file présent (absolu) → le journal est écrit dans ce fichier."""
    config = make_config(
        tmp_path,
        f"logging:\n  level: INFO\n  file: {tmp_path / 'logs' / 'app.log'}\n",
    )
    logger, _bus, _cfg, _threads, _errors = bootstrap(config=config)

    logger.info("message de test bootstrap")

    log_file = tmp_path / "logs" / "app.log"
    assert log_file.exists(), "le fichier de log doit être créé au premier lancement"
    assert "message de test bootstrap" in log_file.read_text(encoding="utf-8")


def test_bootstrap_sans_logging_file(tmp_path: Path) -> None:
    """logging.file absent : pas de fichier, la console seule est utilisée."""
    config = make_config(tmp_path, "logging:\n  level: INFO\n")
    logger, _bus, _cfg, _threads, _errors = bootstrap(config=config)

    assert _log_file_path(config) is None
    logger.info("message sans fichier")


def test_chemin_de_log_relatif_rattache_a_la_racine_projet(tmp_path: Path) -> None:
    """Un chemin relatif est résolu contre la racine du projet, pas le CWD."""
    config = make_config(tmp_path, "logging:\n  file: logs/app.log\n")
    assert _log_file_path(config) == PROJECT_ROOT / "logs" / "app.log"
