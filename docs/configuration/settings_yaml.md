# `settings.yaml` — configuration locale de l'application

[← Sommaire du dossier](README.md) · [← Précédent : `manifest.yaml`](manifest_yaml.md)

> Référence du fichier `config/settings.yaml` présent sur **chaque poste**
> (contrairement au catalogue distant, voir [`README.md`](README.md)).
> Lecture au démarrage par [`core/config_loader.py`](../../core/config_loader.py)
> (singleton `ConfigLoader`, accès par clés à points : `repository.uri`, etc.).

## Fichier complet annoté

```yaml
logging:
  level: INFO                        # DEBUG, INFO, WARNING, ERROR, CRITICAL

update:
  check_interval_minutes: 60         # cycle de vérification des applications
  app_check_interval_minutes: 240    # cycle de vérification de l'application elle-même
  retry_interval_minutes: 3          # reprise accélérée si une ressource réseau est inaccessible
  check_on_startup: true             # vérifier immédiatement au démarrage
  app_auto_restart: true             # relancer l'application après sa propre mise à jour

forge:
  provider: github                   # github | gitlab : forge suivie pour la mise à jour de l'app
  github:
    branch: main                     # branche suivie (version + archive de déploiement)
  gitlab:
    base_url: "https://gitlab.com"   # URL de l'instance (auto-hébergée ou gitlab.com)
    project_id: ""                   # ID numérique du projet (page Projet > Détails)
    branch: main

repository:
  uri: "smb://localhost/Workstation_Tooler"   # chemin réseau unique du catalogue
  username: "guest"                  # compte SMB (voir « Secrets »)
  domain: ""                         # domaine NTLM optionnel
  timeout_seconds: 30                # délai maximal de connexion SMB

github:
  repository: "pderouet/Workstation_Tooler"   # dépôt source (URL GitHub)

ui:
  show_notifications: true
```

## Sections et clés

### `logging`

| Clé | Type | Défaut | Description |
|---|---|---|---|
| `level` | chaîne | `INFO` | Niveau minimal des journaux console (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). La sortie console est colorée par niveau ; les variables d'environnement `NO_COLOR` (désactive) et `FORCE_COLOR` (force) sont respectées. |
| `file` | chaîne | — | Chemin du fichier de journal (relatif à la racine du projet, ou absolu). Créé au premier lancement avec ses répertoires parents — garantit des journaux persistants même sans console (`pythonw` sous Windows). Vide ou absent : console seule. |

### `update` — planification et comportement des mises à jour

| Clé | Type | Défaut | Description |
|---|---|---|---|
| `check_interval_minutes` | entier | `60` | Fréquence du contrôle des applications du catalogue (partage réseau). |
| `app_check_interval_minutes` | entier | `240` | Fréquence du contrôle de la mise à jour de l'application elle-même (forge). |
| `retry_interval_minutes` | entier | `3` | Intervalle de reprise du contrôle tant qu'une ressource réseau (partage, forge) est inaccessible — l'intervalle normal est restauré à la première réussite. L'indisponibilité se reflète dans l'icône d'erreur, **sans notification**. |
| `check_on_startup` | booléen | `true` | Déclencher une première vérification immédiatement au démarrage. |
| `app_auto_restart` | booléen | `true` | Après déploiement d'une mise à jour de l'application, l'updater relance `main.py`. `false` ajoute `--no-relaunch` à l'updater. |

### `forge` — source de la mise à jour de l'application

| Clé | Type | Défaut | Description |
|---|---|---|---|
| `provider` | `github` \| `gitlab` | `github` | Forge interrogée pour la version distante et l'archive de déploiement — le tout par appels HTTP (voir [`../maj_application.md`](../maj_application.md)). |
| `github.branch` | chaîne | `main` | Branche suivie : `version.txt` distant et archive tarball de déploiement. |
| `gitlab.base_url` | chaîne | — | Racine de l'instance GitLab (ex. `https://gitlab.example.com`). |
| `gitlab.project_id` | chaîne | — | ID numérique du projet ; requis en mode `gitlab`. |
| `gitlab.branch` | chaîne | `main` | Branche suivie côté GitLab. |

