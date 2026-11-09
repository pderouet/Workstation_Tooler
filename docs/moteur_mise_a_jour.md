# Moteur de mise à jour piloté par un catalogue distant

> Document de référence du fonctionnement de la mise à jour des applications.
> L'arborescence du dépôt est décrite dans [`arborescence.md`](arborescence.md).

## Principe

Workstation Tooler ne gère plus un module Python par outil : un **moteur
unique** (`engine/`) découvre les applications, leurs versions et les fichiers
à déployer depuis un **catalogue hébergé sur un chemin réseau unique** (partage
SMB), défini dans la configuration locale (`repository.uri` de
`config/settings.yaml`).

Conséquence directe : **ajouter un nouvel outil ne demande aucun code local**.
Il suffit de déposer sur le partage :

- un dossier au nom de l'application, contenant un `app.yaml` (métadonnées) ;
- un dossier par version, contenant un `manifest.yaml` et les fichiers à
  déployer.

Un dossier d'exemple complet et commenté est fourni dans
[`examples/partage/`](../examples/partage/README.md).

> 📘 **Références détaillées** : ce document donne la vue d'ensemble. Les
> schémas complets, clés par clé, sont dans le dossier
> [`configuration/`](configuration/README.md) :
> [`app_yaml.md`](configuration/app_yaml.md) (métadonnées + détection),
> [`manifest_yaml.md`](configuration/manifest_yaml.md) (fichiers + actions),
> [`settings_yaml.md`](configuration/settings_yaml.md) (configuration locale).

## Arborescence du catalogue

```
<racine du partage>/                 ← repository.uri (ex. smb://localhost/Workstation_Tooler)
├── vim/                             ← une application = un dossier
│   ├── app.yaml                     ← métadonnées + détection de version installée
│   ├── 9.1.0500/                    ← une version = un dossier (nom = version)
│   │   ├── manifest.yaml            ← fichiers de cette version + actions
│   │   ├── vim-9.1.0500.tar.gz
│   │   └── vimrc.fragment
│   └── 9.1.0700/
│       ├── manifest.yaml
│       └── vim-9.1.0700.tar.gz
└── k9s/
    ├── app.yaml
    └── v0.50.0/
        ├── manifest.yaml
        └── k9s_Linux_amd64.tar.gz
```

Règles de découverte :

- chaque dossier racine contenant un `app.yaml` est une application ; un
  dossier sans `app.yaml` (ou avec un `app.yaml` invalide) est **ignoré et
  journalisé**, sans impact sur les autres applications ;
- chaque sous-dossier d'une application contenant un `manifest.yaml` est une
  version ; les autres sous-dossiers sont ignorés ;
- les champs `application` (app.yaml) et `version` (manifest.yaml) sont
  optionnels mais, s'ils sont renseignés, doivent être égaux au nom du dossier
  qui les contient ;
- la version « la plus récente » est déterminée par **tri naturel** des noms de
  dossiers (`v0.50.0` < `v0.50.10`, préfixe `v` ignoré, `4.3.2-rc1` < `4.3.2`).

## Schéma des manifests

### `app.yaml` — métadonnées de l'application

```yaml
application: vim            # optionnel, doit égal le nom du dossier
display_name: Vim           # libellé affiché dans le menu du SystemTray
enabled: true               # false : application connue mais ignorée
version_detection:          # commande détectant la version installée
  binary: vim               # binaire résolu via le PATH
  fallback_binary: ""       # optionnel : binaire de substitution (ex. powershell pour pwsh)
  args: ["--version"]       # arguments de la commande
  pattern: 'Vi IMproved (\S+)'   # regex sur la sortie standard
  timeout_seconds: 5        # optionnel (défaut 5)
```

