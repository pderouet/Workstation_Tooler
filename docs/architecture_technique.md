# Architecture technique

> Description du socle applicatif et du modèle d'exécution — pour comprendre,
> modifier ou étendre Workstation Tooler. Les procédures d'usage sont dans
> [`exploitation_catalogue.md`](exploitation_catalogue.md) (partage) et
> [`deploiement_poste.md`](deploiement_poste.md) (installation) ; les formats
> YAML dans [`configuration/`](configuration/README.md).

## Vue d'ensemble

L'application est organisée en quatre couches strictement séparées :

```
┌──────────────────────────────────────────────────────────────────────┐
│ UI (ui/tray_icon.py)                                                 │
│ TrayIcon : menu dynamique, notifications, choix de l'icône.          │
│ Aucune logique métier : déclenche des start_* et écoute l'EventBus.  │
└───────────────▲──────────────────────────────────┬───────────────────┘
                │ signaux (EventBus)               │ appels start_*
┌───────────────┴──────────────────────────────────▼───────────────────┐
│ SOCLE (core/) — singletons                                           │
│ Logger · EventBus · ThreadManager · ConfigLoader · ErrorHandler      │
│ Scheduler (+ ResourceHealthMonitor) · AppUpdater                      │
└───────────────┬──────────────────────────────────────────────────────┘
                │ délégation des tâches bloquantes (QThread + Worker)
┌───────────────▼──────────────────────────────────────────────────────┐
│ MOTEUR (engine/) — piloté par le catalogue distant                   │
│ storage (SMB/file) → repository → catalog → update_engine            │
│ models (validation) · version (tri naturel)                          │
│ detection (sous-processus) · actions (copy/decompress/ensure_content)│
└──────────────────────────────────────────────────────────────────────┘
        ▲ catalogue distant (partage SMB)          ▲ forge (HTTP)
```