Le dépôt GitHub du projet étant **public**, le mode `github` fonctionne
anonymement ; un jeton optionnel `WORKSTATION_TOOLER_GITHUB_TOKEN`
(`Authorization: Bearer`) n'est utile que si le dépôt redevient privé.

### `repository` — chemin réseau du catalogue des applications

| Clé | Type | Défaut | Description |
|---|---|---|---|
| `uri` | chaîne | — | **Requis.** Racine du catalogue : `smb://hôte/partage[/sous-chemin]`, ou `file:///chemin/local` (développement, tests). Toute autre URI (`http://`, `ftp://`...) est refusée au démarrage. |
| `auth` | chaîne | `session` | Mode d'authentification SMB : `session` (SSO avec la session de l'utilisateur du poste — poste Windows joint au domaine AD, droits de lecture requis sur le partage, `username`/`domain` interdits), `credentials` (compte explicite + mot de passe en variable d'environnement) ou `guest` (partage public de dev/test, sans signature). |
| `username` | chaîne | `""` | Compte SMB — modes `credentials` et `guest` uniquement (**requis** dans ces deux modes, refusé en mode `session`). smbprotocol ne sait pas ouvrir de session anonyme pure : en mode `guest`, mapper les invités côté serveur Samba (`map to guest = Bad User`). |
| `domain` | chaîne | `""` | Domaine NTLM, combiné au nom d'utilisateur (`DOMAINE\utilisateur`) — modes `credentials` et `guest` uniquement. |
| `timeout_seconds` | entier | `30` | Délai maximal d'établissement de la session SMB. |

La session SMB est **paresseuse** : établie au premier accès au catalogue. Un
partage injoignable ne fait donc pas échouer le démarrage — l'application
démarre, affiche l'icône d'erreur et retente toutes les
`update.retry_interval_minutes` minutes.

### `github`

| Clé | Type | Défaut | Description |
|---|---|---|---|
| `repository` | chaîne | — | Dépôt au format `propriétaire/dépôt`, utilisé pour construire les URL GitHub (version brute + archive tarball). |

### `ui`

| Clé | Type | Défaut | Description |
|---|---|---|---|
| `show_notifications` | booléen | `true` | **Non consommée à ce jour** (réservée à une évolution : filtrage des notifications). |

## Secrets — variables d'environnement

**Aucun secret dans ce fichier** (règle [AGENTS.md](../../AGENTS.md), une
dérogation documentée existe pour le token GitLab) :

| Secret | Variable d'environnement | Usage |
|---|---|---|
| Mot de passe SMB | `WORKSTATION_TOOLER_SMB_PASSWORD` | Uniquement en mode `repository.auth: credentials` (compte explicite) — exigée au démarrage dans ce mode. Les modes `session` (défaut) et `guest` n'utilisent aucun mot de passe. |
| Token GitLab lecture seule | `WORKSTATION_TOOLER_GITLAB_TOKEN` (recommandée), repli : constante `GITLAB_READ_TOKEN` de `core/app_updater.py` | API v4 et téléchargement de l'archive GitLab. **Dépôt public** : laisser la constante vide. |
| Jeton GitHub (optionnel) | `WORKSTATION_TOOLER_GITHUB_TOKEN` | Uniquement si le dépôt GitHub redevient privé. |

## Exemples d'URI de catalogue

```yaml
# Partage SMB (production) — session de l'utilisateur du poste (AD)
repository:
  uri: "smb://srv-fichiers/Workstation_Tooler"
  auth: "session"

# Partage SMB — compte authentifié
# (+ export WORKSTATION_TOOLER_SMB_PASSWORD='...')
repository:
  uri: "smb://srv-fichiers/Workstation_Tooler"
  auth: "credentials"
  username: "deploiement"
  domain: "ENTREPRISE"

# Partage SMB public (développement/test) — invités mappés côté Samba
repository:
  uri: "smb://localhost/Workstation_Tooler"
  auth: "guest"
  username: "guest"

# Répertoire local (développement, tests — même moteur, sans réseau)
repository:
  uri: "file:///home/dev/catalogue"
```

## Modifier la configuration

Ne pas modifier `config/` sans coordination (règle du projet) : le fichier est
lu au démarrage uniquement — un changement demande un redémarrage de
l'application. Les tests (`tests/test_config_loader.py`) vérifient certaines
valeurs du fichier réel.
