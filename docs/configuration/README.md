# Référence des fichiers de configuration

Ce dossier est la **référence complète** des trois formats YAML utilisés par
Workstation Tooler. Chaque document est autonome : schéma clé par clé (type,
requis/optionnel, défaut), sémantique, exemples et règles de validation.

## Sommaire

| # | Document | Décrit | Emplacement du fichier |
|---|---|---|---|
| 1 | [`app_yaml.md`](app_yaml.md) | Métadonnées d'une application et détection de version installée | Catalogue distant : `<racine>/<application>/app.yaml` |
| 2 | [`manifest_yaml.md`](manifest_yaml.md) | Fichiers à déployer d'une version (actions `copy` / `decompress` / `ensure_content`) | Catalogue distant : `<racine>/<application>/<version>/manifest.yaml` |
| 3 | [`settings_yaml.md`](settings_yaml.md) | Configuration locale du poste (logging, planification, forge, chemin réseau) | Poste : `config/settings.yaml` |

### Sections par document

**1. [`app_yaml.md`](app_yaml.md)** — l'application dans le catalogue :
[emplacement](app_yaml.md#emplacement) · [schéma complet](app_yaml.md#schéma-complet)
([clés de premier niveau](app_yaml.md#clés-de-premier-niveau),
[version_detection](app_yaml.md#section-version_detection)) ·
[sémantique de la détection](app_yaml.md#sémantique-de-la-détection) ·
[exemples](app_yaml.md#exemples) · [règles de validation](app_yaml.md#règles-de-validation)

**2. [`manifest_yaml.md`](manifest_yaml.md)** — le déploiement d'une version :
[emplacement](manifest_yaml.md#emplacement) · [schéma complet](manifest_yaml.md#schéma-complet)
([entrées de files](manifest_yaml.md#entrées-de-files)) ·
[les trois actions](manifest_yaml.md#les-trois-actions)
([copy](manifest_yaml.md#copy--copier-un-fichier),
[decompress](manifest_yaml.md#decompress--extraire-une-archive),
[ensure_content](manifest_yaml.md#ensure_content--garantir-la-présence-dun-contenu)) ·
[cibles et portabilité](manifest_yaml.md#cibles-et-portabilité-target) ·
[exemple complet](manifest_yaml.md#exemple-complet) ·
[règles de validation](manifest_yaml.md#règles-de-validation)

**3. [`settings_yaml.md`](settings_yaml.md)** — la configuration du poste :
[fichier complet annoté](settings_yaml.md#fichier-complet-annoté) ·
[sections et clés](settings_yaml.md#sections-et-clés)
([logging](settings_yaml.md#logging), [update](settings_yaml.md#update--planification-et-comportement-des-mises-à-jour),
[forge](settings_yaml.md#forge--source-de-la-mise-à-jour-de-lapplication),
[repository](settings_yaml.md#repository--chemin-réseau-du-catalogue-des-applications),
[github](settings_yaml.md#github), [ui](settings_yaml.md#ui)) ·
[secrets](settings_yaml.md#secrets--variables-denvironnement) ·
[exemples d'URI](settings_yaml.md#exemples-duri-de-catalogue)

## Ordre de lecture conseillé

1. [`app_yaml.md`](app_yaml.md) — déclarer une application dans le partage ;
2. [`manifest_yaml.md`](manifest_yaml.md) — décrire ses versions et fichiers
   (les trois actions y sont détaillées) ;
3. [`settings_yaml.md`](settings_yaml.md) — brancher le poste sur le partage
   (`repository.uri`) et régler la planification.

## Documents connexes

| Document | Contenu |
|---|---|
| [`../moteur_mise_a_jour.md`](../moteur_mise_a_jour.md) | Vue d'ensemble du moteur (flux, pannes réseau, notification groupée) |
| [`../architecture_technique.md`](../architecture_technique.md) | Architecture : couches, singletons, signaux EventBus, modèle de threading |
| [`../maj_application.md`](../maj_application.md) | Mise à jour de l'application elle-même (forge, updater.py) |
| [`../exploitation_catalogue.md`](../exploitation_catalogue.md) | Guide administrateur du partage : publier, tester, retirer des versions |
| [`../deploiement_poste.md`](../deploiement_poste.md) | Installation d'un poste : autostart, volet Windows, désinstallation |
| [`../arborescence.md`](../arborescence.md) | Arborescence de référence du dépôt |
| [`../../examples/partage/README.md`](../../examples/partage/README.md) | Catalogue d'exemple prêt à recopier sur un partage de test |
| [`../../AGENTS.md`](../../AGENTS.md) | Conventions du projet (agents IA) |

Le schéma de référence du parsing est implémenté dans
[`engine/models.py`](../../engine/models.py) : validation stricte, toute clé
inconnue est une erreur (l'application concernée est ignorée et journalisée,
jamais interprétée de travers en silence).
