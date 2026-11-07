"""Détection de la version installée d'une application sur le poste.

La commande de détection est déclarée dans le ``app.yaml`` de chaque
application (binaire, arguments, motif d'extraction) : le moteur n'embarque
aucune connaissance spécifique par outil.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Callable, List, Optional

from engine.models import VersionDetection

#: Fonction exécutant une commande et retournant sa sortie standard.
#: Signature : ``(binaire, arguments, delai_secondes) -> sortie_standard``.
#: Injectable afin de tester la détection sans exécuter de vrai sous-processus.
CommandOutput = Callable[[str, List[str], int], str]


def _default_command_output(binary: str, args: List[str], timeout_seconds: int) -> str:
    """Exécute le binaire de détection et retourne sa sortie standard.

    Args:
        binary: Chemin ou nom du binaire résolu (via ``PATH``).
        args: Arguments de la ligne de commande.
        timeout_seconds: Délai maximal d'exécution.

    Returns:
        La sortie standard de la commande.

    Raises:
        subprocess.SubprocessError: Si l'exécution échoue ou expire.
        OSError: Si le binaire ne peut pas être lancé.
    """
    completed = subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return completed.stdout


def resolve_binary(detection: VersionDetection) -> Optional[str]:
    """Résout le binaire de détection (avec repli) présent dans le ``PATH``.

    Args:
        detection: Déclaration de détection de l'application.

    Returns:
        Le premier binaire trouvable, ou ``None`` si aucun n'est installé.
    """
    candidates = [detection.binary, detection.fallback_binary]
    for candidate in candidates:
        if candidate and shutil.which(candidate):
            return candidate
    return None


def detect_installed_version(
    detection: VersionDetection,
    command_output: CommandOutput = _default_command_output,
) -> Optional[str]:
    """Détecte la version installée d'une application sur le poste.

    Args:
        detection: Déclaration de détection (binaire, arguments, motif).
        command_output: Exécuteur de commande, injectable pour les tests.

    Returns:
        La version extraite, ou ``None`` si le binaire est introuvable ou que
        le motif ne correspond pas à la sortie.

    Raises:
        subprocess.SubprocessError: Si la commande de détection échoue ou expire
            (l'appelant décide d'assimiler cela à « non installé »).
        OSError: Si le binaire ne peut pas être lancé.
    """
    binary = resolve_binary(detection)
    if binary is None:
        return None

    stdout = command_output(binary, list(detection.args), detection.timeout_seconds)

    match = re.search(detection.pattern, stdout)
    if match is None:
        return None
    extracted = match.group(1) if match.groups() else match.group(0)
    extracted = extracted.strip()
    return extracted or None
