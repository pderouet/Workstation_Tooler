#!/usr/bin/env python3
"""Génère les variantes colorées de l'icône du SystemTray.

Utilitaire de développement (nécessite Pillow, non requis à l'exécution de
l'application) qui recolore l'arrière-plan de ``app_icon.ico`` pour produire
les variantes d'état utilisées par le SystemTray :

- ``app_icon_ok.ico``   (vert)  : application/module à jour, aucune action en cours.
- ``app_icon_info.ico`` (bleu)  : une information est disponible (ex. mise à jour détectée).
- ``app_icon_wip.ico``  (jaune) : une opération est en cours (installation, maj, ...).

La teinte de l'arrière-plan d'origine (``#b2ebf2``, cyan clair) est décalée
vers la teinte cible tout en conservant la saturation et la luminosité de
chaque pixel, ce qui préserve les nuances/antialiasing du dessin d'origine.
Les pixels peu saturés (le robot, en niveaux de gris) ne sont pas affectés.

Usage :
    python3 resources/icons/generate_icon_variants.py
"""

from __future__ import annotations

import colorsys
from pathlib import Path

from PIL import Image

ICONS_DIR = Path(__file__).resolve().parent
SOURCE_ICON = ICONS_DIR / "app_icon.ico"

#: Teinte (en degrés) de l'arrière-plan d'origine (#b2ebf2).
SOURCE_HUE_DEGREES = 186.5625
#: Tolérance (en degrés) pour considérer un pixel comme faisant partie de l'arrière-plan.
HUE_TOLERANCE_DEGREES = 40.0
#: Saturation minimale pour qu'un pixel soit considéré comme coloré (et non gris/robot).
MIN_SATURATION = 0.12

#: Tailles embarquées dans chaque fichier .ico généré.
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128)]

#: Teintes cibles (en degrés) par variante d'état.
TARGET_VARIANTS = {
    "app_icon_ok.ico": 120.0,  # Vert : OK.
    "app_icon_info.ico": 210.0,  # Bleu : Info.
    "app_icon_wip.ico": 48.0,  # Jaune : WIP (en cours).
}


def _hue_distance(hue_a: float, hue_b: float) -> float:
    """Calcule la distance angulaire la plus courte entre deux teintes (en degrés)."""
    diff = abs(hue_a - hue_b) % 360.0
    return min(diff, 360.0 - diff)


def recolor(image: Image.Image, target_hue_degrees: float) -> Image.Image:
    """Décale la teinte des pixels d'arrière-plan vers ``target_hue_degrees``.

    Args:
        image: Image source en mode RGBA.
        target_hue_degrees: Teinte cible, en degrés (0-360).

    Returns:
        Une nouvelle image RGBA avec l'arrière-plan recoloré.
    """
    source = image.convert("RGBA")
    pixels = source.load()
    width, height = source.size
    hue_shift = (target_hue_degrees - SOURCE_HUE_DEGREES) / 360.0

    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue

            h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            if (
                s < MIN_SATURATION
                or _hue_distance(h * 360.0, SOURCE_HUE_DEGREES) > HUE_TOLERANCE_DEGREES
            ):
                continue  # Pixel hors arrière-plan (ex. robot en niveaux de gris) : inchangé.

            new_h = (h + hue_shift) % 1.0
            new_r, new_g, new_b = colorsys.hsv_to_rgb(new_h, s, v)
            pixels[x, y] = (round(new_r * 255), round(new_g * 255), round(new_b * 255), a)

    return source


def main() -> None:
    """Génère les trois variantes d'icône à partir de l'icône source."""
    if not SOURCE_ICON.exists():
        raise FileNotFoundError(f"Icône source introuvable : {SOURCE_ICON}")

    source_image = Image.open(SOURCE_ICON)

    for filename, target_hue in TARGET_VARIANTS.items():
        variant = recolor(source_image, target_hue)
        output_path = ICONS_DIR / filename
        variant.save(output_path, sizes=ICO_SIZES)
        print(f"Généré : {output_path}")


if __name__ == "__main__":
    main()
