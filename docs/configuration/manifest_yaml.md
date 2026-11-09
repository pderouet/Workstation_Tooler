# `manifest.yaml` — fichiers d'une version du catalogue

[← Sommaire du dossier](README.md) · [← Précédent : `app.yaml`](app_yaml.md) · [Suivant : `settings.yaml` →](settings_yaml.md)

> Référence du manifest décrivant les fichiers à déployer pour une version
> donnée d'une application. Vue d'ensemble :
> [`moteur_mise_a_jour.md`](../moteur_mise_a_jour.md). Sommaire du dossier :
> [`README.md`](README.md).

## Emplacement

```
<racine du partage>/
└── <application>/
    └── <version>/              ← le nom du dossier EST la version
        ├── manifest.yaml       ← ce fichier
        └── <fichiers à déployer>
```

Chaque sous-dossier d'une application contenant un `manifest.yaml` est une
version disponible. La version « la plus récente » (cible des mises à jour)
est déterminée par **tri naturel** des noms de dossiers : préfixe `v` ignoré,
composants numériques comparés numériquement (`9.1.0700` > `9.1.500`,
`v0.50.10` > `v0.50.9`), suffixe de pré-version avant la version finale
(`4.3.2-rc1` < `4.3.2`).

Un dossier sans `manifest.yaml` n'est pas une version : il est simplement
ignoré (pratique pour préparer une version en cours de téléversement).

## Schéma complet

```yaml
version: "<version>"            # optionnel
files:                          # REQUIS (liste non vide)
  - source: <fichier>           # requis
    action: <copy|decompress|ensure_content>   # requis
    target: <chemin cible>      # requis
    mode: "<octal>"             # optionnel (utile pour copy)
```

### Clés de premier niveau

| Clé | Type | Requis | Défaut | Description |
|---|---|---|---|---|
| `version` | chaîne | non | nom du dossier | Si renseigné, **doit être égal** au nom du dossier de version, sinon le manifest est rejeté. |
| `files` | liste de sections | **oui** | — | Actions de fichiers, **exécutées dans l'ordre de déclaration**. Une liste vide est refusée. |

### Entrées de `files`

| Clé | Type | Requis | Description |
|---|---|---|---|
| `source` | chaîne | **oui** | Chemin du fichier **relatif au dossier de la version**. Interdits : chemin absolu (`/...`, `\...`) et traverses (`..`) — le manifest est rejeté. |
| `action` | chaîne | **oui** | Mot-clé parmi `copy`, `decompress`, `ensure_content` (énumération fermée, toute autre valeur est une erreur). |
| `target` | chaîne | **oui** | Chemin local cible, avec expansion `~` et variables — voir « Cibles et portabilité » ci-dessous. |
| `mode` | chaîne | non | Permissions **octales** sous forme de chaîne (ex. `"755"`), appliquées après copie (`copy` uniquement). Toute autre forme est refusée. |

## Les trois actions

### `copy` — copier un fichier

Copie la source vers `target` (fichier), en créant les répertoires parents.
`mode` applique des permissions après copie (ex. `"755"` pour un binaire).
Sous Windows, `mode` ne pilote que l'attribut lecture seule : le bit
exécutable est sans effet (aucun crash).

```yaml
- source: vim
  action: copy
  target: "~/.local/bin/vim"
  mode: "755"
```

### `decompress` — extraire une archive

Extrait l'archive vers le répertoire `target` (créé au besoin). Formats
gérés : `.zip`, `.tar.gz`/`.tgz`, `.tar.bz2`/`.tbz2`, `.tar.xz`/`.txz`,
`.tar`, `.gz` (fichier simple, sans conteneur tar). **Le format 7z n'est pas
géré** — reconditionner en zip si besoin (ou poser l'archive par `copy`).

L'extraction est durcie :
- `tarfile` avec filtre `data` : chemins absolus, traverses `..` et liens
  dangereux refusés avant extraction ;
- les membres `.zip` hors de la cible sont vérifiés de la même manière.

```yaml
- source: k9s_Linux_amd64.tar.gz
  action: decompress
  target: "~/.local/share/k9s/1.0.0"
```

### `ensure_content` — garantir la présence d'un contenu

Garantit que le contenu du fragment source est présent dans le fichier cible
(texte UTF-8) :

| État de la cible | Résultat |
|---|---|
| absente | créée (parents inclus) avec le contenu du fragment |
| contient déjà le fragment | **aucune modification** (idempotent) |
| ne le contient pas | fragment ajouté en fin de fichier, précédé d'un passage à la ligne si nécessaire |

C'est l'action à utiliser pour les fragments de configuration partagés
(profils, vimrc...) : réappliquée autant de fois que nécessaire sans
duplication (menu « Réappliquer la config », action
`reconfigure_application` du moteur).

```yaml
- source: vimrc.fragment
  action: ensure_content
  target: "~/.vimrc"
```

## Cibles et portabilité (`target`)

Les cibles sont développées avec `~` et les variables d'environnement
**selon la plateforme du poste** :

| Écriture | Linux | Windows |
|---|---|---|
| `~/outil` | `/home/<login>/outil` | `C:\Users\<login>\outil` |
| `${HOME}/outil` | développé | **littéral** (non supporté) |
| `%APPDATA%\outil` | littéral | développé |

**Recommandation** : utiliser `~` pour tout ce qui est relatif au profil
utilisateur (portable). Réserver `%VAR%` aux manifests spécifiquement Windows.
Cas limite : si `HOME` est défini dans l'environnement Windows (certaines
installations de Git Bash), il prime sur `USERPROFILE`.

## Exemple complet

```yaml
# manifest.yaml de <racine>/vim/9.1.0700/
# Prérequis : les trois fichiers sources sont posés dans ce dossier de version.
version: "9.1.0700"
files:
  - source: vim-9.1.0700.tar.gz
    action: decompress
    target: "~/.local/share/vim"

  - source: vim-startup.bat
    action: copy
    target: "~/.local/bin/vim-startup"
    mode: "755"

  - source: vimrc.fragment
    action: ensure_content
    target: "~/.vimrc"
```

> **Important** : chaque `source` est recopiée du partage vers un répertoire
> temporaire local, puis l'action s'applique. Une source est donc toujours un
> fichier **posé dans le dossier de version du partage** — jamais le résultat
> d'une action précédente du même manifest.

## Règles de validation

- lecture avec `yaml.safe_load` uniquement ; racine = section ;
- **toute clé inconnue** (racine ou entrée `files`) est une erreur ;
- `files` doit être une liste **non vide** de sections ;
- `action` hors énumération, `source` absolue ou avec `..`, `mode` non octal :
  manifest rejeté ;
- `version`, si présent, doit être égal au nom du dossier.

## Conséquences d'un manifest invalide

L'application concernée est **ignorée et journalisée** (message explicite dans
`logs/workstation_tooler.log` et lors du chargement du catalogue) : elle
n'apparaît pas dans le menu et n'est pas vérifiée. Les autres applications ne
sont pas affectées. Corriger le YAML puis relancer « Vérifier les mises à
jour » (ou attendre le cycle suivant) pour qu'elle soit de nouveau prise en
compte.
