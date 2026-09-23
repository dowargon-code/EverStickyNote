"""Run a blocking Evernote call off the UI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from evernote_client import format_evernote_error


class _CallbackHub(QObject):
    """Lives on the UI thread so Evernote results are applied there."""

    def __init__(self, on_ok, on_err):
        super().__init__()
        self._on_ok = on_ok
        self._on_err = on_err

    @Slot(object)
    def succeed(self, value) -> None:
        self._on_ok(value)

    @Slot(str)
    def fail(self, message: str) -> None:
        self._on_err(message)


class AsyncCall(QObject):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, func):
        super().__init__()
        self._func = func

    @Slot()
    def run(self) -> None:
        try:
            value = self._func()
        except Exception as exc:
            self.failed.emit(format_evernote_error(exc))
        else:
            self.succeeded.emit(value)


def start_async(parent, func, on_ok, on_err) -> QThread:
    thread = QThread(parent)
    worker = AsyncCall(func)
    hub = _CallbackHub(on_ok, on_err)
    hub.setParent(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.succeeded.connect(hub.succeed)
    worker.failed.connect(hub.fail)
    worker.succeeded.connect(thread.quit, Qt.ConnectionType.DirectConnection)
    worker.failed.connect(thread.quit, Qt.ConnectionType.DirectConnection)
    thread.worker = worker
    thread.hub = hub
    return thread
