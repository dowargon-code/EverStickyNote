"""二重起動を防ぐ。2つ目の起動は、動いている方にメインフォームを出させて終わる。"""

from __future__ import annotations

import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

CONNECT_TIMEOUT_MS = 500


def default_server_name() -> str:
    # Windows の名前付きパイプはユーザーをまたいで見えるので、ユーザー名を含める
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"EverStickyNote-{user}"


class SingleInstance(QObject):
    """最初の起動だけが acquire() で True を得る。2つ目以降には activated で知らせる。"""

    activated = Signal()

    def __init__(self, name: str | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._name = default_server_name() if name is None else name
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        if notify_running(self._name):
            return False
        server = QLocalServer(self)
        if not server.listen(self._name):
            # ほぼ同時に起動した別のプロセスが先に名前を取った
            return False
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.disconnected.connect(socket.deleteLater)
            socket.disconnectFromServer()
            self.activated.emit()


def notify_running(name: str) -> bool:
    """同じ名前のアプリが動いていれば接続して True を返す。"""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
        return False
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(CONNECT_TIMEOUT_MS)
    return True
