# Déploiement d'un poste — installation, autostart, Windows, désinstallation

> Procédure d'installation initiale de Workstation Tooler sur un poste de
> travail. La mise à jour est ensuite **autonome** (voir
> [`maj_application.md`](maj_application.md)) : cette page ne se lit qu'une
> fois par poste.

## Prérequis

- **Python 3.14+** sur le poste ;
- un environnement de bureau avec SystemTray (GNOME : extension AppIndicator ;
  Windows : intégré) ;
- accès réseau au **catalogue** (`repository.uri` du partage) et à la
  **forge** (GitHub public, ou GitLab + token) ;
- pour l'application elle-même : un **clone Git** de la forge n'est requis que
  pour la toute première installation — ensuite, les mises à jour sont 100 %
  HTTP (`git` peut même être absent).

## Installation initiale

```bash
git clone https://github.com/pderouet/Workstation_Tooler.git ~/Workstation_Tooler
cd ~/Workstation_Tooler
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Puis configurer le poste (voir [`configuration/settings_yaml.md`](configuration/settings_yaml.md)) :
`repository.uri` (partage du catalogue), `repository.auth` (`session` par
défaut : l'accès SMB utilise la session de l'utilisateur — poste joint au
domaine Active Directory, avec droits de lecture sur le partage), niveau de
log. Secrets en variables d'environnement de session si besoin :
`WORKSTATION_TOOLER_GITLAB_TOKEN` (et `WORKSTATION_TOOLER_SMB_PASSWORD`
uniquement en mode `auth: credentials`).

Premier lancement manuel pour valider :

```bash
.venv/bin/python main.py
```

Vérifier : l'icône apparaît (verte), le menu liste les applications du
catalogue, « Vérifier les mises à jour » répond.

## Démarrage automatique à l'ouverture de session

Une application SystemTray doit démarrer avec la session :

### Linux (systemd utilisateur)

`~/.config/systemd/user/workstation-tooler.service` :

```ini
[Unit]
Description=Workstation Tooler (SystemTray)
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/Workstation_Tooler/.venv/bin/python %h/Workstation_Tooler/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=graphical-session.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now workstation-tooler.service
```

### Windows

Raccourci dans le dossier « Démarrage » (`shell:startup`) pointant vers :

```
C:\Users\<login>\Workstation_Tooler\.venv\Scripts\pythonw.exe C:\Users\<login>\Workstation_Tooler\main.py
```

`pythonw.exe` (sans console) est recommandé ; le dossier du service systemd
devient `Workstation_Tooler\.venv\Scripts\` sous Windows.

## Comportement sous Windows

| Point | Comportement |
|---|---|
| Cibles `~` des manifests | résolues vers `C:\Users\<login>\...` (USERPROFILE) — **`~` est la forme portable à privilégier** |
| Variables `${VAR}` | **non développées** sous Windows (`%VAR%` l'est, `${VAR}` uniquement sous Linux) — voir [`configuration/manifest_yaml.md`](configuration/manifest_yaml.md#cibles-et-portabilité-target) |
| Détection de binaire | `shutil.which` s'appuie sur `PATHEXT` : `vim` trouve `vim.exe` |
| `mode: "755"` | sans effet (no-op) : Windows ne pilote pas les bits Unix — aucun crash |
| Partage SMB | smbprotocol est natif Windows ; les URI `smb://...` sont converties en UNC en interne. En mode `auth: session`, l'authentification utilise la session Windows de l'utilisateur (SSPI `Negotiate` : Kerberos puis NTLM) — la dépendance `sspilib` s'installe automatiquement sous Windows |
| Mise à jour autonome | PID via `tasklist`, arrêt forcé via `taskkill /F`, process détachés (`DETACHED_PROCESS`), venv dans `.venv\Scripts\` — déjà implémenté dans `updater.py` |
| Console colorée | mode ANSI activé automatiquement |

Cas limite : si `HOME` est défini dans l'environnement Windows (certaines
installations Git Bash), il prime sur `USERPROFILE` pour l'expansion de `~`.

## Après installation : que se passe-t-il

1. au démarrage, le catalogue est chargé en tâche de fond — le menu se
   peuple (sans bloquer l'UI) ;
2. les vérifications périodiques tournent (applications du catalogue +
   l'application elle-même) ;
3. un partage/forge injoignable **n'empêche rien** : icône d'erreur (rouge)
   et reprise toutes les 3 minutes — sans notification ;
4. les mises à jour disponibles sont **proposées** (notification groupée ;
   dialog à trois choix pour l'application elle-même) — jamais imposées.

## Désinstallation

1. Quitter l'application (menu → Quitter) ou arrêter le service :
   `systemctl --user disable --now workstation-tooler.service` ;
2. supprimer le démarrage automatique (service systemd ou raccourci
   `shell:startup`) ;
3. supprimer le dossier de l'application (`~/Workstation_Tooler`) — il n'y a
   pas d'autres fichiers système : les journaux (`logs/`) et le manifeste de
   déploiement (`.updater_manifest.json`) vivent dans ce dossier ;
4. nettoyer les fichiers déployés par le moteur si souhaité : ils sont listés
   dans `.updater_manifest.json` avant suppression du dossier, et les cibles
   des manifests (`~/.local/...`) par application.

> Les outils installés par le moteur (binaires, fragments de configuration)
> ne sont **pas** désinstallés automatiquement : le catalogue ne décrit pas
> de suppression.
