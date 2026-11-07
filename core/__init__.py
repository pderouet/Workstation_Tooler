"""Package core : socle technique de l'application (singletons, outils transverses)."""

from __future__ import annotations

from typing import Any, Dict, Type


class SingletonMeta(type):
    """Métaclasse générique assurant le patron de conception Singleton.

    Toute classe utilisant cette métaclasse ne pourra avoir qu'une seule
    instance partagée dans tout le processus. L'instanciation se fait de
    façon classique (``MaClasse()``), la métaclasse se chargeant de
    retourner l'instance existante si elle a déjà été créée.
    """

    _instances: Dict[Type[Any], Any] = {}

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
