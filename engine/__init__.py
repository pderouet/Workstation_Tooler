"""Moteur de mise à jour piloté par un catalogue distant.

Ce paquet remplace l'ancienne mécanique « un module Python par outil » par un
moteur unique, piloté par les données : les applications gérées, leurs versions
et les fichiers à déployer sont décrits par des manifests YAML hébergés sur un
chemin réseau unique (voir ``docs/moteur_mise_a_jour.md``).

Principaux composants :
    - ``models`` : modèles de données du catalogue et parsing/validation YAML.
    - ``version`` : comparaison de versions (tri naturel) et résolution « latest ».
    - ``storage`` : backends d'accès au chemin réseau (SMB) ou local (tests).
    - ``repository`` : accès structuré au catalogue (applications, manifests).
    - ``catalog`` : chargement du catalogue complet depuis le repository.
    - ``detection`` : détection de la version installée (déclarée dans le YAML).
    - ``actions`` : exécuteurs des mots-clés ``copy``/``decompress``/``ensure_content``.
    - ``update_engine`` : orchestrateur (vérifications, mises à jour, progression).
"""
