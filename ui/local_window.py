"""Read-only sticky notes loaded from the local Evernote desktop database."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from local_notes import LocalEvernote, LocalNote, LocalNoteSummary, LocalNotebook
from local_store import LocalStore
from notebook_config import (
    NotebookConfigError,
    default_config_path,
    load_notebook_names,
    select_notebooks,
)
from ui.jobs import start_async
from ui.sticky_window import StickyWindow
from window_position import NotePosition, default_position_path, load_layout, save_layout

READ_ONLY_MESSAGE = "読み取り専用です。編集はEvernoteで行い、更新で取り込みます。"


def open_local_reader() -> LocalEvernote:
    reader = LocalEvernote()
    reader.open()
    return reader


def open_evernote_url(url: str) -> None:
    if QDesktopServices.openUrl(QUrl(url)):
        return
    if os.name == "nt":
        os.startfile(url)
        return
    raise OSError("Evernoteでノートを開けませんでした")


class LocalMainWindow(QWidget):
    # def __init__(self, store: LocalStore | None = None, opener=None):
    # 2026/09/23 変更 ---＞
    # def __init__(self, store: LocalStore | None = None, opener=None, config_path=None):
    # <--- 2026/09/23 変更
    # 2026/09/23 変更 ---＞
    # def __init__(self, store: LocalStore | None = None, opener=None, config_path=None, url_opener=None):
    # <--- 2026/09/23 変更
    # 2026/09/23 変更 ---＞
    def __init__(
        self,
        store: LocalStore | None = None,
        opener=None,
        config_path=None,
        url_opener=None,
        position_path=None,
    ):
    # <--- 2026/09/23 変更
        super().__init__()
        self.setWindowTitle("EverStickyNote")
        self.resize(440, 560)
        self._store = store or LocalStore()
        self._opener = opener or open_local_reader
        # 2026/09/23 変更 ---＞
        self._url_opener = url_opener or open_evernote_url
        # <--- 2026/09/23 変更
        # 2026/09/23 変更 ---＞
        self._config_path = config_path or default_config_path()
        self._position_path = position_path or default_position_path()
        self._layout = load_layout(self._position_path)
        # <--- 2026/09/23 変更
        self._reader: LocalEvernote | None = None
        self._notebooks: list[LocalNotebook] = []
        self._allowed_notebook_ids: set[str] = set()
        self._notes: list[LocalNoteSummary] = []
        self._windows: dict[str, StickyWindow] = {}
        self._window_notebooks: dict[str, str] = {}
        self._threads: list = []
        self._notebook_id = ""
        self._generation = 0
        self._build()
        self.reload()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        # hint = QLabel(READ_ONLY_MESSAGE)
        # hint.setWordWrap(True)
        # root.addWidget(hint)
        # 2026/09/23 変更 ---＞
        # <--- 2026/09/23 変更

        row = QHBoxLayout()
        self.notebook_combo = QComboBox()
        self.notebook_combo.currentIndexChanged.connect(self._on_notebook_changed)
        row.addWidget(self.notebook_combo, 1)
        self.refresh_button = QPushButton("更新")
        self.refresh_button.clicked.connect(self.reload)
        row.addWidget(self.refresh_button)
        root.addLayout(row)

        self.note_list = QListWidget()
        self.note_list.itemDoubleClicked.connect(self._open_item)
        root.addWidget(self.note_list, 1)

        buttons = QHBoxLayout()
        self.open_button = QPushButton("開く")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_selected)
        self.close_button = QPushButton("閉じる")
        self.close_button.clicked.connect(self.close_selected)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)

        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    def reload(self) -> None:
        self._generation += 1
        generation = self._generation
        self.refresh_button.setEnabled(False)
        self._set_status("Evernoteのローカルデータを読み込んでいます")

        def work():
            if self._reader is None:
                reader = self._opener()
            else:
                reader = self._reader
                reader.open()
            return reader, reader.list_notebooks()

        def ok(payload, gen=generation):
            self.refresh_button.setEnabled(True)
            if gen != self._generation:
                return
            reader, notebooks = payload
            self._reader = reader
            self._show_notebooks(notebooks)

        def err(message, gen=generation):
            self.refresh_button.setEnabled(True)
            if gen != self._generation:
                return
            self._on_error(message)

        self._submit(work, ok, err)

    # def _show_notebooks(self, notebooks: list[LocalNotebook]) -> None:
    #     self._notebooks = notebooks
    #     saved = self._store.get_notebook_guid()
    #     self.notebook_combo.blockSignals(True)
    #     self.notebook_combo.clear()
    #     for notebook in notebooks:
    #         self.notebook_combo.addItem(notebook.name, notebook.id)
    #     index = 0
    #     for row in range(self.notebook_combo.count()):
    #         if self.notebook_combo.itemData(row) == saved:
    #             index = row
    #             break
    #     self.notebook_combo.setCurrentIndex(index if notebooks else -1)
    #     self.notebook_combo.blockSignals(False)
    #     if not notebooks:
    #         self._notes = []
    #         self._fill_list()
    #         self.open_button.setEnabled(False)
    #         self._set_status("ノートブックがありません")
    #         return
    #     self.open_button.setEnabled(True)
    #     self._notebook_id = self.notebook_combo.currentData()
    #     self._store.set_notebook_guid(self._notebook_id)
    #     self._load_notes(self._notebook_id)
    # 2026/09/23 変更 ---＞
    def _show_notebooks(self, notebooks: list[LocalNotebook]) -> None:
        try:
            names = load_notebook_names(self._config_path)
        except NotebookConfigError as exc:
            self._allowed_notebook_ids = set()
            self._close_disallowed()
            self._notes = []
            self._fill_list()
            self.notebook_combo.clear()
            self.open_button.setEnabled(False)
            self._set_status(str(exc))
            return
        matched, missing = select_notebooks(notebooks, names)
        self._notebooks = matched
        self._allowed_notebook_ids = {notebook.id for notebook in matched}
        self._close_disallowed()
        saved = self._store.get_notebook_guid()
        self.notebook_combo.blockSignals(True)
        self.notebook_combo.clear()
        for notebook in matched:
            self.notebook_combo.addItem(notebook.name, notebook.id)
        index = 0
        for row in range(self.notebook_combo.count()):
            if self.notebook_combo.itemData(row) == saved:
                index = row
                break
        self.notebook_combo.setCurrentIndex(index if matched else -1)
        self.notebook_combo.blockSignals(False)
        if not names:
            self._notes = []
            self._fill_list()
            self.open_button.setEnabled(False)
            self._set_status(
                f"config.toml の notebooks にノートブック名を書いてください ({self._config_path})"
            )
            return
        if not matched:
            self._notes = []
            self._fill_list()
            self.open_button.setEnabled(False)
            self._set_status("設定したノートブックが見つかりません: " + "、".join(missing))
            return
        self.open_button.setEnabled(True)
        self._notebook_id = self.notebook_combo.currentData()
        self._store.set_notebook_guid(self._notebook_id)
        if missing:
            self._set_status("見つからないノートブックがあります: " + "、".join(missing))
        self._load_notes(self._notebook_id)
    # <--- 2026/09/23 変更

    def _close_disallowed(self) -> None:
        for note_id, notebook_id in list(self._window_notebooks.items()):
            if notebook_id not in self._allowed_notebook_ids:
                self.close_sticky(note_id)

    def _on_notebook_changed(self, index: int) -> None:
        notebook_id = self.notebook_combo.itemData(index)
        if not notebook_id or notebook_id == self._notebook_id:
            return
        self._notebook_id = notebook_id
        self._store.set_notebook_guid(notebook_id)
        self._load_notes(notebook_id)

    def _load_notes(self, notebook_id: str) -> None:
        self._generation += 1
        generation = self._generation

        def work():
            return self._reader.list_notes(notebook_id)

        def ok(notes, gen=generation):
            if gen != self._generation:
                return
            self._notes = notes
            self._fill_list()
            self._set_status(f"{len(notes)}件")
            open_ids = [
                note.id
                for note in notes
                if note.id in self._windows or self._store.get_note_state(note.id).is_open
            ]
            if open_ids:
                self._fetch_notes(open_ids, gen)

        self._submit(work, ok, self._on_error)

    def open_selected(self) -> None:
        note_id = self._selected_id()
        if note_id:
            self.open_note(note_id)

    def close_selected(self) -> None:
        note_id = self._selected_id()
        if note_id:
            self.close_sticky(note_id)

    def _open_item(self, item: QListWidgetItem) -> None:
        note_id = item.data(Qt.ItemDataRole.UserRole)
        if note_id:
            self.open_note(note_id)

    def open_note(self, note_id: str) -> None:
        if self._reader is None:
            return
        window = self._windows.get(note_id)
        if window is not None:
            window.show()
            window.raise_()
            window.activateWindow()
            self._store.set_open(note_id, True)
            self._fill_list()
            return
        self._fetch_notes([note_id], self._generation)

    def _fetch_notes(self, note_ids: list[str], generation: int) -> None:
        def work(ids=list(note_ids)):
            return [self._reader.get_note(note_id) for note_id in ids]

        def ok(notes, gen=generation):
            if gen != self._generation and len(note_ids) != 1:
                return
            for note in notes:
                self.show_note(note)

        self._submit(work, ok, self._on_error)

    def show_note(self, note: LocalNote) -> None:
        window = self._windows.get(note.id)
        if window is None:
            state = self._store.get_note_state(note.id)
            window = StickyWindow(note.id, color=state.color, pinned=state.pinned)
            window.set_read_only(READ_ONLY_MESSAGE)
            window.closeRequested.connect(self.close_sticky)
            window.colorChanged.connect(self._on_color_changed)
            window.pinChanged.connect(self._on_pin_changed)
            window.geometryChanged.connect(self._save_geometry)
            # 2026/09/23 変更 ---＞
            window.openRequested.connect(self.open_in_evernote)
            # <--- 2026/09/23 変更
            self._windows[note.id] = window
            # window.place(state.x, state.y, state.width, state.height, len(self._windows) - 1)
            # 2026/09/23 変更 ---＞
            saved = self._layout.notes.get(note.id)
            if saved is None:
                window.place(state.x, state.y, state.width, state.height, len(self._windows) - 1)
            else:
                window.place(saved.x, saved.y, saved.width, saved.height, len(self._windows) - 1)
            # <--- 2026/09/23 変更
            window.show()
        window.set_content(note.title, note.text)
        window.set_read_only(READ_ONLY_MESSAGE)
        self._window_notebooks[note.id] = note.notebook_id
        self._store.set_open(note.id, True)
        self._fill_list()

    def open_in_evernote(self, note_id: str) -> None:
        if self._reader is None:
            return
        try:
            url = self._reader.note_app_url(note_id)
            self._url_opener(url)
        except Exception as exc:
            self._set_status(str(exc) or "Evernoteでノートを開けませんでした")

    def close_sticky(self, note_id: str) -> None:
        window = self._windows.get(note_id)
        if window is not None:
            self._save_geometry(note_id)
            state = self._store.get_note_state(note_id)
            state.is_open = False
            self._store.save_note_state(state)
            window.hide()
            window.deleteLater()
            del self._windows[note_id]
            self._window_notebooks.pop(note_id, None)
        self._fill_list()

    def _fill_list(self) -> None:
        selected = self._selected_id()
        self.note_list.clear()
        for note in self._notes:
            prefix = "● " if note.id in self._windows else ""
            item = QListWidgetItem(f"{prefix}{note.title}")
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            self.note_list.addItem(item)
            if note.id == selected:
                self.note_list.setCurrentItem(item)

    def _selected_id(self) -> str:
        item = self.note_list.currentItem()
        if item is None:
            return ""
        return item.data(Qt.ItemDataRole.UserRole) or ""

    def _on_color_changed(self, note_id: str, color: str) -> None:
        state = self._store.get_note_state(note_id)
        state.color = color
        state.is_open = note_id in self._windows
        self._store.save_note_state(state)

    def _on_pin_changed(self, note_id: str, pinned: bool) -> None:
        state = self._store.get_note_state(note_id)
        state.pinned = pinned
        state.is_open = note_id in self._windows
        self._store.save_note_state(state)

    # def _save_geometry(self, note_id: str) -> None:
    #     window = self._windows.get(note_id)
    #     if window is None:
    #         return
    #     state = self._store.get_note_state(note_id)
    #     state.x = window.x()
    #     state.y = window.y()
    #     state.width = window.width()
    #     state.height = window.height()
    #     state.color = window.color()
    #     state.pinned = window.pinned()
    #     state.is_open = True
    #     self._store.save_note_state(state)
    # 2026/09/23 変更 ---＞
    def _save_geometry(self, note_id: str) -> None:
        window = self._windows.get(note_id)
        if window is None:
            return
        if window.x() <= -32000 or window.y() <= -32000:
            return
        state = self._store.get_note_state(note_id)
        state.x = window.x()
        state.y = window.y()
        state.width = window.width()
        state.height = window.height()
        state.color = window.color()
        state.pinned = window.pinned()
        state.is_open = True
        self._store.save_note_state(state)
        self._layout.notes[note_id] = NotePosition(
            x=window.x(),
            y=window.y(),
            width=window.width(),
            height=window.height(),
        )
        save_layout(self._position_path, self._layout)
    # <--- 2026/09/23 変更

    def _submit(self, func, on_ok, on_err) -> None:
        thread = start_async(self, func, on_ok, on_err)
        self._threads.append(thread)

        def finished(done=thread):
            if done in self._threads:
                self._threads.remove(done)

        thread.finished.connect(finished)
        thread.start()

    def _on_error(self, message: str) -> None:
        self._set_status(message)

    def _set_status(self, message: str) -> None:
        self.status.setText(message)

    # def closeEvent(self, event):
    #     for note_id in list(self._windows):
    #         self.close_sticky(note_id)
    #     if self._reader is not None:
    #         self._reader.close()
    #     super().closeEvent(event)
    # 2026/09/23 変更 ---＞
    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "_layout"):
            self._remember_minimized(self.isMinimized())

    def show_saved_state(self) -> None:
        if self._layout.minimized:
            self.showMinimized()
        else:
            self.show()

    def closeEvent(self, event):
        self._remember_minimized(self.isMinimized())
        for note_id in list(self._windows):
            self.close_sticky(note_id)
        if self._reader is not None:
            self._reader.close()
        super().closeEvent(event)

    def _remember_minimized(self, minimized: bool) -> None:
        self._layout.minimized = bool(minimized)
        save_layout(self._position_path, self._layout)
    # <--- 2026/09/23 変更
