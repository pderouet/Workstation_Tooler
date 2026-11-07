# Workstation Tooler

Application Python (PyQt6) résidant dans le SystemTray, qui gère la mise à jour
d'outils binaires et logiciels sur les postes de travail : OpenShift CLI (`oc`),
plugin OpenShift CloudNativePG, Vim, DBeaver, FreeLens, K9s et le déploiement de
la configuration PowerShell du poste.

L'architecture repose sur un socle de singletons (`core/` : Logger, EventBus,
ThreadManager, ConfigLoader, ErrorHandler, Scheduler, AppUpdater) auquel
s'attachent des modules de mise à jour indépendants (`modules/`), découverts
dynamiquement au démarrage. L'interface se limite à une icône SystemTray (`ui/`)
dont l'état visuel reflète l'activité : vert (OK), bleu (information / mise à
jour disponible), jaune (opération en cours).

## Prérequis

- Python 3.14 ou supérieur
- Un environnement de bureau avec SystemTray (GNOME : extension AppIndicator, etc.)

## Installation

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Lancement

```bash
.venv/bin/python main.py
```

Les logs sont écrits dans `logs/workstation_tooler.log` (dossier créé au
premier lancement). La configuration générale (`config/settings.yaml`) définit
notamment le niveau de log et les intervalles de vérification des mises à
jour ; la configuration par outil (`config/modules_config.yaml`) active chaque
module et précise sa version cible et son URL de téléchargement.

## Développement

Installation des dépendances de développement, puis vérifications à faire
passer avant chaque livraison :

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -v
```

Les variantes colorées des icônes du SystemTray se régénèrent via :

```bash
.venv/bin/python resources/icons/generate_icon_variants.py
```

## Structure du projet

L'arborescence de référence est décrite dans
[`docs/arborescence.md`](docs/arborescence.md).

## Agents IA

Les instructions de référence pour les agents IA (ZCode) sont dans
[`AGENTS.md`](AGENTS.md) à la racine. Les fichiers de
`.github/instructions/` sont la copie destinée à GitHub Copilot : en cas
d'évolution des règles, synchroniser les deux sources manuellement.
