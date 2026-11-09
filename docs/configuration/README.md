# Référence des fichiers de configuration

Ce dossier est la **référence complète** des trois formats YAML utilisés par
Workstation Tooler :

| Document | Contenu | Emplacement |
|---|---|---|
| [`app_yaml.md`](app_yaml.md) | Métadonnées d'une application et détection de version installée | Catalogue distant : `<racine>/<application>/app.yaml` |
| [`manifest_yaml.md`](manifest_yaml.md) | Fichiers à déployer pour une version (actions `copy` / `decompress` / `ensure_content`) | Catalogue distant : `<racine>/<application>/<version>/manifest.yaml` |
| [`settings_yaml.md`](settings_yaml.md) | Configuration locale de l'application (logging, planification, forge, chemin réseau) | Poste : `config/settings.yaml` |

Les deux premiers décrivent le **catalogue distant** : ajouter ou modifier un
outil géré ne demande que le dépôt de fichiers sur le partage, aucun code
local. Le troisième décrit la configuration propre à chaque poste.

Pour la vue d'ensemble des mécanismes (flux de mise à jour, gestion des
pannes réseau, notification groupée...), voir :
- [`../moteur_mise_a_jour.md`](../moteur_mise_a_jour.md) — moteur des applications gérées ;
- [`../maj_application.md`](../maj_application.md) — mise à jour de l'application elle-même.

Le schéma de référence du parsing est implémenté dans
[`engine/models.py`](../../engine/models.py) : validation stricte, toute clé
inconnue est une erreur (l'application concernée est ignorée et journalisée,
jamais interprétée de travers en silence).
