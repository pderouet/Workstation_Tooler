# Instructions du Projet : Workstation_Tooler

> **Note agents IA** : ce fichier est la référence pour tout agent travaillant sur ce dépôt
> (ZCode le charge automatiquement). Les fichiers de `.github/instructions/` sont la copie
> destinée à GitHub Copilot : si le présent fichier évolue, pensez à les resynchroniser
> manuellement — ils ne sont pas lus automatiquement par ZCode.

## 🎯 Objectif du Projet
Application Python utilisant PyQt6 dont le point d'entrée est une icône dans le SystemTray.
L'application gère la mise à jour d'outils binaires et logiciels (OpenShift, Vim, DBeaver,
Freelens, K9s, etc.) pour les postes de travail, à partir d'un catalogue hébergé sur un
chemin réseau unique (partage SMB).

## 🏗️ Architecture Technique (Contraintes Strictes)

### 1. Patrons de Conception (Singletons)
L'application repose sur plusieurs Singletons obligatoires, basés sur la métaclasse
`SingletonMeta` (`core/__init__.py`) — ou sur un `__new__` gardé pour les `QObject`. Tout
nouveau composant technique doit vérifier s'il doit être un singleton :
- **Logger** (`core/logger.py`) : Doit inclure systématiquement le nom/ID du thread émetteur
  dans chaque log.
- **EventBus** (`core/event_bus.py`) : Basé sur `pyqtSignal`. C'est le canal de communication
  unique entre les threads et l'UI (y compris `catalog_loaded`, qui peuple le menu).
- **ThreadManager** (`core/thread_manager.py`) : Gère le cycle de vie des `QThread` et des
  Workers pour garantir que l'UI ne soit jamais bloquée.
- **ConfigLoader** (`core/config_loader.py`) : Charge `config/settings.yaml` au démarrage
  (accès par clés à points, ex. `repository.uri`).