Trois règles non négociables (détaillées en [fin de page](#règles-darchitecture)) :

1. **UI ↔ logique : uniquement via l'EventBus** ;
2. **toute opération bloquante passe par le ThreadManager** (jamais dans le
   thread GUI) ;
3. **toute exception remonte à l'ErrorHandler** (jamais d'except silencieux).

## Démarrage (`main.py`)

```
QApplication
  → bootstrap()          : ConfigLoader → Logger → EventBus → ThreadManager → ErrorHandler
  → build_repository()   : URI de settings.yaml → StorageBackend (SMB paresseux ou file://)
  → UpdateEngine(...)    : orchestrateur câblé sur le socle
  → TrayIcon(...)        : affichage immédiat (menu « Catalogue en cours de chargement… »)
  → engine.start_load_catalog()   ← tâche de fond : le menu se peuple via catalog_loaded
  → Scheduler().configure(engine) + start()  ← timers + première vérification
  → app.exec()           → à la sortie : scheduler.stop() puis thread_manager.shutdown()
```

Le partage réseau n'est **jamais** contacté avant la boucle d'événements :
un partage injoignable se traduit par une icône d'erreur et une reprise
automatique, pas par un plantage.

## Le socle (`core/`)

### Singletons

Deux mécanismes selon la nature de la classe :

| Mécanisme | Classes | Pourquoi |
|---|---|---|
| Métaclasse `SingletonMeta` (`core/__init__.py`) | `Logger`, `ConfigLoader`, `ErrorHandler`, `AppUpdater` | POJO purs : le dict d'instances de la métaclasse suffit. |
| Fabrique de module (`event_bus()`, `thread_manager()`, `scheduler()`) | `EventBus`, `ThreadManager`, `Scheduler` | `QObject`/sip : surcharger `__new__`/`__init__` y provoque, avec certaines combinaisons PyQt6/sip (constaté sous Windows), une récursion infinie de l'initialisation native (stack overflow silencieux). La fabrique crée l'unique instance en paresseux sur une classe Qt ordinaire — voir `tests/test_singletons.py`. |

Tout nouveau composant technique doit se demander s'il doit être singleton
(règle [AGENTS.md](../AGENTS.md)).

### EventBus (`core/event_bus.py`) — canal unique threads → UI

Bus de signaux PyQt6, singleton. La livraison inter-threads est assurée par
Qt (queued connections automatiques) : **émettre depuis un Worker est sûr**.

Table de référence des signaux :

| Signal | Signature | Émis par | Consommé par | Remarque |
|---|---|---|---|---|
| `error_occurred` | `(titre, message)` | `ErrorHandler` | TrayIcon | Notification critique. |
| `module_status_changed` | `(cible, statut)` | `AppUpdater`, `UpdateEngine._start_action` | TrayIcon | Journalisé (ex. `("vim", "mise_a_jour")`). |
| `update_finished` | `(cible, succès, message)` | TrayIcon lui-même (callbacks `on_result`) | TrayIcon | Notification de fin + sortie de `_pending_updates`. |
| `update_available` | `(cible, courant, dispo)` | `AppUpdater.check_update` | TrayIcon | **Réservé à `"app"`** (dialog 3 choix). |
| `catalog_updates_available` | `([{name, display_name, current, latest}])` | `UpdateEngine.check_updates` | TrayIcon | **Notification groupée** : un événement par vérification. |
| `resource_state_changed` | `(ressource, disponible)` | `Scheduler` (via `ResourceHealthMonitor`) | TrayIcon | Transitions uniquement : icône d'erreur + retry 3 min. |
| `catalog_loaded` | `([{name, display_name}])` | `UpdateEngine.load_catalog` | TrayIcon | Reconstruction du menu. |
| `task_started` | `(nom_tâche)` | `AppUpdater`, `UpdateEngine` | TrayIcon | Bascule l'icône en WIP. |
| `task_finished` | `(nom_tâche)` | idem | TrayIcon | Retour à l'état stable. |
| `log_message` | `(niveau, message)` | — | — | Déclaré, **non exploité** (prévu pour un panneau de logs UI). |
| `update_progress` | `(cible, %)` | — | — | Déclaré, **non exploité** (la progression passe par les callbacks). |

Les noms de tâches suivent la convention `engine.<cible>.<statut>` (ex.
`engine.vim.mise_a_jour`, `engine.catalogue.verification`, `app.verification`).

### ThreadManager (`core/thread_manager.py`) — exécution en tâche de fond

Cycle de vie d'une tâche (`run_task(func, on_result, on_error, on_progress)`) :

```
run_task
  → QThread + Worker(func) créés, Worker déplacé dans le thread (moveToThread)
  → thread.started ──▶ Worker.run()
  → run() exécute func ; injecte automatiquement progress_callback si la
    signature de func le déclare (introspection co_varnames)
  → finished(result) ──▶ on_result      error(Exception) ──▶ on_error
  → dans tous les cas : thread.quit() + deleteLater des objets, retrait de
    la table des threads actifs ; shutdown() à la sortie de l'application.
```

Points clés :
- **un QThread par tâche** (pas de pool) : simple, et le volume de tâches
  est faible par nature (vérifications, mises à jour) ;
- `Worker.run` attrape toute exception et l'émet via `error` : aucune tâche
  ne peut faire planter silencieusement l'application ;
- les callbacks `on_*` sont des **signaux Qt** : exécutés dans le thread GUI
  même si émis depuis le Worker.

### Scheduler et ResourceHealthMonitor (`core/scheduler.py`)

Le `Scheduler` ne contient **aucune logique lourde** : deux `QTimer` qui ne
font qu'appeler les `start_*` des composants (eux-mêmes déléguent au
ThreadManager).

`ResourceHealthMonitor` (logique pure, sans Qt, testée unitairement) suit la
disponibilité des ressources réseau :

| Ressource | Contrôle associé | Timer |
|---|---|---|
| `"catalogue"` | `UpdateEngine.start_check_updates` | `_applications_timer` |
| `"forge"` | `AppUpdater.start_check_update` | `_app_timer` |

Comportement : échec inédit → dégradation (notification interne
`resource_state_changed(False)`, timer basculé sur
`update.retry_interval_minutes` = 3 min) ; première réussite →
rétablissement (`True`, intervalle normal restauré). Les transitions seules
sont publiées. Côté AppUpdater, une version distante `None` (forge
injoignable) compte comme échec, sans exception.

### Les autres composants du socle

| Composant | Rôle | Points notables |
|---|---|---|
| `Logger` | Journal unique thread-safe | Chaque ligne porte `nom_thread:ident` ; console colorée par niveau (`NO_COLOR`/`FORCE_COLOR`, fichier jamais coloré). |
| `ConfigLoader` | Lecture de `config/settings.yaml` | Accès par clés à points (`repository.uri`), singleton, rechargement sur `reload()`. |
| `ErrorHandler` | Traitement centralisé des erreurs | `handle_exception(exc, context, notify_ui)` : log + émission `error_occurred` ; `notify_ui=False` pour les contrôles périodiques (pas de popup). |
| `AppUpdater` | Mise à jour de l'application | HTTP uniquement (version + archive) ; report « Pas aujourd'hui » en mémoire d'exécution ; lance `updater.py` détaché — voir [`maj_application.md`](maj_application.md). |

