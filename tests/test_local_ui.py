import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QEventLoop, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from local_notes import LocalNote, LocalNoteSummary, LocalNotebook
from local_store import LocalStore
from ui.local_window import LocalMainWindow


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def wait_until(predicate, timeout_ms=3000):
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
        raise AssertionError("timed out")


class FakeReader:
    def __init__(self):
        self.bodies = {"n1": "本文です", "secret": "見えない"}

    def open(self):
        return None

    def close(self):
        return None

    def list_notebooks(self):
        return [LocalNotebook("nb", "仕事"), LocalNotebook("other", "個人")]

    def list_notes(self, notebook_id):
        if notebook_id == "other":
            return [LocalNoteSummary("secret", "秘密", notebook_id)]
        return [LocalNoteSummary("n1", "題", notebook_id)]

    def get_note(self, note_id):
        if note_id == "secret":
            return LocalNote(note_id, "秘密", self.bodies.get(note_id, "見えない"), "other")
        return LocalNote(note_id, "題", self.bodies.get(note_id, "本文です"), "nb")

    def note_app_url(self, note_id):
        return f"evernote:///view/1/s1/{note_id}/nb"


class LocalWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _app()

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = LocalStore(Path(self._dir.name) / "state.sqlite")
        self.config_path = Path(self._dir.name) / "config.toml"
        self.config_path.write_text('notebooks = ["仕事"]\n', encoding="utf-8")
        self.position_path = Path(self._dir.name) / "position.toml"
        self.reader = FakeReader()
        self.opened_urls: list[str] = []
        self.windows: list[LocalMainWindow] = []
        self._stamp_value = 0
        self.startup_calls: list[bool] = []
        self.window = self._open_window()

    def _open_window(self) -> LocalMainWindow:
        window = LocalMainWindow(
            store=self.store,
            opener=lambda: self.reader,
            config_path=self.config_path,
            url_opener=self.opened_urls.append,
            position_path=self.position_path,
            stamp=lambda: self._stamp_value,
            startup_apply=self.startup_calls.append,
        )
        self.windows.append(window)
        return window

    def tearDown(self):
        for window in self.windows:
            window.close()
        for _ in range(20):
            QApplication.processEvents()
            if all(not window._threads for window in self.windows):
                break
        QApplication.processEvents()
        self.store.close()
        self._dir.cleanup()

    def test_open_note_is_read_only(self):
        wait_until(lambda: self.window.note_list.count() == 1)
        self.assertEqual(self.window.notebook_combo.count(), 1)
        self.assertEqual(self.window.notebook_combo.currentText(), "仕事")
        self.window.note_list.setCurrentRow(0)
        self.window.open_selected()
        wait_until(lambda: "n1" in self.window._windows)
        sticky = self.window._windows["n1"]
        self.assertEqual(sticky.note_text(), "本文です")
        self.assertTrue(sticky.title_edit.isReadOnly())
        self.assertTrue(sticky.body_edit.isReadOnly())
        self.assertTrue(sticky.banner.isHidden())
        sticky.close_button.click()
        self.assertNotIn("n1", self.window._windows)
        self.assertFalse(self.store.get_note_state("n1").is_open)
        self.assertFalse(self.window._layout.notes["n1"].visible)

    def test_double_click_on_the_drag_area_opens_the_evernote_note(self):
        wait_until(lambda: self.window.note_list.count() == 1)
        self.window.note_list.setCurrentRow(0)
        self.window.open_selected()
        wait_until(lambda: "n1" in self.window._windows)
        sticky = self.window._windows["n1"]
        sticky._bar.mouseDoubleClickEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonDblClick,
                QPointF(8, 8),
                QPointF(8, 8),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        self.assertEqual(self.opened_urls, ["evernote:///view/1/s1/n1/nb"])

    def test_sticky_reopens_at_the_saved_position(self):
        wait_until(lambda: self.window.note_list.count() == 1)
        self.window.note_list.setCurrentRow(0)
        self.window.open_note("n1")
        wait_until(lambda: "n1" in self.window._windows)
        sticky = self.window._windows["n1"]
        sticky.move(320, 180)
        sticky.resize(360, 240)
        self.window._save_geometry("n1")
        self.window.close()

        again = self._open_window()
        wait_until(lambda: again.note_list.count() == 1)
        again.open_note("n1")
        wait_until(lambda: "n1" in again._windows)
        restored = again._windows["n1"]
        self.assertEqual(restored.x(), 320)
        self.assertEqual(restored.y(), 180)
        self.assertEqual(restored.width(), 360)
        self.assertEqual(restored.height(), 240)
        again.close()

    def test_main_window_reopens_minimized_when_it_was_closed_minimized(self):
        self.window.show()
        self.window.showMinimized()
        self.assertTrue(self.window.isMinimized())
        self.window.close()

        again = self._open_window()
        wait_until(lambda: again.note_list.count() == 1)
        again.show_saved_state()
        self.assertTrue(again.isMinimized())
        sticky = again._windows.get("n1")
        if sticky is None:
            again.open_note("n1")
            wait_until(lambda: "n1" in again._windows)
            sticky = again._windows["n1"]
        sticky.mainRequested.emit("n1")
        self.assertFalse(again.isMinimized())
        again.close()

    def test_watch_reloads_only_when_the_database_stamp_changes(self):
        wait_until(lambda: self.window.note_list.count() == 1 and not self.window._threads)
        self.assertEqual(self.window._watch_seconds, 2)
        self.assertEqual(self.window._watched_stamp, 0)
        generation = self.window._generation
        self.window._watch()
        self.assertEqual(self.window._generation, generation)
        self._stamp_value = 1
        self.window._watch()
        wait_until(lambda: self.window._watched_stamp == 1 and not self.window._threads)
        self.assertGreater(self.window._generation, generation)
        self.assertEqual(self.window.note_list.count(), 1)

    def test_hidden_note_appears_only_while_its_update_flickers(self):
        wait_until(lambda: self.window.note_list.count() == 1 and not self.window._threads)
        self.window.open_note("n1")
        wait_until(lambda: "n1" in self.window._windows)
        self.window.close_sticky("n1")
        self.assertFalse(self.window._layout.notes["n1"].visible)
        self.reader.bodies["n1"] = "更新後"
        self._stamp_value = 1
        self.window._watch()
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        sticky = self.window._windows["n1"]
        self.assertIn("3px solid", sticky.styleSheet())
        self.assertFalse(self.window._layout.notes["n1"].visible)
        sticky._flicker_elapsed = 5000
        sticky._tick_update_flicker()
        self.assertNotIn("n1", self.window._windows)
        self.assertFalse(self.window._layout.notes["n1"].visible)

    def test_hidden_note_stays_open_when_close_after_flicker_is_off(self):
        self.config_path.write_text(
            'notebooks = ["仕事"]\nflicker_seconds = 1\nclose_after_flicker = false\n',
            encoding="utf-8",
        )
        wait_until(lambda: self.window.note_list.count() == 1 and not self.window._threads)
        self.window.open_note("n1")
        wait_until(lambda: "n1" in self.window._windows)
        self.window.close_sticky("n1")
        self.assertNotIn("n1", self.window._windows)
        self.reader.bodies["n1"] = "更新後"
        self._stamp_value = 1
        self.window._watch()
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        sticky = self.window._windows["n1"]
        self.assertEqual(sticky._flicker_limit_ms, 1000)
        self.assertTrue(self.window._layout.notes["n1"].visible)
        sticky._flicker_elapsed = 1000
        sticky._tick_update_flicker()
        self.assertIn("n1", self.window._windows)
        self.assertTrue(self.window._layout.notes["n1"].visible)

    def test_startup_checkbox_saves_the_toml_setting(self):
        wait_until(lambda: self.window.note_list.count() == 1)
        self.assertFalse(self.window.startup_check.isChecked())
        self.window.startup_check.setChecked(True)
        text = self.config_path.read_text(encoding="utf-8")
        self.assertIn("launch_at_startup = true", text)
        self.assertEqual(self.startup_calls[-1], True)


if __name__ == "__main__":
    unittest.main()