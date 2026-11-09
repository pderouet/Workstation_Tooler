.
├── .github/
│   ├── instructions/                   # Instructions pour GitHub Copilot (copie — la référence est AGENTS.md à la racine)
│   │   ├── copilote.instructions.md    # Instructions globales pour GitHub Copilot
│   │   └── python.instructions.md      # Consignes de code Python pour GitHub Copilot
│   └── workflows/
│       └── version.yml                 # CI : incrémente le patch de version.txt à chaque push sur main
├── AGENTS.md                           # Instructions de référence pour les agents IA (ZCode)
├── .gitignore                          # Fichiers ignorés par Git (caches, venv, logs)
├── README.md                           # Présentation, installation, lancement
├── pyproject.toml                      # Configuration ruff (lint/format) et pytest
├── version.txt                         # Version courante (source de vérité, incrémentée par la CI)
├── updater.py                          # Script autonome de mise à jour de l'application, 100 % HTTP (voir docs/maj_application.md)
├── config/
│   └── settings.yaml                   # Configuration générale (logging, scheduler, repository.uri, github, ui)
├── core/
│   ├── __init__.py                     # SingletonMeta (métaclasse Singleton partagée)
│   ├── logger.py                       # Singleton Logger (avec Thread ID)
│   ├── event_bus.py                    # Singleton EventBus (PyQtSignal, dont catalog_loaded)
│   ├── config_loader.py                # Chargement de config/settings.yaml (clés à points)
│   ├── thread_manager.py               # Singleton gestionnaire de QThreads/Workers
│   ├── error_handler.py                # Système de gestion d'erreurs centralisé
│   ├── app_updater.py                  # Singleton de mise à jour de l'application elle-même
│   └── scheduler.py                    # Singleton de planification des vérifications récurrentes
├── docs/
│   ├── arborescence.md                 # Ce document : description de référence de l'arborescence
│   ├── moteur_mise_a_jour.md           # Référence du moteur : catalogue distant, manifests, actions
│   └── maj_application.md              # Référence de la mise à jour autonome de l'application (forge, updater.py)
├── engine/                             # Moteur de mise à jour piloté par le catalogue distant
│   ├── __init__.py                     # Présentation du paquet engine
│   ├── models.py                       # Dataclasses du catalogue + parsing/validation stricts des YAML
│   ├── version.py                      # Comparaison de versions (tri naturel), résolution « plus récente »
│   ├── storage.py                      # StorageBackend : SMB (smbprotocol) et local (file://), fabrique
│   ├── repository.py                   # Vue typée du catalogue (applications, versions, manifests)
│   ├── catalog.py                      # Chargement résilient du catalogue depuis le chemin réseau
│   ├── detection.py                    # Détection de la version installée (déclarée dans app.yaml)
│   ├── actions.py                      # Exécuteurs copy / decompress / ensure_content
│   └── update_engine.py                # Orchestrateur (vérifications, mises à jour, wrappers start_*)
├── examples/
│   └── partage/                        # Catalogue d'exemple à recopier sur le chemin réseau de test
│       ├── README.md                   # Mode d'emploi (alimentation du partage, essai file://)
│       ├── vim/                        # Démontre decompress + copy (mode 755) + ensure_content
│       └── k9s/                        # Démontre decompress seule
├── tests/
│   ├── conftest.py                     # Faux catalogue complet sur système de fichiers local (fixtures)
│   ├── test_config_loader.py           # Tests headless du ConfigLoader
│   ├── test_version.py                 # Tri naturel des versions
│   ├── test_models.py                  # Parsing/validation des manifests (schéma strict)
│   ├── test_storage.py                 # Backend local, fabrique, conversion URI smb:// → UNC
│   ├── test_catalog.py                 # Repository et chargement du catalogue
│   ├── test_detection.py               # Extraction de version (exécuteur de commandes injecté)
│   ├── test_actions.py                 # copy / decompress (zip, tar.gz, gz) / ensure_content
│   ├── test_engine.py                  # Orchestrateur complet (doublures du socle, sans Qt)
│   ├── test_app_updater.py             # AppUpdater : versions, forges GitHub/GitLab, report, spawn
│   └── test_updater.py                 # updater.py : PID, forçage, déploiement Git (intégration locale)
├── ui/
│   ├── __init__.py
│   └── tray_icon.py                    # Interface PyQt6 SystemTray (menu dynamique selon le catalogue)
├── resources/
│   └── icons/
│       ├── app_icon.ico                # Icône source
│       ├── app_icon_ok.ico             # Variante verte (état OK)
│       ├── app_icon_info.ico           # Variante bleue (information / maj disponible)
│       ├── app_icon_wip.ico            # Variante jaune (opération en cours)
│       ├── app_icon_err.ico            # Variante rouge (ressource réseau inaccessible)
│       └── generate_icon_variants.py   # Utilitaire de génération des variantes colorées
├── main.py                             # Point d'entrée : socle + UpdateEngine + TrayIcon + Scheduler
├── requirements.txt                    # Dépendances runtime (PyQt6, PyYAML, smbprotocol)
└── requirements-dev.txt                # Dépendances de développement (ruff, pytest, Pillow)