Le premier groupe capturant du `pattern` (ou la correspondance entière s'il
n'y a pas de groupe) fournit le numéro de version installée. Un binaire
introuvable, une commande en échec ou un motif sans correspondance valent
« non installé » — une mise à jour (installation) est alors proposée.

### `manifest.yaml` — fichiers d'une version

```yaml
version: "9.1.0700"         # optionnel, doit égal le nom du dossier
files:
  - source: vim-9.1.0700.tar.gz   # relatif au dossier de la version (sans ..)
    action: decompress
    target: "~/.local/share/vim"
  - source: vim
    action: copy
    target: "~/.local/bin/vim"
    mode: "755"             # optionnel : permissions octales après copie
  - source: vimrc.fragment
    action: ensure_content
    target: "~/.vimrc"
```

Les entrées `files` sont exécutées **dans l'ordre de déclaration**. Chaque
`source` est d'abord recopiée dans un répertoire temporaire local, puis
l'action s'applique au système de fichiers. Les chemins `target` acceptent
l'expansion `~` et `${VAR}` (ex. `${HOME}/bin`).

### Mots-clés d'action

| Action | Sémantique |
|---|---|
| `copy` | Copie le fichier source vers `target` (répertoires parents créés, `mode` octal optionnel appliqué après copie). |
| `decompress` | Décompresse l'archive source vers le répertoire `target`. Formats : `.zip`, `.tar.gz`/`.tgz`, `.tar.bz2`/`.tbz2`, `.tar.xz`/`.txz`, `.tar`, `.gz` (fichier simple). Le **7z n'est pas géré**. |
| `ensure_content` | Garantit que le contenu du fragment source est présent dans le fichier `target` : cible absente → création avec le fragment ; contenu déjà présent → aucune modification ; sinon → ajout en fin de fichier, précédé d'un passage à la ligne. Idempotent par construction. |

## Flux applicatifs

### Chargement du catalogue (démarrage)

`main.py` construit le `UpdateEngine` sur le backend défini par `repository.uri`,
puis lance le chargement en tâche de fond. Le catalogue est publié à l'UI via
le signal `catalog_loaded` de l'`EventBus` (liste `{"name", "display_name"}`),
et le menu du SystemTray se reconstruit dynamiquement (les manifests de
versions, eux, sont lus à la demande, avec cache mémoire).

### Vérification des mises à jour

Déclenchée par le `Scheduler` (intervalle `update.check_interval_minutes`,
plus immédiatement au démarrage si `update.check_on_startup`) ou par le menu
« Vérifier les mises à jour ». Pour chaque application active : exécution de la
commande de détection, comparaison au tri naturel avec la version la plus
récente du catalogue (un poste **plus récent** que le catalogue n'est pas
rétrogradé). Les mises à jour détectées sont publiées en **un seul événement
groupé** (`catalog_updates_available`) : l'utilisateur voit une notification
unique listant tous les logiciels concernés, pas une notification par logiciel.

### Partage réseau inaccessible

Un partage injoignable ne fait **jamais planter l'application** : la session
SMB n'est établie qu'au premier accès (backend paresseux) et l'échec remonte
aux tâches de fond. Le `Scheduler` suit la disponibilité de la ressource :

- à la première détection d'indisponibilité : icône d'erreur du SystemTray
  (`app_icon_err.ico`) et replanification du contrôle toutes les
  `update.retry_interval_minutes` minutes (3 par défaut) — **sans
  notification** (l'état est visible dans l'icône et les journaux) ;
- dès la première réussite : retour à l'intervalle configuré et à l'état
  d'icône normal (les transitions seules sont notifiées, pas chaque contrôle).

### Mise à jour

« Tout mettre à jour » ou « Mettre à jour > `<application>` » : lecture du
manifest de la version cible, téléchargement de chaque source, exécution des
actions, progression rapportée par fichier via `progress_callback`. Les
échecs remontent au `ErrorHandler` (notification + log), conformément aux
règles du projet.

### Réapplication de configuration

« Réappliquer la config > `<application>` » n'exécute que les actions
`ensure_content` du manifest — sur la version installée détectée si elle
existe au catalogue, sinon la plus récente. C'est l'opération à utiliser après
une modification d'un fragment partagé (profil PowerShell, vimrc, etc.).

## Configuration locale

`config/settings.yaml` :

```yaml
repository:
  uri: "smb://SERVEUR.DOMAINE/Workstation_Tooler"   # chemin réseau unique du catalogue
  auth: "session"        # session | credentials | guest (voir ci-dessous)
  username: ""           # modes credentials et guest uniquement
  domain: ""
  timeout_seconds: 30
```

Le schéma `file://` (ou un chemin nu) est également accepté pour développement
et tests : le même moteur s'exécute alors sur un répertoire local.

### Authentification

La clé `repository.auth` sélectionne le mode d'authentification SMB :

- **`session` (défaut, production)** : l'accès utilise la **session de
  l'utilisateur du poste** — sur un poste Windows joint au domaine Active
  Directory, smbprotocol négocie via SSPI (`Negotiate` : Kerberos puis NTLM)
  avec les identifiants de la session, sans mot de passe ni compte dédié.
  Prérequis : l'utilisateur (ou son groupe AD) doit avoir les droits de
  **lecture** sur le partage. `username`/`domain` doivent rester vides (sinon
  erreur au démarrage) et la signature des messages reste exigée. En
  développement Linux (sans Kerberos local), ce mode ne peut pas
  s'authentifier : préférer `file://` ou `guest` ;
- **`credentials`** : compte explicite — renseigner `repository.username`
  (et `repository.domain` le cas échéant) et fournir le mot de passe via la
  variable d'environnement `WORKSTATION_TOOLER_SMB_PASSWORD` (jamais dans la
  configuration, exigée au démarrage dans ce mode) — signature exigée ;
