.
├── .github/
│   └── instructions/                   # Instructions pour GitHub Copilot (copie — la référence est AGENTS.md à la racine)
│       ├── copilote.instructions.md    # Instructions globales pour GitHub Copilot
│       └── python.instructions.md      # Consignes de code Python pour GitHub Copilot
├── AGENTS.md                           # Instructions de référence pour les agents IA (ZCode)
├── .gitignore                          # Fichiers ignorés par Git (caches, venv, logs)
├── README.md                           # Présentation, installation, lancement
├── pyproject.toml                      # Configuration ruff (lint/format) et pytest
├── config/
│   ├── settings.yaml                   # Configuration générale
│   └── modules_config.yaml             # Configuration spécifique aux modules
├── core/
│   ├── __init__.py                     # SingletonMeta (métaclasse Singleton partagée)
│   ├── logger.py                       # Singleton Logger (avec Thread ID)
│   ├── event_bus.py                    # Singleton EventBus (PyQtSignal)
│   ├── config_loader.py                # Gestion du chargement des fichiers config
│   ├── thread_manager.py               # Singleton gestionnaire de QThreads/Workers
│   ├── error_handler.py                # Système de gestion d'erreurs centralisé
│   ├── app_updater.py                  # Singleton de mise à jour de l'application elle-même
│   └── scheduler.py                    # Singleton de planification des vérifications récurrentes
├── docs/
│   └── arborescence.md                 # Ce document : description de référence de l'arborescence
├── modules/
│   ├── __init__.py
│   ├── base_module.py                  # Classe abstraite pour les modules de mise à jour
│   ├── openshift/
│   │   ├── __init__.py
│   │   └── soft_manager.py             # Logique spécifique à OpenShift
│   ├── openshift_cnpg/
│   │   ├── __init__.py
│   │   └── soft_manager.py             # Logique spécifique au plugin OpenShift CloudNativePG
│   ├── vim/
│   │   ├── __init__.py
│   │   └── soft_manager.py             # Logique spécifique à Vim
│   ├── dbeaver/
│   │   ├── __init__.py
│   │   └── soft_manager.py             # Logique spécifique à DBeaver
│   ├── freelens/
│   │   ├── __init__.py
│   │   └── soft_manager.py             # Logique spécifique à FreeLens
│   ├── k9s/
│   │   ├── __init__.py
│   │   └── soft_manager.py             # Logique spécifique à K9s
│   └── powershell_config/
│       ├── __init__.py
│       └── soft_manager.py             # Déploiement de la configuration PowerShell du poste
├── tests/
│   └── test_config_loader.py           # Tests headless du ConfigLoader (logique pure)
├── ui/
│   ├── __init__.py
│   └── tray_icon.py                    # Interface PyQt6 SystemTray
├── resources/
│   └── icons/
│       ├── app_icon.ico                # Icône source
│       ├── app_icon_ok.ico             # Variante verte (état OK)
│       ├── app_icon_info.ico           # Variante bleue (information / maj disponible)
│       ├── app_icon_wip.ico            # Variante jaune (opération en cours)
│       └── generate_icon_variants.py   # Utilitaire de génération des variantes colorées
├── main.py                             # Point d'entrée principal
├── requirements.txt                    # Dépendances runtime (PyQt6, PyYAML)
└── requirements-dev.txt                # Dépendances de développement (ruff, pytest, Pillow)
