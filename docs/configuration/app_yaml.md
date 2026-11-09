# `app.yaml` — métadonnées d'une application du catalogue

> Référence du fichier décrivant une application gérée dans le catalogue
> distant. Vue d'ensemble : [`moteur_mise_a_jour.md`](../moteur_mise_a_jour.md).
> Sommaire du dossier : [`README.md`](README.md).

## Emplacement

```
<racine du partage>/
└── <application>/          ← le nom du dossier EST le nom de l'application
    └── app.yaml            ← ce fichier
```

Un dossier racine du catalogue contenant un `app.yaml` valide est découvert
comme application. Un `app.yaml` absent, illisible ou invalide fait **ignorer
et journaliser** l'application (elle n'apparaît ni dans le menu ni dans les
vérifications), sans impacter les autres.

## Schéma complet

```yaml
application: <nom>              # optionnel
display_name: <libellé>         # optionnel
enabled: <booléen>              # optionnel (défaut : true)
version_detection:              # REQUIS (section)
  binary: <binaire>             # requis
  pattern: <regex>              # requis
  args: [<argument>, ...]       # optionnel (défaut : [])
  fallback_binary: <binaire>    # optionnel (défaut : "")
  timeout_seconds: <entier>     # optionnel (défaut : 5)
```

### Clés de premier niveau

| Clé | Type | Requis | Défaut | Description |
|---|---|---|---|---|
| `application` | chaîne | non | nom du dossier | Si renseigné, **doit être égal** au nom du dossier contenant le fichier, sinon le manifest est rejeté (garde anti-erreur de copie). |
| `display_name` | chaîne | non | nom du dossier mis en forme | Libellé affiché dans le menu du SystemTray (ex. `openshift_cnpg` → `Openshift Cnpg`). Le renseigner pour un libellé soigné (`OpenShift CNPG`). |
| `enabled` | booléen | non | `true` | `false` : l'application reste connue du catalogue mais est ignorée par le moteur (ni vérifiée, ni affichée, ni mise à jour). |
| `version_detection` | section | **oui** | — | Déclaration de la commande détectant la version installée sur le poste. |

### Section `version_detection`

| Clé | Type | Requis | Défaut | Description |
|---|---|---|---|---|
| `binary` | chaîne | **oui** | — | Binaire à exécuter, résolu via le `PATH` du poste. |
| `pattern` | chaîne | **oui** | — | Expression régulière appliquée à la **sortie standard**. La version extraite est le **premier groupe capturant**, ou la correspondance entière si le motif n'en contient pas. La regex est compilée au chargement : un motif invalide rejette l'application. |
| `args` | liste de chaînes | non | `[]` | Arguments passés au binaire (ex. `["--version"]`). |
| `fallback_binary` | chaîne | non | `""` | Binaire de substitution si `binary` est introuvable dans le `PATH` (ex. `powershell` pour `pwsh`). Sous Windows, la recherche s'appuie sur `PATHEXT` : `vim` trouve `vim.exe`. |
| `timeout_seconds` | entier > 0 | non | `5` | Délai maximal d'exécution de la commande de détection. |

## Sémantique de la détection

Pour chaque vérification (au démarrage et à chaque cycle du `Scheduler`) :

1. `binary` est résolu dans le `PATH` ; sinon `fallback_binary` ;
2. la commande est exécutée **sans interpréteur de commandes** (liste
   d'arguments), avec `timeout_seconds` ;
3. `pattern` est recherché dans la sortie standard ; le premier groupe
   capturant (ou toute la correspondance) devient la version ;
4. la version est comparée à la plus récente du catalogue par **tri naturel**
   (`v0.50.0` < `v0.50.10`, préfixe `v` ignoré) : plus récent n'est jamais
   rétrogradé.

Tout échec (binaire introuvable, commande en erreur ou expirée, motif sans
correspondance) est assimilé à « **non installé** » → une mise à jour
(installation) est proposée. Une erreur ne bloque jamais les autres
applications.

## Exemples

### Complet (trois actions déclarées côté manifest, détection standard)

```yaml
application: vim
display_name: Vim
enabled: true
version_detection:
  binary: vim
  args: ["--version"]
  pattern: 'Vi IMproved (\S+)'
  timeout_seconds: 5
```

### Avec binaire de repli (multiplateforme PowerShell)

```yaml
application: powershell_config
display_name: Configuration PowerShell
enabled: true
version_detection:
  binary: pwsh
  fallback_binary: powershell
  args: ["-NoLogo", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"]
  pattern: '(\d+\.\d+\.\d+)'
```

### Minimal (seules les clés requises)

```yaml
version_detection:
  binary: k9s
  pattern: '(v[0-9.]+)'
```

## Règles de validation

- lecture avec `yaml.safe_load` uniquement ; la racine doit être une section ;
- **toute clé inconnue** (à la racine ou dans `version_detection`) est une
  erreur → l'application est ignorée avec un message de log explicite ;
- `pattern` doit compiler comme regex Python ;
- `args` doit être une liste de chaînes ; `timeout_seconds` un entier
  strictement positif ;
- la valeur de `application`, si présente, doit être égale au nom du dossier.

## Conseils

- **Motif d'extraction** : préférer un groupe capturant précis
  (`'Client Version:\s*(\S+)'` pour `oc`) à un motif large.
- **Cibles des manifests** : voir [`manifest_yaml.md`](manifest_yaml.md) pour
  la portabilité des chemins (`~` vs `%VAR%`) entre Linux et Windows.
- Pour tester une application sans la déployer réellement : la désactiver via
  `enabled: false` plutôt que de supprimer son dossier.
