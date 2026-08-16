from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(int, int, object)


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:  # delivered to the GUI boundary
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.signals.finished.emit(result)


class AsyncProgressWorker(QRunnable):
    def __init__(
        self,
        function: Callable[[Callable[[int, int, object], None]], Coroutine[Any, Any, Any]],
    ) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        def progress(current: int, total: int, item: object) -> None:
            self.signals.progress.emit(current, total, item)

        try:
            result: Any = asyncio.run(self.function(progress))
        except Exception as exc:  # delivered to the GUI boundary
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.signals.finished.emit(result)
