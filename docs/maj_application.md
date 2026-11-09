# Mise à jour autonome de l'application

> Document de référence de la mécanique de mise à jour de Workstation Tooler
> elle-même. Le moteur des applications gérées est décrit dans
> [`moteur_mise_a_jour.md`](moteur_mise_a_jour.md).

## Principe

La CI du dépôt incrémente le patch de `version.txt` à chaque push sur la
branche principale (workflow `Increment Version`). L'application compare
régulièrement sa version locale (`version.txt`) à la version distante, propose
la mise à jour à l'utilisateur, puis se met à jour elle-même via le script
autonome [`updater.py`](../updater.py) — **exclusivement par des appels HTTP à
la forge** : aucune commande Git n'est exécutée, le poste n'a besoin que d'un
accès réseau.

```
┌────────────┐   compare    ┌──────────────────┐   « Oui »   ┌──────────────────────────┐
│ Scheduler  │─────────────▶│ AppUpdater       │────────────▶│ updater.py (détaché)     │
│ (timer)    │              │ (version.txt     │             │ 1. attend fin du PID     │
└────────────┘              │  local vs distant)│            │ 2. télécharge l'archive   │
                            └──────────────────┘             │ 3. extrait + déploie      │
                                     │ émet                  │ 4. pip install            │
                                     ▼                       │ 5. relance l'application │
                            QMessageBox « Oui / Non /        └──────────────────────────┘
                            Pas aujourd'hui »                 l'application se ferme
                                                               proprement entre 1 et 2
```

## Fournisseurs (`forge.provider`) — tout en HTTP

| | GitHub (défaut) | GitLab |
|---|---|---|
| Version distante | `https://raw.githubusercontent.com/<dépôt>/<branche>/version.txt` | API v4 : `GET <base>/api/v4/projects/<id>/repository/files/version.txt/raw?ref=<branche>` |
| Archive de déploiement | `https://api.github.com/repos/<dépôt>/tarball/<branche>` | `GET <base>/api/v4/projects/<id>/repository/archive.tar.gz?sha=<branche>` |
| Authentification | anonyme (dépôt public) ; jeton optionnel `WORKSTATION_TOOLER_GITHUB_TOKEN` (en-tête `Authorization: Bearer`) si le dépôt redevient privé | token en lecture seule obligatoire, en-tête `PRIVATE-TOKEN` (voir ci-dessous) |

Les deux forges servent une archive `tar.gz` dont le contenu est emballé sous
un dossier racine `<projet>-<sha>` ; l'updater le retire à l'extraction. Une
défaillance (réseau, configuration) est journalisée en warning et dégradée en
« version distante inconnue » : aucune proposition, aucune interruption des
autres fonctions.

### Le token GitLab en lecture seule

