# Mise à jour autonome de l'application

> Document de référence de la mécanique de mise à jour de Workstation Tooler
> elle-même. Le moteur des applications gérées est décrit dans
> [`moteur_mise_a_jour.md`](moteur_mise_a_jour.md).

## Principe

La CI du dépôt incrémente le patch de `version.txt` à chaque push sur la
branche principale (workflow `Increment Version`). L'application compare
régulièrement sa version locale (`version.txt`) à la version distante, propose
la mise à jour à l'utilisateur, puis se met à jour elle-même via le script
autonome [`updater.py`](../updater.py) et Git.

```
┌────────────┐   compare    ┌──────────────────┐   « Oui »   ┌─────────────────────────┐
│ Scheduler  │─────────────▶│ AppUpdater       │────────────▶│ updater.py (détaché)    │
│ (timer)    │              │ (version.txt     │             │ 1. attend fin du PID    │
└────────────┘              │  local vs distant)│            │ 2. git fetch + reset    │
                            └──────────────────┘             │ 3. pip install          │
                                     │ émet                  │ 4. relance l'application│
                                     ▼                       └─────────────────────────┘
                            QMessageBox « Oui / Non /
                            Pas aujourd'hui »                 l'application se ferme
                                                               proprement entre 2 et 3
```

## Fournisseurs de version (`forge.provider`)

| | GitHub (défaut) | GitLab |
|---|---|---|
| Version distante | `git fetch origin <branche>` puis `git show FETCH_HEAD:version.txt` dans le clone local | API v4 : `GET <base_url>/api/v4/projects/<id>/repository/files/version.txt/raw?ref=<branche>` avec en-tête `PRIVATE-TOKEN` |
| Authentification | credentials Git existants du clone (dépôt privé compris) | token en lecture seule (voir ci-dessous) |
| Déploiement (`updater.py`) | `git fetch origin <branche>` | même fetch, token injecté via `git -c http.extraheader="Authorization: Bearer <token>"` |

Une défaillance (réseau, Git, configuration) est journalisée en warning et
dégradée en « version distante inconnue » : aucune proposition, aucune
interruption des autres fonctions.

### Le token GitLab en lecture seule

Le token est **stocké dans le code**, à un emplacement unique :
`GITLAB_READ_TOKEN` dans [`core/app_updater.py`](../core/app_updater.py)
(l'updater l'importe depuis là ; il n'existe qu'une seule définition).

> **Dérogation assumée** à la règle « aucun secret en dur » d'AGENTS.md —
> décision du propriétaire du projet. Pour en limiter la portée :
> créer un jeton d'accès **avec le rôle le plus faible donnant accès au dépôt
> en lecture** (ex. rôle *Reporter*, portées `read_api` + `read_repository`,
> sans expiration trop longue). Les paramètres non sensibles (URL, ID projet,
> branche) restent dans `config/settings.yaml`.

## La notification à trois choix

Déclenchée automatiquement par la vérification périodique
(`update.app_check_interval_minutes`, plus immédiatement au démarrage si
`update.check_on_startup`), ou manuellement via le menu
« Mise à jour Application » (ce dernier **ignore le report** : changer d'avis
sans redémarrer reste possible).

| Choix | Effet |
|---|---|
| **Oui** | Lance l'updater, affiche « Mise à jour lancée : fermeture… », puis ferme proprement l'application 1,5 s après. |
| **Non** | Ferme la notification ; la question sera reposée au prochain contrôle. |
| **Pas aujourd'hui** | Plus aucune proposition **pour cette exécution du programme**. Le report est une simple mémoire vive : au redémarrage de l'application, la question est reposée. |

Une version locale plus récente que la distante ne déclenche **jamais** de
rétrogradage (comparaison sémantique par tri naturel).

## `updater.py` : le script autonome

Utilisation (lancée par l'application, mais fonctionnelle seule) :

```
python updater.py <pid> [--app-dir DIR] [--provider github|gitlab]
                      [--branch BRANCHE] [--no-relaunch] [--relaunched]
```

Déroulé :

1. **Auto-relocalisation** : le script se copie dans un répertoire temporaire
   et relance **cette copie** détachée. Le `git reset --hard` peut ainsi
   réécrire `updater.py` du dépôt sans conflit de fichier en cours
   d'utilisation (verrou Windows notamment).
2. **Attente de l'arrêt** : le PID transmis est celui du **processus principal**
   de l'application (les threads Qt partagent ce PID). Interrogation toutes les
   0,5 s ; passé **15 s**, une boîte de dialogue propose de **forcer l'arrêt**
   (refuser relance une période d'attente de 15 s avant de reposer la question).
3. **Garde-fou** : si le dépôt contient des modifications locales, un
   avertissement propose d'abandonner (`git reset --hard` les écraserait).
4. **Déploiement** : `git fetch origin <branche>` puis
   `git reset --hard FETCH_HEAD` (commandes en liste, sans shell).
5. **Dépendances** : si un `.venv` est présent, `pip install -r requirements.txt`
   (échec non bloquant, journalisé).
6. **Relance** de l'application (`<venv>/python main.py`, détaché) sauf
   `--no-relaunch` / `update.app_auto_restart: false`.

Côté application, l'arrêt suit le chemin normal : `QApplication.quit()` →
sortie de `app.exec()` → `scheduler.stop()` puis `thread_manager.shutdown()`
dans `main()` ; le processus disparaît, l'updater le détecte et poursuit.

## Configuration (`config/settings.yaml`)

```yaml
update:
  app_check_interval_minutes: 240   # fréquence de vérification
  check_on_startup: true
  app_auto_restart: true            # relance après mise à jour

forge:
  provider: github                  # github | gitlab
  github:
    branch: main
  gitlab:
    base_url: "https://gitlab.com"  # URL de l'instance
    project_id: ""                  # ID numérique (page Projet > Détails)
    branch: main
```

## Prérequis sur le poste

- l'application est déployée sous forme de **clone Git** de la forge ;
- `git` est disponible dans le `PATH` ;
- le clone peut *fetcher* : credentials Git configurés (GitHub) ou token GitLab
  renseigné dans le code (GitLab) ;
- le dépôt de déploiement reste **propre** (aucune modification locale) : le
  garde-fou de l'étape 3 protège sinon, au prix d'une question à l'utilisateur.

## Journalisation et dépannage

| Fichier | Contenu |
|---|---|
| `logs/updater.log` | Journal applicatif horodaté de l'updater (chaque étape). |
| `logs/updater_console.log` | Sorties brutes (tracebacks non interceptés) de l'updater et de l'application relancée. |

Points de contrôle en cas d'échec : section `forge.*` renseignée (provider,
branche, ID projet), token GitLab renseigné, `git fetch` fonctionnel
manuellement dans le dépôt, dépôt propre.

## Sécurité

- Toutes les commandes sont exécutées en liste d'arguments, **sans shell**.
- Le token GitLab n'apparaît ni dans les arguments de processus (en-tête HTTP
  `Authorization: Bearer` via `git -c http.extraheader`), ni dans l'URL, ni
  dans la configuration Git du dépôt ; il n'est jamais journalisé.
- Aucune exception n'est avalée silencieusement : journal + notification
  utilisateur en cas d'échec.
