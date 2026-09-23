import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel

from evernote_client import EvernoteClient
from local_store import LocalStore
from sync import text_to_enml
from tests.fake_store import FakeNoteStore
from ui.main_window import MainWindow
from ui.sticky_window import StickyWindow


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _mouse(event_type, global_point, widget, buttons):
    button = Qt.MouseButton.LeftButton
    if event_type == QEvent.Type.MouseMove:
        button = Qt.MouseButton.NoButton
    return QMouseEvent(
        event_type,
        widget.mapFromGlobal(global_point),
        global_point,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def wait_until(predicate, timeout_ms=3000, detail=None):
    if predicate():
        return
    loop = QEventLoop()
    finished = {"done": False}

    def finish():
        if not finished["done"]:
            finished["done"] = True
            loop.quit()

    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: finish() if predicate() else None)
    QTimer.singleShot(timeout_ms, finish)
    timer.start()
    loop.exec()
    timer.stop()
    if not predicate():
        extra = detail() if detail else ""
        raise AssertionError(f"timed out {extra}")


class StickyWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _app()

    def test_color_pin_and_conflict_banner(self):
        window = StickyWindow("note-1", color="yellow", pinned=True)
        window.set_content("題", "本文")
        window.show()
        self.assertEqual(window.note_title(), "題")
        self.assertTrue(window.pinned())
        window.set_color("blue")
        self.assertEqual(window.color(), "blue")
        window.set_pinned(False)
        self.assertFalse(window.pinned())
        window.set_conflict(True)
        self.assertFalse(window.pull_button.isHidden())
        self.assertIn("Evernote側が新しい", window.banner.text())
        window.set_rich(True)
        self.assertTrue(window.body_edit.isReadOnly())
        window.close()

    def test_header_drag_moves_from_the_title(self):
        window = StickyWindow("note-1")
        window.set_read_only("読み取り専用")
        window.set_content("付箋テスト", "本文")
        window.move(120, 80)
        window.show()
        self.assertNotIn("移動", [label.text() for label in window.findChildren(QLabel)])

        start = window.pos()
        point = window.title_edit.mapToGlobal(window.title_edit.rect().center())
        window._bar.mousePressEvent(
            _mouse(QEvent.Type.MouseButtonPress, point, window._bar, Qt.MouseButton.LeftButton)
        )
        moved = point + QPoint(40, 24)
        window._bar.mouseMoveEvent(
            _mouse(QEvent.Type.MouseMove, moved, window._bar, Qt.MouseButton.LeftButton)
        )
        window._bar.mouseReleaseEvent(
            _mouse(QEvent.Type.MouseButtonRelease, moved, window._bar, Qt.MouseButton.NoButton)
        )
        self.assertEqual(window.pos(), start + QPoint(40, 24))
        window.close()

    def test_pin_button_releases_always_on_top_without_closing(self):
        window = StickyWindow("note-1", pinned=True)
        window.move(180, 140)
        window.show()
        self.assertEqual(window.pin_button.text(), "最前面")
        place = window.geometry()
        window.pin_button.click()
        self.assertTrue(window.isVisible())
        self.assertFalse(window.pinned())
        self.assertFalse(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertEqual(window.geometry(), place)
        self.assertEqual(window.pin_button.text(), "最前面")
        window.pin_button.click()
        self.assertTrue(window.isVisible())
        self.assertTrue(window.pinned())
        self.assertTrue(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertEqual(window.pin_button.text(), "最前面")
        window.close()


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _app()

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = FakeNoteStore()
        self.local = LocalStore(Path(self._dir.name) / "state.sqlite")
        self.client = EvernoteClient("token", note_store=self.store)
        self.window = MainWindow(
            store=self.local,
            client_factory=lambda token: self.client,
        )

    def tearDown(self):
        self.window.close()
        self.local.close()
        self._dir.cleanup()

    def test_open_edit_save_and_conflict_pull(self):
        self.window.connect_token("token")
        wait_until(
            lambda: self.window.note_list.count() == 1,
            detail=lambda: self.window.status.text(),
        )
        self.assertEqual(self.window.notebook_combo.currentText(), "付箋")
        self.window.note_list.setCurrentRow(0)
        self.window.open_selected()
        wait_until(lambda: "note-1" in self.window._windows)
        sticky = self.window._windows["note-1"]
        self.assertEqual(sticky.note_text(), "牛乳")
        self.assertTrue(self.local.get_note_state("note-1").is_open)

        sticky.body_edit.setPlainText("牛乳とパン")
        self.window.save_note("note-1")
        wait_until(lambda: "パン" in self.store.notes["note-1"].content)
        self.assertIn("保存しました", self.window.status.text())

        self.store.notes["note-1"].content = text_to_enml("サーバ側")
        self.store.notes["note-1"].updateSequenceNum = 99
        sticky.body_edit.setPlainText("手元の下書き")
        self.window.save_note("note-1")
        wait_until(lambda: sticky.pull_button.isVisible())
        self.assertIn("上書きを止めて", self.window.status.text())
        self.assertIn("手元の下書き", sticky.note_text())

        sticky.pull_button.click()
        wait_until(lambda: sticky.note_text() == "サーバ側" and not sticky.pull_button.isVisible())
        self.assertFalse(self.window._sessions["note-1"].conflict)

        sticky.close_button.click()
        self.assertNotIn("note-1", self.window._windows)
        self.assertFalse(self.local.get_note_state("note-1").is_open)


if __name__ == "__main__":
    unittest.main()