Le token réside à un emplacement unique, `core/app_updater.py`, avec **deux
sources possibles** (la première l'emporte) :

1. la variable d'environnement `WORKSTATION_TOOLER_GITLAB_TOKEN` —
   **recommandée** ;
2. la constante `GITLAB_READ_TOKEN` (repli).

> **Dérogation assumée** à la règle « aucun secret en dur » d'AGENTS.md —
> décision du propriétaire du projet. Pour en limiter la portée :
> créer un jeton d'accès **avec le rôle le plus faible donnant accès au dépôt
> en lecture** (ex. rôle *Reporter*, portées `read_api` + `read_repository`,
> sans expiration trop longue). Les paramètres non sensibles (URL, ID projet,
> branche) restent dans `config/settings.yaml`.

> ⚠️ **Dépôt public** : le dépôt GitHub du projet est public — toute valeur
> renseignée dans `GITLAB_READ_TOKEN` serait exposée au monde entier au
> premier push (et les scanners de secrets la révoquent souvent
> automatiquement). Dans ce contexte, **laisser la constante vide** et
> fournir le token via `WORKSTATION_TOOLER_GITLAB_TOKEN` sur chaque poste.

## Forge inaccessible

Une forge (GitHub/GitLab) injoignable est dégradée sans faire planter
l'application ni notifier l'utilisateur : la vérification de version est
journalisée, une icône d'erreur s'affiche dans le SystemTray (sans
notification), et le contrôle est replanifié toutes les
`update.retry_interval_minutes` minutes (3 par défaut) jusqu'à la
première réussite — l'intervalle normal (`update.app_check_interval_minutes`)
est alors restauré.

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
python updater.py <pid> --archive-url URL [--app-dir DIR]
                      [--provider github|gitlab] [--no-relaunch] [--relaunched]
```

Déroulé :

1. **Auto-relocalisation** : le script se copie dans un répertoire temporaire
   et relance **cette copie** détachée. Le déploiement peut ainsi réécrire
   `updater.py` du dépôt sans conflit de fichier en cours d'utilisation
   (verrou Windows notamment).
2. **Attente de l'arrêt** : le PID transmis est celui du **processus principal**
   de l'application (les threads Qt partagent ce PID). Interrogation toutes les
   0,5 s ; passé **15 s**, une boîte de dialogue propose de **forcer l'arrêt**
   (refuser relance une période d'attente de 15 s avant de reposer la question).
3. **Téléchargement HTTP** de l'archive de la nouvelle version (URL fournie
   par l'application, sans jeton ; l'authentification éventuelle passe par les
   en-têtes `PRIVATE-TOKEN` / `Authorization: Bearer`, jamais dans l'URL ni
   les arguments de processus).
4. **Extraction sûre** : filtre `data` de `tarfile` (rejet des chemins
   absolus et des traverses de répertoires) et retrait du dossier racine
   ajouté par les forges.
5. **Déploiement** (voir le manifeste ci-dessous) : recouvrement des fichiers
   de la release, **purge** des fichiers déployés par le précédent
   déploiement mais absents de la nouvelle release, garde contre l'écrasement
   de modifications locales.
6. **Dépendances** : si un `.venv` est présent, `pip install -r requirements.txt`
   (échec non bloquant, journalisé).
7. **Relance** de l'application (`<venv>/python main.py`, détaché) sauf
   `--no-relaunch` / `update.app_auto_restart: false`.

Côté application, l'arrêt suit le chemin normal : `QApplication.quit()` →
sortie de `app.exec()` → `scheduler.stop()` puis `thread_manager.shutdown()`
dans `main()` ; le processus disparaît, l'updater le détecte et poursuit.

### Le manifeste de déploiement `.updater_manifest.json`

Chaque déploiement enregistre, à la racine de l'application, l'empreinte
SHA-256 de chaque fichier déployé. Il sert à :

- **détecter les modifications locales** : un fichier déployé dont le contenu
  local ne correspond plus à l'empreinte enregistrée déclenche un avertissement
  avant écrasement (possibilité d'abandonner) ;
- **purger les retraits amont** : les fichiers présents au manifeste précédent
  mais absents de la nouvelle release sont supprimés (équivalent HTTP du
  `reset --hard`, limité aux fichiers réellement déployés).

Sans manifeste (première mise à jour après l'installation initiale) : simple
recouvrement, sans garde ni purge — les fichiers préexistants non déployés
(`.venv`, `logs/`, `.git`, fichiers personnels) ne sont **jamais** touchés.

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

github:
  repository: "pderouet/Workstation_Tooler"   # utilisé pour les URL GitHub
```

## Prérequis sur le poste

- un **accès HTTP(S)** à la forge depuis le poste ;
- pour GitLab : token en lecture fourni (variable d'environnement
  `WORKSTATION_TOOLER_GITLAB_TOKEN` de préférence) ;
- plus aucun prérequis Git : `git` et un clone propre ne sont plus nécessaires
  (le `.git` d'une installation initiale par clone est simplement préservé et
  ignoré).

## Journalisation et dépannage

| Fichier | Contenu |
|---|---|
| `logs/updater.log` | Journal applicatif horodaté de l'updater (chaque étape). |
| `logs/updater_console.log` | Sorties brutes (tracebacks non interceptés) de l'updater et de l'application relancée. |

Points de contrôle en cas d'échec : section `forge.*` renseignée (provider,
branche, ID projet, `github.repository`), token GitLab fourni si applicable,
URL d'archive joignable depuis le poste (test navigateur/curl), journal
`logs/updater.log`.

## Sécurité

- Les archives sont extraites avec le filtre `data` de `tarfile` : chemins
  absolus et traverses de répertoires rejetés.
- Les jetons ne figurent ni dans les URL, ni dans les arguments de processus
  (en-têtes HTTP uniquement), ni dans les journaux.
- La purge du déploiement ne peut supprimer que des fichiers précédemment
  déployés par l'updater (manifeste) — jamais `.venv`, `logs/`, `.git` ni les
  fichiers personnels.
- Aucune exception n'est avalée silencieusement : journal + notification
  utilisateur en cas d'échec.
