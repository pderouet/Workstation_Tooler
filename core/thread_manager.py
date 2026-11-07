"""Singleton ThreadManager : gestion du cycle de vie des QThread/Worker.

Toute opération potentiellement bloquante (I/O, téléchargement, exécution
de binaire externe, etc.) doit être soumise à ce gestionnaire afin de ne
jamais geler le thread principal (UI). Le ``ThreadManager`` encapsule la
création des ``QThread``, le déplacement d'un ``Worker`` générique dans ce
thread, ainsi que le nettoyage des ressources une fois la tâche terminée.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, Optional, Tuple

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class Worker(QObject):
    """Encapsule l'exécution d'une fonction quelconque dans un ``QThread``.

    Signaux exposés :
        finished(object): résultat retourné par la fonction exécutée.
        error(Exception): exception levée pendant l'exécution, le cas échéant.
        progress(int): avancement optionnel rapporté par la fonction (0-100).
    """

    finished = pyqtSignal(object)
    error = pyqtSignal(Exception)
    progress = pyqtSignal(int)

    def __init__(
        self,
        func: Callable[..., Any],
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
    ) -> None:
        """Mémorise la fonction cible et ses arguments.

        Args:
            func: Fonction à exécuter dans le thread secondaire. Si elle
                accepte un paramètre nommé ``progress_callback``, celui-ci
                lui sera fourni pour émettre une progression (0-100).
            args: Arguments positionnels à transmettre à ``func``.
            kwargs: Arguments nommés à transmettre à ``func``.
        """
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        """Exécute la fonction cible et émet le signal correspondant.

        Toute exception est capturée et remontée via le signal ``error``
        plutôt que silencieusement ignorée, conformément à la politique
        centralisée de gestion des erreurs du projet.
        """
        try:
            if "progress_callback" in self._func.__code__.co_varnames:
                self._kwargs["progress_callback"] = self.progress.emit
            result = self._func(*self._args, **self._kwargs)
        except Exception as exc:  # remontée explicite vers l'ErrorHandler
            self.error.emit(exc)
        else:
            self.finished.emit(result)


class ThreadManager(QObject):
    """Gère la création et le nettoyage des ``QThread`` applicatifs.

    Exemple :
        >>> ThreadManager().run_task(
        ...     my_long_function,
        ...     on_result=lambda res: print(res),
        ... )
    """

    _instance: Optional["ThreadManager"] = None
    _initialized: bool = False

    def __new__(cls, *args: Any, **kwargs: Dict[str, Any]) -> "ThreadManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialise la table des threads actifs (une seule fois)."""
        if ThreadManager._initialized:
            return
        super().__init__()
        self._active_threads: Dict[str, Tuple[QThread, Worker]] = {}
        ThreadManager._initialized = True

    def run_task(
        self,
        func: Callable[..., Any],
        *args: Any,
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
        **kwargs: Any,
    ) -> str:
        """Lance ``func`` dans un nouveau ``QThread`` et retourne son identifiant.

        Args:
            func: Fonction à exécuter en tâche de fond.
            *args: Arguments positionnels transmis à ``func``.
            on_result: Rappelé avec le résultat de ``func`` en cas de succès.
            on_error: Rappelé avec l'exception levée en cas d'échec. Si non
                fourni, l'erreur est tout de même transmise à l'``ErrorHandler``
                centralisé par l'appelant via ce même callback.
            on_progress: Rappelé avec un pourcentage d'avancement (0-100).
            **kwargs: Arguments nommés transmis à ``func``.

        Returns:
            L'identifiant unique de la tâche lancée.
        """
        task_id = str(uuid.uuid4())
        thread = QThread()
        worker = Worker(func, args, kwargs)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._active_threads.pop(task_id, None))

        if on_result is not None:
            worker.finished.connect(on_result)
        if on_error is not None:
            worker.error.connect(on_error)
        if on_progress is not None:
            worker.progress.connect(on_progress)

        self._active_threads[task_id] = (thread, worker)
        thread.start()
        return task_id

    def shutdown(self, wait_ms: int = 5000) -> None:
        """Demande l'arrêt propre de tous les threads encore actifs.

        Args:
            wait_ms: Délai maximal (en millisecondes) accordé à chaque
                thread pour se terminer.
        """
        for thread, _worker in list(self._active_threads.values()):
            thread.quit()
            thread.wait(wait_ms)
