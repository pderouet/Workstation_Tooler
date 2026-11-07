# Instructions du Projet : Workstation_Tooler

> **Note agents IA** : ce fichier est la référence pour tout agent travaillant sur ce dépôt
> (ZCode le charge automatiquement). Les fichiers de `.github/instructions/` sont la copie
> destinée à GitHub Copilot : si le présent fichier évolue, pensez à les resynchroniser
> manuellement — ils ne sont pas lus automatiquement par ZCode.

## 🎯 Objectif du Projet
Application Python utilisant PyQt6 dont le point d'entrée est une icône dans le SystemTray.
L'application gère la mise à jour d'outils binaires et logiciels (OpenShift, Vim, DBeaver,
Freelens, etc.) pour les postes de travail.

## 🏗️ Architecture Technique (Contraintes Strictes)

### 1. Patrons de Conception (Singletons)
L'application repose sur plusieurs Singletons obligatoires, tous basés sur la métaclasse
`SingletonMeta` (`core/__init__.py`). Tout nouveau composant technique doit vérifier s'il
doit être un singleton :
- **Logger** (`core/logger.py`) : Doit inclure systématiquement le nom/ID du thread émetteur
  dans chaque log.
- **EventBus** (`core/event_bus.py`) : Basé sur `pyqtSignal`. C'est le canal de communication
  unique entre les threads et l'UI.
- **ThreadManager** (`core/thread_manager.py`) : Gère le cycle de vie des `QThread` et des
  Workers pour garantir que l'UI ne soit jamais bloquée.
- **ConfigLoader** (`core/config_loader.py`) : Charge les fichiers de configuration
  (`config/settings.yaml`, `config/modules_config.yaml`) au démarrage.
- **ErrorHandler** (`core/error_handler.py`) : Gestion centralisée des erreurs (logging +
  notification UI via l'EventBus).
- **Scheduler** (`core/scheduler.py`) : Planifie les vérifications récurrentes (application
  et modules) via `QTimer`, en déléguant l'exécution au `ThreadManager`.
- **AppUpdater** (`core/app_updater.py`) : Mise à jour de l'application elle-même (dépôt
  GitHub configuré dans `config/settings.yaml`).

### 2. Gestion des Erreurs
- **Interdiction** d'utiliser des blocs `try/except` génériques sans remontée.
- **Système Centralisé** (`core/error_handler.py`) : Toutes les exceptions doivent être
  capturées et envoyées au gestionnaire d'erreurs centralisé qui se charge du logging et de
  la notification via l'EventBus.

### 3. Modularité Fonctionnelle
- Chaque application mise à jour est un module indépendant dans `modules/`.
- Chaque module doit hériter de `BaseModule` (`modules/base_module.py`).
- **Mécanique d'initialisation** : Chaque module est attaché au socle via
  `attach(logger, event_bus, config, thread_manager)` (accès au logger, eventbus et config).
- Le chargement des modules est dynamique au démarrage (`main.discover_modules()` :
  tout sous-paquet de `modules/` exposant une sous-classe de `BaseModule` dans
  `soft_manager.py` est découvert automatiquement — inutile de modifier `main.py` pour
  ajouter un outil).

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
- **Thread-Safety** : Toute opération I/O ou mise à jour logicielle doit être déléguée au
  `ThreadManager` via un `QThread`.
- **Dépendances** : Ne pas ajouter de librairies tierces sans justification écrite ;
  dépendances runtime dans `requirements.txt`, dépendances de développement dans
  `requirements-dev.txt`.
- **Secrets** : Aucun mot de passe ou clé API en dur.

## 🖥️ Environnement & Lancement
- **Prérequis** : Python 3.14 ou supérieur.
- **Installation** :
  ```bash
  python -m venv .venv
  .venv/bin/pip install -r requirements.txt            # runtime
  .venv/bin/pip install -r requirements-dev.txt        # dev : tests, lint, icônes
  ```
- **Lancement** : `.venv/bin/python main.py` (le dossier `logs/` et le fichier de log
  `logs/workstation_tooler.log` sont créés au premier lancement).
- **Icônes** : les variantes colorées du SystemTray sont (re)générées par
  `python resources/icons/generate_icon_variants.py` (nécessite Pillow, fourni par
  `requirements-dev.txt`).
- **Configuration** : ne pas modifier les fichiers de `config/` sans coordination ;
  la config générale est dans `config/settings.yaml`, la config par module dans
  `config/modules_config.yaml`.

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
  tester la logique pure (chargement de configuration, comparaison de versions, parsing) ;
  mocker le réseau et les threads Qt.
- Tout nouveau module de mise à jour s'accompagne de tests sur sa logique pure (hors
  exécution réelle d'installation).

## 🌿 Conventions Git
- **Commits** : Conventional Commits avec description en français — `feat:`, `fix:`,
  `docs:`, `refactor:`, `test:`, `chore:` (ex. : `feat: ajoute le module de mise à jour k9s`).
  Titre à l'impératif, court (< 72 caractères).
- **Branches** : développement sur `main` pour le travail courant ; branches
  `feat/<sujet>` ou `fix/<sujet>` pour les changements de portée plus large.

## 🛠️ Workflow de Vérification
Avant de proposer une solution, s'assurer que :
1. L'interaction UI -> Logique passe par l'EventBus.
2. La logique lourde ne s'exécute pas dans le thread principal (GUI thread).
3. L'erreur potentielle est redirigée vers l'ErrorHandler.
4. Le module créé respecte l'interface de `BaseModule`.
5. `ruff check .`, `ruff format --check .` et `pytest` passent.

## 📝 Consignes de Modification
- Analyser les composants existants avant de créer une nouvelle fonction ou classe
  (vérifier si une solution équivalente existe déjà).
- Limiter les changements aux fichiers nécessaires à la tâche.
- Privilégier la réutilisation des Singletons du dossier `core/`.
- Ne pas modifier les fichiers de configuration sans coordination.
- Valider les données provenant de l'utilisateur ou de sources externes ; ne jamais
  ignorer silencieusement une exception.