## Le moteur (`engine/`)

Couches indépendantes, chacune testable isolément :

| Module | Responsabilité | Points d'extension (injectables) |
|---|---|---|
| `models.py` | Dataclasses + parsing **strict** des YAML (schéma fermé, `yaml.safe_load`, clé inconnue = `ManifestError`) | — |
| `version.py` | Tri naturel des versions, résolution « plus récente » | — |
| `storage.py` | `StorageBackend` : SMB (session **paresseuse**, URI→UNC, invité sans signature) et local (`file://`) | backend via `build_storage_backend` |
| `repository.py` | Vue typée du catalogue (applications, versions, manifests, fichiers) | tout backend |
| `catalog.py` | Chargement **résilient** : application invalide = ignorée et journalisée | — |
| `detection.py` | Version installée depuis la déclaration `app.yaml` | exécuteur de commandes (`CommandOutput`) |
| `actions.py` | `copy` / `decompress` (extraction durcie, filtre `data`) / `ensure_content` (idempotent) | chemins via `expand_target` (`~`, variables) |
| `update_engine.py` | Orchestrateur : catalogue, vérifications, mises à jour, reconfiguration + wrappers `start_*` | détecteur (`VersionDetector`) |

Flux d'une mise à jour d'application :

```
menu « Mettre à jour > vim »
  → engine.start_update_application("vim")           (thread GUI)
  → ThreadManager → update_application()             (Worker)
      manifest de la dernière version (cache mémoire)
      pour chaque fichier : téléchargement en zone temporaire → action
      progression : progress_callback (une étape par fichier)
  → on_result → update_finished("vim", succès, message) → notification
```

La vérification (`check_updates`) charge le catalogue à la demande si
nécessaire, dégrade silencieusement une détection en échec (« non installé »)
et publie les mises à jour trouvées en **un seul** événement groupé.

## L'UI (`ui/tray_icon.py`)

Volontairement « fine » : aucun accès réseau, aucun fichier — uniquement des
déclenchements `start_*` et des réactions aux signaux.

- **Menu dynamique** : reconstruit à chaque `catalog_loaded` (placeholder
  « Catalogue en cours de chargement… » avant) ;
- **États internes** : `_active_tasks` (WIP), `_unavailable` (erreur),
  `_pending_updates` (info) — sources de vérité du choix d'icône :
  **WIP > Erreur > Info > OK** ;
- **Notification groupée** des mises à jour du catalogue ; dialog à trois
  choix (Oui / Non / Pas aujourd'hui) pour l'application elle-même.

## Règles d'architecture

Reprises d'[AGENTS.md](../AGENTS.md), appliquées partout dans ce code :

1. **EventBus unique canal UI ↔ logique** — jamais d'accès direct à l'UI
   depuis un Worker ;
2. **I/O uniquement via ThreadManager** — les méthodes bloquantes du moteur
   ne s'appellent qu'à travers les wrappers `start_*` ;
3. **Erreurs vers l'ErrorHandler** — un `except` qui avale sans remonter est
   interdit ;
4. **Validation stricte des entrées externes** (manifests : schéma fermé ;
   archives : extraction durcie ; commandes : listes d'arguments sans shell) ;
5. **Singletons du socle réutilisés** plutôt que réimplémentés.

## Stratégie de tests

**Headless intégral** : aucun test n'exige de `QApplication` ni d'affichage.

| Ce qui est testé | Comment |
|---|---|
| Socle (Scheduler, AppUpdater) | Doublures : `FakeEventBus`, `FakeThreadManager`, `FakeTimer`, ouvreur d'URL factice |
| Moteur complet (`tests/test_engine.py`) | Faux catalogue sur `tmp_path` (`tests/conftest.py`), détection et bus injectés |
| Détection, actions, versions | Exécuteur de commandes injecté ; vraies archives générées dans `tmp_path` |
| updater.py | `is_alive`/`ask_force`/`opener` injectés ; extraction et déploiement réels sur fichiers temporaires |

Lancement : `.venv/bin/python -m pytest -v` (143 tests), qualité :
`.venv/bin/ruff check .` et `.venv/bin/ruff format --check .`.
