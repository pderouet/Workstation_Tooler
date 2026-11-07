"""Comparaison de versions par tri naturel et résolution de la plus récente.

Les versions rencontrées dans le catalogue distant sont des chaînes libres
(``9.1.0700``, ``v0.50.0``, ``4.3.2-rc1``...) : une simple comparaison de
chaînes serait incorrecte (``"9" > "10"``). Ce module découpe une version en
jetons numériques et alphabétiques pour les comparer naturellement.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

#: Préfixe « v »/«V » immédiatement suivi d'un chiffre, ignoré lors de la comparaison.
_VERSION_PREFIX = re.compile(r"^[vV](?=\d)")

#: Découpage d'une version en jetons numériques ou alphabétiques.
_TOKEN_PATTERN = re.compile(r"\d+|[A-Za-z]+")


def parse_version_tokens(version: str) -> tuple[tuple[int, str], ...]:
    """Découpe une version en jetons comparables (numériques puis alphabétiques).

    Chaque jeton devient un couple ``(valeur_numérique, texte)`` : les jetons
    numériques portent leur valeur (``"0700"`` -> ``(700, "")``) et les jetons
    alphabétiques une valeur sentinelle négative (``"rc1"`` -> ``(-1, "rc"),
    (1, "")``), de sorte qu'un jeton numérique précède toujours un jeton
    alphabétique à position égale.

    Args:
        version: Chaîne de version (ex. ``"v0.50.0"``).

    Returns:
        Le tuple des jetons, vide si aucun jeton exploitable n'est trouvé.
    """
    cleaned = _VERSION_PREFIX.sub("", version.strip())
    tokens: list[tuple[int, str]] = []
    for raw in _TOKEN_PATTERN.findall(cleaned):
        if raw.isdigit():
            tokens.append((int(raw), ""))
        else:
            tokens.append((-1, raw.lower()))
    return tuple(tokens)


def compare_versions(left: str, right: str) -> int:
    """Compare deux versions par tri naturel (préfixe ``v`` ignoré).

    Les zéros de tête numériques sont sans effet (``9.07`` == ``9.7``) et une
    version plus longue est supérieure si le préfixe commun est égal
    (``9.1.1`` > ``9.1``).

    Args:
        left: Première version.
        right: Seconde version.

    Returns:
        -1 si ``left < right``, 0 si équivalentes, 1 si ``left > right``.
    """
    left_tokens = list(parse_version_tokens(left))
    right_tokens = list(parse_version_tokens(right))
    length = max(len(left_tokens), len(right_tokens))
    # Le remplissage par (0, "") fait qu'une version plus longue "étend" la
    # plus courte avec des jetons nuls : 9.1 devient 9.1.0 pour comparer à 9.1.2.
    left_tokens += [(0, "")] * (length - len(left_tokens))
    right_tokens += [(0, "")] * (length - len(right_tokens))

    if left_tokens < right_tokens:
        return -1
    if left_tokens > right_tokens:
        return 1
    return 0


def latest_version(versions: Iterable[str]) -> Optional[str]:
    """Retourne la version la plus élevée d'une collection.

    Args:
        versions: Versions candidates (ex. noms des dossiers de version).

    Returns:
        La version la plus récente, ou ``None`` si la collection est vide.
    """
    candidates = list(versions)
    if not candidates:
        return None
    return max(candidates, key=parse_version_tokens)