- **ErrorHandler** (`core/error_handler.py`) : Gestion centralisée des erreurs (logging +
  notification UI via l'EventBus).
- **Scheduler** (`core/scheduler.py`) : Planifie les vérifications récurrentes (application
  et applications du catalogue) via `QTimer`, en déléguant l'exécution au `ThreadManager`.
- **AppUpdater** (`core/app_updater.py`) : Mise à jour de l'application elle-même —
  version locale/distante (`version.txt`, forge GitHub ou GitLab selon `forge.provider`),
  notification à trois choix et lancement du script autonome `updater.py`
  (voir `docs/maj_application.md`).

### 2. Gestion des Erreurs
- **Interdiction** d'utiliser des blocs `try/except` génériques sans remontée.
- **Système Centralisé** (`core/error_handler.py`) : Toutes les exceptions doivent être
  capturées et envoyées au gestionnaire d'erreurs centralisé qui se charge du logging et de
  la notification via l'EventBus.

### 3. Moteur de mise à jour piloté par catalogue (`engine/`)
Il n'y a **plus de module Python par outil** : un moteur unique découvre les applications
depuis le catalogue distant — un dossier par application avec `app.yaml`, un dossier par
version avec `manifest.yaml`, actions `copy` / `decompress` / `ensure_content`. Référence
complète : `docs/moteur_mise_a_jour.md`. Ajouter un outil = déposer des fichiers sur le
partage, **zéro code local**.
- **UpdateEngine** (`engine/update_engine.py`) : orchestrateur unique (catalogue,
  vérifications, mises à jour, reconfiguration), câblé dans `main.py` sur un
  `RemoteRepository` (`engine/repository.py`) appuyé sur un `StorageBackend`
  (`engine/storage.py` : SMB via `smbprotocol`, ou `file://` pour dev/tests).
- **Validation stricte des manifests** (`engine/models.py`) : schéma fermé, `yaml.safe_load`,
  actions limitées à l'enum — toute clé inconnue est une erreur.
- **Résilience** : une application mal déclarée est ignorée et journalisée, sans empêcher
  le traitement des autres.

### Gestion de l'arborescence
- L'arborescence doit être basée sur la description qui en est faite dans le document
  `docs/arborescence.md` (document de référence à maintenir à jour en cas de changement
  de structure).

## 💻 Conventions de Code Python

### Standards
- **Framework** : PyQt6.
- **Python** : version 3.14+ (conserver `from __future__ import annotations` et le style
  d'import déjà en place).
- **Typage** : Utilisation systématique des annotations de type.
- **Style** : Respect strict de la PEP 8, noms explicites pour les variables, fonctions et
  classes.
- **Docstrings** : Obligatoires pour toutes les classes et méthodes publiques, en français,
  dans le style Google déjà présent dans le projet (voir `core/config_loader.py` pour
  l'exemple de référence).
- Privilégier du code simple, lisible et facile à tester.

### Développement
- **Thread-Safety** : Toute opération I/O (réseau SMB, sous-processus, fichiers) doit être
  déléguée au `ThreadManager` via un `QThread` — les méthodes bloquantes du moteur ne
  s'appellent qu'à travers les wrappers `start_*`.
- **Dépendances** : Ne pas ajouter de librairies tierces sans justification écrite ;
  dépendances runtime dans `requirements.txt`, dépendances de développement dans
  `requirements-dev.txt` (justification de `smbprotocol` en tête de `requirements.txt`).
- **Secrets** : Aucun mot de passe ou clé API en dur — le mot de passe SMB éventuel passe
  par la variable d'environnement `WORKSTATION_TOOLER_SMB_PASSWORD`. **Exception assumée**
  (décision du propriétaire du projet) : le token GitLab en lecture seule
  `GITLAB_READ_TOKEN` vit dans `core/app_updater.py` (voir `docs/maj_application.md`).

## 🖥️ Environnement & Lancement
- **Prérequis** : Python 3.14 ou supérieur.
- **Installation** :
  ```bash
  python -m venv .venv
  .venv/bin/pip install -r requirements.txt            # runtime
  .venv/bin/pip install -r requirements-dev.txt        # dev : tests, lint, icônes
  ```
- **Lancement** : `.venv/bin/python main.py` (le dossier `logs/` et le fichier de log
  `logs/workstation_tooler.log` sont créés au premier lancement ; le catalogue est chargé
  en tâche de fond au démarrage).
- **Icônes** : les variantes colorées du SystemTray sont (re)générées par
  `python resources/icons/generate_icon_variants.py` (nécessite Pillow, fourni par
  `requirements-dev.txt`).
- **Configuration** : ne pas modifier les fichiers de `config/` sans coordination ;
  la config générale est dans `config/settings.yaml` (chemin réseau du catalogue :
  `repository.uri`). La configuration des applications gérées est **externalisée sur le
  chemin réseau** (voir `docs/moteur_mise_a_jour.md`).

## 🧹 Qualité de Code
Avant de livrer une modification, s'assurer que :
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```
passent sans erreur (configuration dans `pyproject.toml`). Corriger les avertissements
plutôt que de les ignorer.

## 🧪 Tests
- Framework : **pytest**, tests dans `tests/` (configuration dans `pyproject.toml`).
- Lancer : `.venv/bin/python -m pytest -v`.
- **Tests headless** : aucun test ne doit exiger un `QApplication` ni un affichage —
  tester la logique pure (parsing des manifests, comparaison de versions, actions sur
  fichiers via `tmp_path`, catalogue factice de `tests/conftest.py`) ; mocker le réseau
  SMB, les commandes de détection et les threads Qt (doublures du socle, voir
  `tests/test_engine.py`).
- Toute évolution du moteur s'accompagne de tests sur sa logique pure (hors accès réseau
  réel).

## 🌿 Conventions Git
- **Commits** : Conventional Commits avec description en français — `feat:`, `fix:`,
  `docs:`, `refactor:`, `test:`, `chore:` (ex. : `feat: ajoute l'action decompress au moteur`).
  Titre à l'impératif, court (< 72 caractères).
- **Branches** : développement sur `main` pour le travail courant ; branches
  `feat/<sujet>` ou `fix/<sujet>` pour les changements de portée plus large.

## 🛠️ Workflow de Vérification
Avant de proposer une solution, s'assurer que :
1. L'interaction UI -> Logique passe par l'EventBus.
2. La logique lourde ne s'exécute pas dans le thread principal (GUI thread).
3. L'erreur potentielle est redirigée vers l'ErrorHandler.
4. Les nouveaux YAML du catalogue respectent le schéma strict de `engine/models.py`
   (voir `docs/moteur_mise_a_jour.md`).
5. `ruff check .`, `ruff format --check .` et `pytest` passent.

## 📝 Consignes de Modification
- Analyser les composants existants avant de créer une nouvelle fonction ou classe
  (vérifier si une solution équivalente existe déjà).
- Limiter les changements aux fichiers nécessaires à la tâche.
- Privilégier la réutilisation des Singletons du dossier `core/`.
- Ne pas modifier les fichiers de configuration sans coordination.
- Valider les données provenant de l'utilisateur ou de sources externes ; ne jamais
  ignorer silencieusement une exception.
