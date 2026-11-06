.
├── .github/
│   └── instructions/                   # Instructions globales pour Copilot
│       └── copilot-instructions.md     # Instructions globales pour Copilot
├── config/
│   ├── settings.yaml                   # Configuration générale
│   └── modules_config.yaml             # Configuration spécifique aux modules
├── core/
│   ├── __init__.py
│   ├── logger.py                       # Singleton Logger (avec Thread ID)
│   ├── event_bus.py                    # Singleton EventBus (PyQtSignal)
│   ├── config_loader.py                # Gestion du chargement des fichiers config
│   ├── thread_manager.py               # Singleton gestionnaire de QThreads/Workers
│   └── error_handler.py                # Système de gestion d'erreurs centralisé
├── modules/
│   ├── __init__.py
│   ├── base_module.py                  # Classe abstraite pour les modules de mise à jour
│   ├── openshift/
│   │   ├── __init__.py
│   │   └── soft_manager.py             # Logique spécifique à OpenShift
│   ├── vim/
│   │   ├── __init__.py
│   │   └── soft_manager.py             # Logique spécifique à Vim
│   └── dbeaver/
│       ├── __init__.py
│       └── soft_manager.py             # Logique spécifique à DBeaver
├── ui/
│   ├── __init__.py
│   └── tray_icon.py                    # Interface PyQt6 SystemTray
├── main.py                             # Point d'entrée principal
└── requirements.txt                    # Dépendances (PyQt6, PyYAML, etc.)
