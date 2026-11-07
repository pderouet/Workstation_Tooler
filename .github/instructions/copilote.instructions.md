---
applyTo: "**"
---

# Instructions du Projet : Workstation_Tooler

## 🎯 Objectif du Projet
Application Python utilisant PyQt6 dont le point d'entrée est une icône dans le SystemTray. L'application gère la mise à jour d'outils binaires et logiciels (OpenShift, Vim, DBeaver, Freelens, etc.) pour les postes de travail, à partir d'un catalogue hébergé sur un chemin réseau unique (partage SMB).

## 🏗️ Architecture Technique (Contraintes Strictes)

### 1. Patrons de Conception (Singletons)
L'application repose sur plusieurs Singletons obligatoires. Tout nouveau composant technique doit vérifier s'il doit être un singleton :
- **Logger** (`core/logger.py`) : Doit inclure systématiquement le nom/ID du thread émetteur dans chaque log.
- **EventBus** (`core/event_bus.py`) : Basé sur `pyqtSignal`. C'est le canal de communication unique entre les threads et l'UI (y compris `catalog_loaded`).
- **ThreadManager** (`core/thread_manager.py`) : Gère le cycle de vie des `QThread` et des Workers pour garantir que l'UI ne soit jamais bloquée.
- **ConfigLoader** (`core/config_loader.py`) : Charge `config/settings.yaml` au démarrage (clés à points).
- **ErrorHandler** (`core/error_handler.py`) : Gestion centralisée des erreurs.
- **Scheduler** (`core/scheduler.py`) : Planifie les vérifications récurrentes via `QTimer`, en déléguant l'exécution au `ThreadManager`.
- **AppUpdater** (`core/app_updater.py`) : Mise à jour de l'application elle-même — version locale/distante (`version.txt`, forge GitHub ou GitLab selon `forge.provider`), notification à trois choix et lancement du script autonome `updater.py` (voir `docs/maj_application.md`).

### 2. Gestion des Erreurs
- **Interdiction** d'utiliser des blocs `try/except` génériques sans remontée.
- **Système Centralisé** (`core/error_handler.py`) : Toutes les exceptions doivent être capturées et envoyées au gestionnaire d'erreurs centralisé qui se charge du logging et de la notification via l'EventBus.

### 3. Moteur de mise à jour piloté par catalogue (`engine/`)
Il n'y a plus de module Python par outil : un moteur unique (`engine/update_engine.py`) découvre les applications depuis le catalogue distant — un dossier par application avec `app.yaml`, un dossier par version avec `manifest.yaml`, actions `copy` / `decompress` / `ensure_content`. Référence : `docs/moteur_mise_a_jour.md`. Ajouter un outil = déposer des fichiers sur le partage, zéro code local.
- **Validation stricte des manifests** (`engine/models.py`) : schéma fermé, `yaml.safe_load`, actions limitées à l'enum.
- **Résilience** : une application mal déclarée est ignorée et journalisée, sans empêcher le traitement des autres.
- **Backends de stockage** (`engine/storage.py`) : SMB (`smbprotocol`) ou `file://` (dev/tests).

### Gestion de l'arborescence
- L'arborescence doit être basée sur la description qui en est faite dans le document `docs/arborescence.md`.

## 💻 Conventions de Code Python

### Standards
- **Framework** : PyQt6.
- **Python** : version 3.14+ (conserver `from __future__ import annotations`).
- **Typage** : Utilisation systématique des annotations de type (`typing`).
- **Style** : Respect strict de la PEP 8.
- **Docstrings** : Obligatoires pour toutes les classes et méthodes publiques, en français, style Google.

### Développement
- **Thread-Safety** : Toute opération I/O (réseau SMB, sous-processus, fichiers) doit être déléguée au `ThreadManager` via un `QThread` — les méthodes bloquantes du moteur ne s'appellent qu'à travers les wrappers `start_*`.
- **Dépendances** : Ne pas ajouter de librairies tierces sans justification écrite.
- **Secrets** : Aucun mot de passe ou clé API en dur (mot de passe SMB : variable d'environnement `WORKSTATION_TOOLER_SMB_PASSWORD`). Exception assumée : le token GitLab en lecture seule `GITLAB_READ_TOKEN` vit dans `core/app_updater.py` (voir `docs/maj_application.md`).

## 🛠️ Workflow de Vérification
Avant de proposer une solution, Copilot doit s'assurer que :
1. L'interaction UI -> Logique passe par l'EventBus.
2. La logique lourde ne s'exécute pas dans le thread principal (GUI thread).
3. L'erreur potentielle est redirigée vers l'`ErrorHandler`.
4. Les nouveaux YAML du catalogue respectent le schéma strict de `engine/models.py` (voir `docs/moteur_mise_a_jour.md`).

## 📝 Consignes de Modification
- Analyser les composants existants avant de créer une nouvelle fonction.
- Privilégier la réutilisation des Singletons du dossier `core/`.
- Ne pas modifier les fichiers de configuration sans coordination.
