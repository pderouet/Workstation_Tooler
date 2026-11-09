# Contenu d'exemple du catalogue distant

Ce dossier reproduit l'agencement attendu par le moteur de mise à jour sur le
chemin réseau (`repository.uri` de `config/settings.yaml`). Il sert à la fois
de référence et de jeu d'essai pour alimenter le partage de test
`smb://localhost/Workstation_Tooler/`.

```
partage/                       ← racine recopiée à la racine du partage
├── vim/
│   ├── app.yaml               ← métadonnées + détection de version installée
│   └── 9.9.9999/              ← dossier de version (nom = numéro de version)
│       ├── manifest.yaml      ← fichiers de cette version et actions
│       ├── vim-9.9.9999.tar.gz   (action decompress)
│       ├── vim-exemple           (action copy, mode 755)
│       └── vimrc.fragment        (action ensure_content)
└── k9s/
    ├── app.yaml
    └── v0.99.0/
        ├── manifest.yaml
        └── k9s_Linux_amd64.tar.gz   (action decompress)
```

Les versions proposées sont **fictives et volontairement très élevées**
(`9.9.9999`, `v0.99.0`) afin que la vérification propose toujours une mise à
jour, même sur un poste où `vim`/`k9s` réels sont installés. Les cibles des
manifests sont toutes regroupées sous des chemins `~/.local/...` et
`~/.config/workstation_tooler/...` : la démonstration n'écrase aucun fichier
réel du poste.

## Alimenter le partage de test

Avec le client SMB en ligne de commande (session invité) :

```bash
smbclient //localhost/Workstation_Tooler -N -c "lcd <chemin vers ce dossier>; prompt; recurse; mput vim k9s"
```

Ce partage de test local correspond au mode `auth: "guest"` avec
`username: "guest"` dans `config/settings.yaml`. Si le partage exige plutôt un
compte authentifié, passez en mode `auth: "credentials"`, renseignez
`repository.username` et exportez le mot de passe avant de lancer
l'application :

```bash
export WORKSTATION_TOOLER_SMB_PASSWORD='...'
```

## Essai sans partage (backend local)

Le schéma `file://` est accepté par `repository.uri`, ce qui permet de tester
le moteur directement sur ce dossier, sans SMB :

```yaml
repository:
  uri: "file:///home/<utilisateur>/code/Workstation_Tooler/examples/partage"
```

Voir `docs/moteur_mise_a_jour.md` pour la référence complète du format.