- **`guest`** (développement/test) : partage public — la bibliothèque SMB
  (`smbprotocol`, module `smbclient`) ne sait pas établir de session anonyme
  pure : mapper les requêtes invité côté serveur Samba (`map to guest = Bad
  User` dans `[global]` de `smb.conf`) et renseigner `repository.username`
  (ex. `guest`). Une session invité ne pouvant ni signer ni chiffrer les
  messages SMB, le backend lève alors automatiquement l'exigence de signature
  et la vérification *secure negotiate* (sinon le serveur rejette la session
  avec « guest which does not support encryption or signing »).

Un refus d'authentification en mode `session` (poste hors domaine, droits AD
manquants) se manifeste comme un partage injoignable : état dégradé (icône
d'erreur, reprise toutes les `update.retry_interval_minutes` minutes), sans
blocage du démarrage.

## Sécurité

Le contenu du catalogue pilote des écritures sur le poste : le partage doit
être **administré et de confiance** (comme tout outil de déploiement). Mesures
appliquées par le moteur :

- parsing strict (`yaml.safe_load`, schéma fermé : toute clé inconnue est
  refusée) ;
- sources limitées à des chemins relatifs sans `..` ;
- extraction d'archives durcie : filtre `data` de `tarfile` (refuse chemins
  absolus et traverses), vérification équivalente des membres zip ;
- commandes de détection exécutées sans interpréteur de commandes (liste
  d'arguments), avec délai maximal ;
- aucun secret stocké dans les fichiers de configuration.

## Cartographie du code (`engine/`)

| Module | Rôle |
|---|---|
| `models.py` | Dataclasses (`AppMetadata`, `VersionManifest`, `FileAction`, `Catalog`…) et parsing/validation stricts des YAML. |
| `version.py` | Comparaison de versions par tri naturel, résolution « plus récente ». |
| `storage.py` | Protocole `StorageBackend` ; backends SMB (`smbprotocol`) et local (`file://`) ; fabrique selon le schéma d'URI. |
| `repository.py` | Vue typée du catalogue : applications, versions, manifests, récupération de fichiers. |
| `catalog.py` | Chargement résilient du catalogue (application invalide = ignorée et journalisée). |
| `detection.py` | Détection de version installée à partir de la déclaration `app.yaml`. |
| `actions.py` | Exécuteurs `copy` / `decompress` / `ensure_content` (expansion `~`/`${VAR}`, chmod, extraction sécurisée). |
| `update_engine.py` | Orchestrateur : catalogue, vérifications, mises à jour, reconfiguration, wrappers `start_*` déléguant au `ThreadManager`. |
