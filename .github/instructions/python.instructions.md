---
applyTo: "**/*.py"
---

# Consignes pour le code Python

## Conventions
- Respecte la version de Python et les conventions déjà utilisées dans le projet.
- Suis PEP 8 et utilise des noms explicites pour les variables, fonctions et classes.
- Ajoute des annotations de type aux fonctions et méthodes.
- Écris des docstrings pour les fonctions et classes publiques, selon le style déjà présent dans le projet.
- Privilégie du code simple, lisible et facile à tester.

## Modifications
- Avant de créer une nouvelle fonction ou classe, vérifie si une solution équivalente existe déjà.
- Limite les changements aux fichiers nécessaires à la tâche.
- N’ajoute pas de dépendance sans nécessité ; si tu en ajoutes une, explique pourquoi.
- Ne place jamais de mots de passe, clés API ou autres secrets dans le code.

## Erreurs et entrées
- Vérifie et valide les données provenant de l’utilisateur ou de sources externes.
- Gère les erreurs de façon explicite ; évite les blocs `except` trop généraux.
- N’ignore pas silencieusement les exceptions.
