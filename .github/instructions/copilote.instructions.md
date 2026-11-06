---
applyTo: "**"
---

# Instructions du Projet : Workstaction_Tooler

## 🎯 Objectif du Projet
Application Python utilisant PyQt6 dont le point d'entrée est une icône dans le SystemTray. L'application gère la mise à jour d'outils binaires et logiciels (OpenShift, Vim, DBeaver, Freelens, etc.) pour les postes de travail.

## 🏗️ Architecture Technique (Contraintes Strictes)

### 1. Patrons de Conception (Singletons)
L'application repose sur plusieurs Singletons obligatoires. Tout nouveau composant technique doit vérifier s'il doit être un singleton :
- **Logger** (`core/logger.py`) : Doit inclure systématiquement le nom/ID du thread émetteur dans chaque log.
- **EventBus** (`core/event_bus.py`) : Basé sur `pyqtSignal`. C'est le canal de communication unique entre les threads et l'UI.
- **ThreadManager** (`core/thread_manager.py`) : Gère le cycle de vie des `QThread` et des Workers pour garantir que l'UI ne soit jamais bloquée.
- **ConfigLoader** (`core/config_loader.py`) : Charge les fichiers de configuration au démarrage.

### 2. Gestion des Erreurs
- **Interdiction** d'utiliser des blocs `try/except` génériques sans remontée.
- **Système Centralisé** (`core/error_handler.py`) : Toutes les exceptions doivent être capturées et envoyées au gestionnaire d'erreurs centralisé qui se charge du logging et de la notification via l'EventBus.

### 3. Modularité Fonctionnelle
- Chaque application mise à jour est un module indépendant dans `modules/`.
- Chaque module doit hériter de `BaseModule` (`modules/base_module.py`).
- **Mécanique d'initialisation** : Chaque module doit implémenter une méthode d'attachement au socle (accès au logger, eventbus et config).
- Le chargement des modules est dynamique au démarrage.

### Gestion de l'arborescence
- L'arborescence doit  être basée sur la description qui en est faite dans le docoment `docs/arborescence.md`


## 💻 Conventions de Code Python

### Standards
- **Framework** : PyQt6.
- **Typage** : Utilisation systématique des annotations de type (`typing`).
- **Style** : Respect strict de la PEP 8.
- **Docstrings** : Obligatoires pour toutes les classes et méthodes publiques.

### Développement
- **Thread-Safety** : Toute opération I/O ou mise à jour logicielle doit être déléguée au `ThreadManager` via un `QThread`.
- **Dépendances** : Ne pas ajouter de librairies tierces sans justification.
- **Secrets** : Aucun mot de passe ou clé API en dur.

## 🛠️ Workflow de Vérification
Avant de proposer une solution, Copilot doit s'assurer que :
1. L'interaction UI -> Logique passe par l'EventBus.
2. La logique lourde ne s'exécute pas dans le thread principal (GUI thread).
3. L'erreur potentielle est redirigée vers le `ErrorHandler`.
4. Le module créé respecte l'interface de `BaseModule`.

## 📝 Consignes de Modification
- Analyser les composants existants avant de créer une nouvelle fonction.
- Privilégier la réutilisation des Singletons du dossier `core/`.
- Ne pas modifier les fichiers de configuration sans coordination.
