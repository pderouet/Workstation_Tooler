# Workstation Tooler

Application Python (PyQt6) résidant dans le SystemTray, qui gère la mise à jour
d'outils binaires et logiciels sur les postes de travail : OpenShift CLI (`oc`),
plugin OpenShift CloudNativePG, Vim, DBeaver, FreeLens, K9s et le déploiement de
la configuration PowerShell du poste.

L'architecture repose sur un socle de singletons (`core/` : Logger, EventBus,
ThreadManager, ConfigLoader, ErrorHandler, Scheduler, AppUpdater) et sur un
**moteur de mise à jour** (`engine/`) piloté par un **catalogue hébergé sur un
chemin réseau unique** (partage SMB) : chaque application gérée est décrite par
un `app.yaml` et chaque version par un `manifest.yaml` (actions `copy`,
`decompress`, `ensure_content`). Ajouter un outil ne demande **aucun code
local** — voir [`docs/moteur_mise_a_jour.md`](docs/moteur_mise_a_jour.md).
L'application sait également **se mettre à jour elle-même** : la version
(`version.txt`, incrémentée par la CI à chaque push) est comparée à la forge
(GitHub ou GitLab), une notification à trois choix est proposée et le script
autonome `updater.py` déploie la nouvelle version via Git puis relance
l'application — voir [`docs/maj_application.md`](docs/maj_application.md).
L'interface se limite à une icône SystemTray (`ui/`) dont l'état visuel reflète
l'activité : vert (OK), bleu (information / mise à jour disponible), jaune
(opération en cours).

## Prérequis

- Python 3.14 ou supérieur
- Un environnement de bureau avec SystemTray (GNOME : extension AppIndicator, etc.)
- Un chemin réseau hébergeant le catalogue (`repository.uri`), ex. un partage SMB

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
notamment le niveau de log, les intervalles de vérification et le chemin réseau
du catalogue (`repository.uri` — un chemin `file://` est accepté pour développer
sans partage). Par défaut (`repository.auth: session`), l'accès au partage SMB
utilise la session de l'utilisateur du poste (poste joint au domaine Active
Directory) ; un mot de passe n'est nécessaire qu'en mode `auth: credentials`,
via la variable d'environnement `WORKSTATION_TOOLER_SMB_PASSWORD`. Un exemple
de catalogue est disponible dans [`examples/partage/`](examples/partage/README.md).

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

### Documentation

| Document | Contenu |
|---|---|
| [`docs/arborescence.md`](docs/arborescence.md) | Arborescence de référence du dépôt |
| [`docs/moteur_mise_a_jour.md`](docs/moteur_mise_a_jour.md) | Moteur des applications gérées (vue d'ensemble) |
| [`docs/architecture_technique.md`](docs/architecture_technique.md) | **Architecture** : couches, singletons, signaux de l'EventBus, modèle de threading |
| [`docs/maj_application.md`](docs/maj_application.md) | Mise à jour autonome de l'application (forge, updater.py) |
| [`docs/exploitation_catalogue.md`](docs/exploitation_catalogue.md) | **Guide administrateur du partage** : publier, tester, retirer une version |
| [`docs/deploiement_poste.md`](docs/deploiement_poste.md) | **Installation d'un poste** : installation initiale, autostart, Windows, désinstallation |
| [`docs/configuration/README.md`](docs/configuration/README.md) | **Références YAML** : sommaire et navigation — [`app_yaml.md`](docs/configuration/app_yaml.md), [`manifest_yaml.md`](docs/configuration/manifest_yaml.md), [`settings_yaml.md`](docs/configuration/settings_yaml.md) |
| [`examples/partage/README.md`](examples/partage/README.md) | Catalogue d'exemple à recopier sur un partage de test |

## Agents IA

Les instructions de référence pour les agents IA (ZCode) sont dans
[`AGENTS.md`](AGENTS.md) à la racine. Les fichiers de
`.github/instructions/` sont la copie destinée à GitHub Copilot : en cas
d'évolution des règles, synchroniser les deux sources manuellement.
