import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QEventLoop, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog

from everstickynote.local_notes import LocalEvernoteError, LocalNote, LocalNoteSummary, LocalNotebook
from everstickynote.local_store import LocalStore
from everstickynote.ui.local_window import (
    ALL_NOTEBOOKS_ID,
    LocalMainWindow,
    NewNoteDialog,
    SettingsDialog,
)
from everstickynote.ui.sticky_window import arrange_positions


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
        self.titles = {"n1": "題", "secret": "秘密"}
        self.note_notebooks = {"n1": "nb", "secret": "other"}
        self.notebooks = [LocalNotebook("nb", "仕事"), LocalNotebook("other", "個人")]
        self.removed: set[str] = set()

    def open(self):
        return None

    def close(self):
        return None

    def list_notebooks(self):
        return list(self.notebooks)

    def list_notes(self, notebook_id):
        return [
            LocalNoteSummary(note_id, self.titles.get(note_id, "題"), notebook_id)
            for note_id, owner in self.note_notebooks.items()
            if owner == notebook_id and note_id not in self.removed
        ]

    def get_note(self, note_id):
        if note_id in self.removed or note_id not in self.bodies:
            raise LocalEvernoteError("ノートが見つかりません")
        return LocalNote(
            note_id,
            self.titles.get(note_id, "題"),
            self.bodies[note_id],
            self.note_notebooks.get(note_id, "nb"),
        )

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
        self.opened_enex: list[Path] = []
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
            quit_on_exit=lambda: None,
            enex_opener=self.opened_enex.append,
        )
        self.windows.append(window)
        return window

    def tearDown(self):
        for window in self.windows:
            if window._closed:
                continue
            window._force_close = True
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
        self.assertIn("n1", self.window._windows)
        self.assertTrue(sticky.isMinimized())
        self.assertTrue(self.window._layout.notes["n1"].visible)

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
        self.window._force_close = True
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
        again._force_close = True
        again.close()

    def test_main_window_reopens_minimized_when_it_was_closed_minimized(self):
        self.window.show()
        self.window._hide_to_tray()
        self.assertFalse(self.window.isVisible())
        self.window._force_close = True
        self.window.close()

        again = self._open_window()
        wait_until(lambda: again.note_list.count() == 1)
        again.show_saved_state()
        self.assertFalse(again.isVisible())
        sticky = again._windows.get("n1")
        if sticky is None:
            again.open_note("n1")
            wait_until(lambda: "n1" in again._windows)
            sticky = again._windows["n1"]
        sticky.mainRequested.emit("n1")
        self.assertFalse(again.isMinimized())
        again._force_close = True
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
        self.window._hide_sticky("n1")
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
        self.window._hide_sticky("n1")
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

    def test_new_note_opens_as_visible(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        self.assertTrue(self.window._layout.notes["n1"].visible)

    def test_deleted_note_removes_the_sticky(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        self.assertIn("n1", self.window._layout.notes)
        self.reader.removed.add("n1")
        self.reader.bodies.pop("n1", None)
        self._stamp_value = 1
        self.window._watch()
        wait_until(lambda: "n1" not in self.window._windows and not self.window._threads)
        self.assertNotIn("n1", self.window._layout.notes)

    def test_open_restores_minimized_sticky(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        self.window.note_list.setCurrentRow(0)
        self.window.close_sticky("n1")
        sticky = self.window._windows["n1"]
        self.assertTrue(sticky.isMinimized())
        self.window.open_selected()
        self.assertFalse(sticky.isMinimized())

    def test_list_double_click_restores_minimized_sticky(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        self.window.note_list.setCurrentRow(0)
        self.window.close_sticky("n1")
        sticky = self.window._windows["n1"]
        item = self.window.note_list.currentItem()
        self.window._open_item(item)
        self.assertFalse(sticky.isMinimized())

    def test_open_shows_hidden_sticky(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        self.window.note_list.setCurrentRow(0)
        self.window._hide_sticky("n1")
        self.assertNotIn("n1", self.window._windows)
        self.window.open_selected()
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        self.assertTrue(self.window._layout.notes["n1"].visible)

    def test_main_close_button_minimizes_selected_sticky(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        self.window.show()
        self.window.note_list.setCurrentRow(0)
        sticky = self.window._windows["n1"]
        self.window.close_selected()
        self.assertTrue(sticky.isMinimized())
        self.assertTrue(self.window.isVisible())

    def test_main_window_close_asks_before_quitting(self):
        self.window.show()
        self.window._confirm_exit = lambda: False
        self.window.close()
        self.assertFalse(self.window._force_close)
        self.assertFalse(self.window._closed)

    def test_main_window_close_quits_when_confirmed(self):
        self.window.show()
        self.window._confirm_exit = lambda: True
        self.window.close()
        self.assertTrue(self.window._force_close)
        self.assertTrue(self.window._closed)

    def test_minimized_sticky_restores_on_update(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        sticky = self.window._windows["n1"]
        self.window.close_sticky("n1")
        self.assertTrue(sticky.isMinimized())
        self.window._seen_content["n1"] = ("題", "本文です")
        sticky._updated = False
        sticky._flicker_timer.stop()
        self.reader.bodies["n1"] = "更新後"
        self.window.show_note(LocalNote("n1", "題", "更新後", "nb"))
        self.assertFalse(sticky.isMinimized())
        self.assertTrue(sticky._flicker_timer.isActive())

    def test_visible_note_does_not_flicker_when_only_widget_text_differs(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        sticky = self.window._windows["n1"]
        nbsp_body = "a\u00a0b"
        self.reader.bodies["n1"] = nbsp_body
        self.window._seen_content["n1"] = ("題", nbsp_body)
        sticky.set_content("題", nbsp_body.replace("\u00a0", " "))
        sticky._updated = False
        sticky._flicker_timer.stop()
        self.window.show_note(LocalNote("n1", "題", nbsp_body, "nb"))
        self.assertFalse(sticky._flicker_timer.isActive())
        self.assertFalse(sticky._updated)

    def test_visible_note_flickers_when_seen_content_changes(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        sticky = self.window._windows["n1"]
        self.window._seen_content["n1"] = ("題", "本文です")
        sticky._updated = False
        sticky._flicker_timer.stop()
        self.reader.bodies["n1"] = "更新後"
        self.window.show_note(LocalNote("n1", "題", "更新後", "nb"))
        self.assertTrue(sticky._flicker_timer.isActive())


    def test_arrange_button_puts_the_pressed_sticky_at_the_top_right(self):
        wait_until(lambda: self.window.note_list.count() == 1)
        self.window.show_note(LocalNote("n1", "題", "本文です", "nb"))
        self.window.show_note(LocalNote("n2", "二つ目", "本文", "nb"))
        first = self.window._windows["n1"]
        second = self.window._windows["n2"]
        area = QApplication.primaryScreen().availableGeometry()
        rect = (area.x(), area.y(), area.width(), area.height())

        second.arrange_button.click()
        slots = arrange_positions([(second.width(), second.height()), (first.width(), first.height())], rect)
        self.assertEqual((second.x(), second.y()), slots[0])
        self.assertEqual((first.x(), first.y()), slots[1])
        self.assertEqual(second.x() + second.width(), area.x() + area.width() - 8)
        self.assertEqual(second.y(), area.y() + 8)

        first.arrange_button.click()
        slots = arrange_positions([(first.width(), first.height()), (second.width(), second.height())], rect)
        self.assertEqual((first.x(), first.y()), slots[0])
        self.assertEqual((second.x(), second.y()), slots[1])

    def test_watch_caches_config_parsing_until_file_changes(self):
        wait_until(lambda: self.window.note_list.count() == 1 and not self.window._threads)
        with mock.patch("everstickynote.ui.local_window.load_config", wraps=__import__("everstickynote.notebook_config", fromlist=["load_config"]).load_config) as spy:
            self.window._watch()
            self.window._watch()
            self.window._watch()
            self.assertEqual(spy.call_count, 0)

            self.config_path.write_text('notebooks = ["仕事"]\nwatch_seconds = 5\n', encoding="utf-8")
            self.window._watch()
            self.assertEqual(spy.call_count, 1)
            self.assertEqual(self.window._watch_seconds, 5.0)
            self.assertEqual(self.window._timer.interval(), 5000)

    def test_resize_debounce_flushes_when_closing_sticky_or_main(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        sticky = self.window._windows["n1"]
        sticky.resize(410, 310)
        QApplication.processEvents()
        self.assertTrue(sticky._resize_timer.isActive())
        self.window.close_sticky("n1")
        self.assertFalse(sticky._resize_timer.isActive())
        self.assertEqual(self.window._layout.notes["n1"].width, 410)
        self.assertEqual(self.window._layout.notes["n1"].height, 310)

        self.window.open_note("n1")
        sticky.resize(450, 330)
        QApplication.processEvents()
        self.window._force_close = True
        self.window.close()
        self.assertEqual(self.window._layout.notes["n1"].width, 450)
        self.assertEqual(self.window._layout.notes["n1"].height, 330)

    def test_multiple_notebooks_offer_all_option_and_monitor_across_notebooks(self):
        wait_until(lambda: self.window.note_list.count() == 1 and not self.window._threads)
        self.config_path.write_text('notebooks = ["仕事", "個人"]\n', encoding="utf-8")
        self.window.reload()
        wait_until(lambda: self.window.note_list.count() == 2 and not self.window._threads)
        self.assertEqual(self.window.notebook_combo.count(), 3)
        self.assertEqual(self.window.notebook_combo.itemText(0), "すべてのノートブック")
        self.assertEqual(self.window.notebook_combo.itemData(0), ALL_NOTEBOOKS_ID)
        self.assertIn("n1", self.window._windows)
        self.assertIn("secret", self.window._windows)

        # Switch combo filter to 仕事 only; 個人 ("secret") must still stay monitored & flicker on update
        self.window.notebook_combo.setCurrentIndex(1)
        wait_until(lambda: self.window.note_list.count() == 1 and not self.window._threads)
        self.window._hide_sticky("secret")
        self.assertNotIn("secret", self.window._windows)

        self.reader.bodies["secret"] = "個人ノート更新"
        self._stamp_value = 2
        self.window._watch()
        wait_until(lambda: "secret" in self.window._windows and not self.window._threads)
        self.assertEqual(self.window._windows["secret"].note_text(), "個人ノート更新")
        self.assertIn("3px solid", self.window._windows["secret"].styleSheet())

    def test_arrange_stickies_uses_pressed_sticky_monitor(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        self.window.show_note(LocalNote("n2", "二つ目", "本文", "nb"))
        first = self.window._windows["n1"]
        second = self.window._windows["n2"]
        second_monitor = QRect(1920, 0, 1920, 1080)

        class FakeScreen:
            def availableGeometry(self):
                return second_monitor

        with mock.patch.object(second, "screen", return_value=FakeScreen()):
            second.arrange_button.click()

        slots = arrange_positions(
            [(second.width(), second.height()), (first.width(), first.height())],
            (second_monitor.x(), second_monitor.y(), second_monitor.width(), second_monitor.height()),
        )
        self.assertEqual((second.x(), second.y()), slots[0])
        self.assertEqual((first.x(), first.y()), slots[1])
        self.assertEqual(second.x() + second.width(), second_monitor.x() + second_monitor.width() - 8)

    def test_settings_dialog_keeps_missing_notebooks_and_applies_immediately(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        self.config_path.write_text(
            '# 設定コメント\nnotebooks = ["仕事", "行方不明"]\nwatch_seconds = 2\ndefault_notebook = "未検出Inbox"\n',
            encoding="utf-8",
        )
        self.window.reload()
        wait_until(lambda: not self.window._threads)
        config = self.window._load_app_config(force=True)
        dialog = SettingsDialog(self.window._all_notebooks, config, parent=self.window)
        names = [
            dialog.notebook_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(dialog.notebook_list.count())
        ]
        self.assertEqual(names, ["仕事", "個人", "行方不明"])
        default_items = [
            dialog.default_notebook_combo.itemData(i)
            for i in range(dialog.default_notebook_combo.count())
        ]
        self.assertEqual(default_items, ["", "仕事", "個人", "未検出Inbox"])
        self.assertEqual(dialog.default_notebook(), "未検出Inbox")
        self.assertIn("デフォルトのノートブック", dialog.notice_label.text())

        # Check "個人" (index 1), keep "行方不明" checked, and set default_notebook to "個人"
        dialog.notebook_list.item(1).setCheckState(Qt.CheckState.Checked)
        dialog.watch_spin.setValue(4.0)
        dialog.flicker_spin.setValue(1.5)
        dialog.close_after_flicker_check.setChecked(False)
        dialog.default_notebook_combo.setCurrentIndex(2)
        self.assertEqual(dialog.notebook_list.item(1).checkState(), Qt.CheckState.Unchecked)
        self.assertNotIn("個人", dialog.selected_notebooks())

        self.window.apply_settings(
            notebooks=dialog.selected_notebooks(),
            watch_seconds=dialog.watch_seconds(),
            flicker_seconds=dialog.flicker_seconds(),
            close_after_flicker=dialog.close_after_flicker(),
            default_notebook=dialog.default_notebook(),
        )
        wait_until(lambda: not self.window._threads)
        self.assertNotIn("secret", self.window._windows)
        self.assertEqual(self.window._watch_seconds, 4.0)
        self.assertEqual(self.window._flicker_seconds, 1.5)
        self.assertFalse(self.window._close_after_flicker)
        self.assertEqual(self.window._default_notebook_name, "個人")
        saved_text = self.config_path.read_text(encoding="utf-8")
        self.assertIn("# 設定コメント", saved_text)
        self.assertIn('"行方不明"', saved_text)
        self.assertIn('default_notebook = "個人"', saved_text)

        # Even if config.toml manually lists "個人" in BOTH notebooks and default_notebook,
        # default_notebook filtering takes precedence and does NOT show pre-existing "secret"
        self.window.apply_settings(
            notebooks=["仕事", "個人"],
            watch_seconds=4.0,
            flicker_seconds=1.5,
            close_after_flicker=False,
            default_notebook="個人",
        )
        wait_until(lambda: not self.window._threads)
        self.assertNotIn("secret", self.window._windows)

    def test_create_new_note_passes_enex_via_os_and_shows_notice(self):
        wait_until(lambda: self.window.note_list.count() == 1 and not self.window._threads)
        written = self.window.create_new_note("テスト題名", "本文1行目\n本文2行目")
        self.assertIsNotNone(written)
        self.assertEqual(self.opened_enex, [written])
        self.assertTrue(written.exists())
        xml_content = written.read_text(encoding="utf-8")
        self.assertIn("<title>テスト題名</title>", xml_content)
        self.assertIn("<div>本文1行目</div><div>本文2行目</div>", xml_content)
        if written.exists():
            written.unlink()

    def test_new_note_dialog_shows_notice_and_tray_and_sticky_menus_trigger_it(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        # Notice without default_notebook
        unset_dialog = NewNoteDialog(default_notebook="", parent=self.window)
        self.assertIn("設定", unset_dialog.notice_label.text())

        # Notice with default_notebook
        set_dialog = NewNoteDialog(default_notebook="0. Inbox", parent=self.window)
        self.assertIn("0. Inbox", set_dialog.notice_label.text())
        set_dialog.title_edit.setText("ダイアログ題")
        set_dialog.body_edit.setPlainText("ダイアログ本文")
        set_dialog.create_button.click()
        self.assertEqual(set_dialog.result(), QDialog.DialogCode.Accepted)

        # Tray menu includes 新規作成 and triggers open_new_note_dialog
        self.assertIsNotNone(self.window._tray_menu)
        tray_actions = {action.text(): action for action in self.window._tray_menu.actions()}
        self.assertIn("メインフォームを開く", tray_actions)
        self.assertIn("新規作成", tray_actions)
        self.assertIn("終了", tray_actions)

        with mock.patch("everstickynote.ui.local_window.NewNoteDialog", return_value=set_dialog):
            with mock.patch.object(set_dialog, "exec", return_value=QDialog.DialogCode.Accepted):
                tray_actions["新規作成"].trigger()
        self.assertEqual(len(self.opened_enex), 1)
        self.assertIn("<title>ダイアログ題</title>", self.opened_enex[0].read_text(encoding="utf-8"))
        if self.opened_enex[0].exists():
            self.opened_enex[0].unlink()

        # Sticky right-click menu includes 新規作成 and triggers open_new_note_dialog
        sticky = self.window._windows["n1"]
        sticky_actions = {action.text(): action for action in sticky._build_context_menu().actions()}
        self.assertIn("新規作成", sticky_actions)
        with mock.patch("everstickynote.ui.local_window.NewNoteDialog", return_value=set_dialog):
            with mock.patch.object(set_dialog, "exec", return_value=QDialog.DialogCode.Accepted):
                sticky_actions["新規作成"].trigger()
        self.assertEqual(len(self.opened_enex), 2)
        if self.opened_enex[1].exists():
            self.opened_enex[1].unlink()

    def test_default_notebook_tracks_only_app_created_notes_across_restart_and_move(self):
        wait_until(lambda: "n1" in self.window._windows and not self.window._threads)
        self.window.apply_settings(
            notebooks=["仕事"],
            watch_seconds=2.0,
            flicker_seconds=5.0,
            close_after_flicker=True,
            default_notebook="個人",
        )
        wait_until(lambda: not self.window._threads)

        # Pre-existing note in default_notebook ("secret") must NOT appear
        self.assertNotIn("secret", self.window._windows)
        self.assertEqual(self.window.note_list.count(), 1)

        # Create a new note from the app
        enex_path = self.window.create_new_note("Inbox新メモ", "新規本文")
        self.assertIsNotNone(enex_path)
        if enex_path.exists():
            enex_path.unlink()

        # Unrelated note AND the created note both appear in default_notebook ("other")
        self.reader.titles["external"] = "他アプリからのメール"
        self.reader.bodies["external"] = "無関係"
        self.reader.note_notebooks["external"] = "other"
        self.reader.titles["created-1"] = "Inbox新メモ"
        self.reader.bodies["created-1"] = "新規本文"
        self.reader.note_notebooks["created-1"] = "other"
        self._stamp_value = 10
        self.window._watch()
        wait_until(lambda: "created-1" in self.window._windows and not self.window._threads)

        # Only created-1 appears; secret and external stay hidden
        self.assertNotIn("secret", self.window._windows)
        self.assertNotIn("external", self.window._windows)
        self.assertEqual(self.window.note_list.count(), 2)
        self.assertIn("created-1", self.store.get_tracked_created_notes())

        # Save custom geometry and color on created-1, then restart window
        created_sticky = self.window._windows["created-1"]
        created_sticky.move(410, 210)
        created_sticky.resize(350, 250)
        created_sticky.set_color("blue")
        self.window._save_geometry("created-1")
        self.window._force_close = True
        self.window.close()

        restarted = self._open_window()
        wait_until(lambda: "created-1" in restarted._windows and not restarted._threads)
        self.assertNotIn("secret", restarted._windows)
        self.assertNotIn("external", restarted._windows)
        restored = restarted._windows["created-1"]
        self.assertEqual((restored.x(), restored.y(), restored.width(), restored.height()), (410, 210, 350, 250))
        self.assertEqual(restored.color(), "blue")

        # Move created-1 from default_notebook ("other") to regular notebook ("nb")
        self.reader.note_notebooks["created-1"] = "nb"
        self._stamp_value = 11
        restarted._watch()
        wait_until(lambda: restarted._watched_stamp == 11 and not restarted._threads)
        self.assertIn("created-1", restarted._windows)
        self.assertIs(restarted._windows["created-1"], restored)
        self.assertEqual((restored.x(), restored.y(), restored.width(), restored.height()), (410, 210, 350, 250))
        self.assertEqual(restarted._window_notebooks["created-1"], "nb")

if __name__ == "__main__":
    unittest.main()