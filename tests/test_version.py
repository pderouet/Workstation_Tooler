"""Tests headless de la comparaison de versions par tri naturel."""

from __future__ import annotations

from engine.version import compare_versions, latest_version, parse_version_tokens


def test_compare_egalite_et_zero_de_tete() -> None:
    """Les zéros de tête numériques et le préfixe 'v' sont sans effet."""
    assert compare_versions("9.07", "9.7") == 0
    assert compare_versions("v0.50.0", "0.50.0") == 0


def test_compare_ordre_numerique() -> None:
    """Les composants numériques se comparent numériquement, pas lexicographiquement."""
    assert compare_versions("9.1.0700", "9.1.500") == 1
    assert compare_versions("2", "10") == -1
    assert compare_versions("0.9", "v0.50.0") == -1


def test_compare_versions_de_longueurs_differentes() -> None:
    """Une version qui étend un préfixe commun égal est supérieure."""
    assert compare_versions("9.1.1", "9.1") == 1
    assert compare_versions("9.1", "9.1.1") == -1


def test_compare_avec_suffixe_alphabetique() -> None:
    """Les jetons alphabétiques se comparent après les numériques.

    Conséquence recherchée : un suffixe de pré-version (rc, beta, dev) précède
    la version finale correspondante.
    """
    assert compare_versions("4.3.2-rc1", "4.3.2-rc2") == -1
    assert compare_versions("4.3.2-rc1", "4.3.2") == -1
    assert compare_versions("4.3.2", "4.3.2-rc1") == 1


def test_parse_tokens_ignorant_le_prefixe() -> None:
    """Le préfixe 'v' suivi d'un chiffre n'apparaît pas dans les jetons."""
    tokens = parse_version_tokens("v10.2")
    assert tokens == ((10, ""), (2, ""))


def test_latest_version_parmi_candidats() -> None:
    """La version la plus élevée est retenue, même non triée."""
    assert latest_version(["0.9", "v0.50.0", "0.10.3", "9.1"]) == "9.1"
    assert latest_version(["1.2", "1.10", "1.3"]) == "1.10"


def test_latest_version_vide() -> None:
    """Une collection vide n'a pas de version la plus élevée."""
    assert latest_version([]) is None
