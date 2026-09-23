"""Notebook list and the sticky windows that edit its notes."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from evernote_client import EvernoteClient, NoteDetail, NoteSummary
from local_store import LocalStore
from sync import (
    RichNoteBlocked,
    build_update_content,
    classify_remote_change,
    normalize_title,
    parse_note_body,
    text_to_enml,
)
from ui.jobs import start_async
from ui.sticky_window import StickyWindow

POLL_MS = 60_000
SAVE_MS = 1200


@dataclass
class Session:
    guid: str
    title: str
    text: str
    usn: int
    rich: bool
    synced_title: str
    synced_text: str
    original_enml: str
    conflict: bool = False
    remote_title: str = ""
    remote_text: str = ""
    remote_usn: int = 0
    remote_enml: str = ""


def default_client_factory(token: str) -> EvernoteClient:
    client = EvernoteClient(token)
    client.connect()
    return client


class MainWindow(QWidget):
    def __init__(self, store: LocalStore | None = None, client_factory=None):
        super().__init__()
        self.setWindowTitle("EverStickyNote")
        self.resize(440, 560)
        self._store = store or LocalStore()
        self._client_factory = client_factory or default_client_factory
        self._client: EvernoteClient | None = None
        self._notebook_guid = ""
        self._summaries: list[NoteSummary] = []
        self._sessions: dict[str, Session] = {}
        self._windows: dict[str, StickyWindow] = {}
        self._save_timers: dict[str, QTimer] = {}
        self._threads: list = []
        self._saving: set[str] = set()
        self._resave: set[str] = set()
        self._generation = 0
        self._build()
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self.poll_notes)
        token = self._store.get_token().strip()
        if token:
            self.token_edit.setText(token)
            self.connect_token(token)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        connect_page = QWidget()
        connect_layout = QVBoxLayout(connect_page)
        hint = QLabel(
            'Evernoteの開発者トークンを入力します。'
            '<a href="https://www.evernote.com/api/DeveloperToken.action">発行ページ</a>'
        )
        hint.setOpenExternalLinks(True)
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        connect_layout.addWidget(hint)
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("開発者トークン")
        connect_layout.addWidget(self.token_edit)
        self.connect_button = QPushButton("接続")
        self.connect_button.clicked.connect(lambda: self.connect_token(self.token_edit.text()))
        connect_layout.addWidget(self.connect_button)
        connect_layout.addStretch(1)
        self.stack.addWidget(connect_page)

        notes_page = QWidget()
        notes_layout = QVBoxLayout(notes_page)
        notebook_row = QHBoxLayout()
        self.notebook_combo = QComboBox()
        self.notebook_combo.currentIndexChanged.connect(self._on_notebook_changed)
        notebook_row.addWidget(self.notebook_combo, 1)
        self.refresh_button = QPushButton("更新")
        self.refresh_button.clicked.connect(self.reload_notebook)
        notebook_row.addWidget(self.refresh_button)
        notes_layout.addLayout(notebook_row)

        self.note_list = QListWidget()
        self.note_list.itemDoubleClicked.connect(self._open_item)
        notes_layout.addWidget(self.note_list, 1)

        button_row = QHBoxLayout()
        self.open_button = QPushButton("開く")
        self.open_button.clicked.connect(self.open_selected)
        self.close_button = QPushButton("閉じる")
        self.close_button.clicked.connect(self.close_selected)
        self.new_button = QPushButton("新しいノート")
        self.new_button.clicked.connect(self.create_note)
        button_row.addWidget(self.open_button)
        button_row.addWidget(self.close_button)
        button_row.addWidget(self.new_button)
        notes_layout.addLayout(button_row)

        self.token_button = QPushButton("トークンを変更")
        self.token_button.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        notes_layout.addWidget(self.token_button)
        self.stack.addWidget(notes_page)

    def connect_token(self, token: str) -> None:
        cleaned = token.strip()
        if not cleaned:
            self._set_status("トークンを入力してください")
            return
        self._store.set_token(cleaned)
        self._set_status("接続しています")
        self.connect_button.setEnabled(False)

        def work():
            return self._client_factory(cleaned)

        def ok(client):
            self.connect_button.setEnabled(True)
            self._client = client
            self._set_status("ノートブックを読み込んでいます")
            self._submit(client.list_notebooks, self._on_notebooks, self._on_error)

        def err(message):
            self.connect_button.setEnabled(True)
            self._on_error(message)

        self._submit(work, ok, err)

    def _on_notebooks(self, notebooks) -> None:
        self.notebook_combo.blockSignals(True)
        self.notebook_combo.clear()
        for notebook in notebooks:
            self.notebook_combo.addItem(notebook.name, notebook.guid)
        saved = self._store.get_notebook_guid()
        index = 0
        for row in range(self.notebook_combo.count()):
            if self.notebook_combo.itemData(row) == saved:
                index = row
                break
        self.notebook_combo.setCurrentIndex(index if self.notebook_combo.count() else -1)
        self.notebook_combo.blockSignals(False)
        self.stack.setCurrentIndex(1)
        self._poll.start()
        if self.notebook_combo.count() == 0:
            self._set_status("ノートブックがありません")
            return
        self._notebook_guid = self.notebook_combo.currentData()
        self._store.set_notebook_guid(self._notebook_guid)
        self._load_notebook(self._notebook_guid)

    def _on_notebook_changed(self, index: int) -> None:
        guid = self.notebook_combo.itemData(index)
        if not guid or guid == self._notebook_guid:
            return
        for open_guid in list(self._windows):
            self.close_sticky(open_guid, save=True)
        self._notebook_guid = guid
        self._store.set_notebook_guid(guid)
        self._load_notebook(guid)

    def reload_notebook(self) -> None:
        if self._notebook_guid:
            self._load_notebook(self._notebook_guid)

    def _load_notebook(self, notebook_guid: str) -> None:
        self._generation += 1
        generation = self._generation

        def work():
            return self._client.list_notes(notebook_guid)

        def ok(summaries, gen=generation):
            if gen != self._generation:
                return
            self._summaries = summaries
            self._fill_list()
            open_guids = [
                summary.guid
                for summary in summaries
                if self._store.get_note_state(summary.guid).is_open
            ]
            self._set_status(f"{len(summaries)}件")
            if not open_guids:
                return

            def fetch(guids=list(open_guids)):
                return [self._client.get_note(guid) for guid in guids]

            def opened(details, fetch_gen=gen):
                if fetch_gen != self._generation:
                    return
                for detail in details:
                    self.show_detail(detail)

            self._submit(fetch, opened, self._on_error)

        self._submit(work, ok, self._on_error)

    def poll_notes(self) -> None:
        if self._client is None or not self._notebook_guid:
            return
        notebook_guid = self._notebook_guid
        watched = {
            guid: self._sessions[guid].usn
            for guid in self._windows
            if guid in self._sessions and guid not in self._saving
        }
        generation = self._generation

        def work():
            summaries = self._client.list_notes(notebook_guid)
            by_guid = {item.guid: item for item in summaries}
            changed = []
            missing = []
            for guid, usn in watched.items():
                summary = by_guid.get(guid)
                if summary is None:
                    missing.append(guid)
                    continue
                if summary.update_sequence_num != usn:
                    changed.append(self._client.get_note(guid))
            return summaries, changed, missing

        def ok(payload, gen=generation):
            if gen != self._generation:
                return
            summaries, changed, missing = payload
            self._summaries = summaries
            self._fill_list()
            for guid in missing:
                self._set_status("Evernote上から削除されたノートを閉じました")
                self.close_sticky(guid, save=False)
            for detail in changed:
                self._consider_remote(detail)

        self._submit(work, ok, self._on_error)

    def open_selected(self) -> None:
        guid = self._selected_guid()
        if guid:
            self.open_note(guid)

    def close_selected(self) -> None:
        guid = self._selected_guid()
        if guid:
            self.close_sticky(guid, save=True)

    def _open_item(self, item: QListWidgetItem) -> None:
        guid = item.data(Qt.ItemDataRole.UserRole)
        if guid:
            self.open_note(guid)

    def open_note(self, guid: str) -> None:
        window = self._windows.get(guid)
        if window is not None:
            window.show()
            window.raise_()
            window.activateWindow()
            self._store.set_open(guid, True)
            self._fill_list()
            return
        session = self._sessions.get(guid)
        if session is not None and (session.conflict or self._is_dirty(session)):
            self._open_window(session)
            return

        def work(note_guid=guid):
            return self._client.get_note(note_guid)

        self._submit(work, self.show_detail, self._on_error)

    def show_detail(self, detail: NoteDetail) -> None:
        text, rich = parse_note_body(detail.content)
        title = detail.title or "無題"
        session = Session(
            guid=detail.guid,
            title=title,
            text=text,
            usn=detail.update_sequence_num,
            rich=rich,
            synced_title=title,
            synced_text=text,
            original_enml=detail.content,
        )
        self._sessions[detail.guid] = session
        self._store.set_last_usn(detail.guid, detail.update_sequence_num)
        if not any(item.guid == detail.guid for item in self._summaries):
            self._summaries.append(
                NoteSummary(
                    guid=detail.guid,
                    title=title,
                    update_sequence_num=detail.update_sequence_num,
                    notebook_guid=detail.notebook_guid or self._notebook_guid,
                )
            )
        self._open_window(session)

    def _open_window(self, session: Session) -> None:
        existing = self._windows.get(session.guid)
        if existing is not None:
            existing.show()
            existing.raise_()
            return
        state = self._store.get_note_state(session.guid)
        window = StickyWindow(session.guid, color=state.color, pinned=state.pinned)
        window.set_content(session.title, session.text)
        window.set_rich(session.rich)
        window.set_conflict(session.conflict)
        window.edited.connect(self._on_edited)
        window.closeRequested.connect(lambda guid: self.close_sticky(guid, save=True))
        window.colorChanged.connect(self._on_color_changed)
        window.pinChanged.connect(self._on_pin_changed)
        window.geometryChanged.connect(self._save_geometry)
        window.pullRequested.connect(self.pull_remote)
        self._windows[session.guid] = window
        window.place(state.x, state.y, state.width, state.height, len(self._windows) - 1)
        window.show()
        self._store.set_open(session.guid, True)
        self._fill_list()

    def close_sticky(self, guid: str, save: bool = True, sync: bool = False) -> None:
        timer = self._save_timers.get(guid)
        if timer is not None:
            timer.stop()
        window = self._windows.get(guid)
        session = self._sessions.get(guid)
        if window is not None and session is not None:
            session.title = window.note_title()
            session.text = window.note_text()
        if save and sync:
            self._save_blocking(guid)
        elif save:
            self.save_note(guid)
        if window is not None:
            self._save_geometry(guid)
            state = self._store.get_note_state(guid)
            state.is_open = False
            self._store.save_note_state(state)
            window.hide()
            window.deleteLater()
            del self._windows[guid]
        self._fill_list()

    def create_note(self) -> None:
        if self._client is None or not self._notebook_guid:
            return
        notebook_guid = self._notebook_guid
        title = "新しいノート"
        content = text_to_enml("")

        def work():
            return self._client.create_note(notebook_guid, title, content)

        self.new_button.setEnabled(False)

        def ok(detail):
            self.new_button.setEnabled(True)
            self.show_detail(detail)

        def err(message):
            self.new_button.setEnabled(True)
            self._on_error(message)

        self._submit(work, ok, err)

    def save_note(self, guid: str) -> None:
        if guid in self._saving:
            self._resave.add(guid)
            return
        if self._client is None:
            return
        window = self._windows.get(guid)
        session = self._sessions.get(guid)
        if window is None or session is None:
            return
        if session.rich or session.conflict:
            return
        title = normalize_title(window.note_title())
        text = window.note_text()
        if title == session.synced_title and text == session.synced_text:
            return
        try:
            content = build_update_content(session.original_enml, text)
        except RichNoteBlocked:
            session.rich = True
            window.set_rich(True)
            return
        expected_usn = session.usn
        self._saving.add(guid)

        def work(note_guid=guid, note_title=title, note_content=content, usn=expected_usn):
            return self._client.update_note_if_usn_matches(
                note_guid, note_title, note_content, usn
            )

        def ok(result, note_guid=guid, note_title=title, note_text=text, note_content=content):
            self._saving.discard(note_guid)
            self._on_saved(note_guid, note_title, note_text, note_content, result)
            if note_guid in self._resave:
                self._resave.discard(note_guid)
                self.save_note(note_guid)

        def err(message, note_guid=guid):
            self._saving.discard(note_guid)
            self._on_error(message)

        self._submit(work, ok, err)

    def _save_blocking(self, guid: str) -> None:
        window = self._windows.get(guid)
        session = self._sessions.get(guid)
        if self._client is None or window is None or session is None:
            return
        if session.rich or session.conflict:
            return
        title = normalize_title(window.note_title())
        text = window.note_text()
        if title == session.synced_title and text == session.synced_text:
            return
        try:
            content = build_update_content(session.original_enml, text)
        except RichNoteBlocked:
            session.rich = True
            window.set_rich(True)
            return
        result = self._client.update_note_if_usn_matches(guid, title, content, session.usn)
        self._on_saved(guid, title, text, content, result)

    def _on_saved(self, guid: str, title: str, text: str, content: str, result) -> None:
        session = self._sessions.get(guid)
        if session is None:
            return
        if not result.updated:
            self._remember_remote(session, result.note)
            session.conflict = True
            window = self._windows.get(guid)
            if window is not None:
                window.set_conflict(True)
            self._set_status("Evernote側が新しいため、上書きを止めています")
            return
        session.usn = result.note.update_sequence_num
        session.synced_title = title
        session.synced_text = text
        session.original_enml = content
        session.conflict = False
        self._store.set_last_usn(guid, session.usn)
        for summary in self._summaries:
            if summary.guid == guid:
                summary.title = title
                summary.update_sequence_num = session.usn
        window = self._windows.get(guid)
        if window is not None:
            window.set_conflict(False)
            if (
                normalize_title(window.note_title()) != session.synced_title
                or window.note_text() != session.synced_text
            ):
                self._schedule_save(guid)
        self._fill_list()
        self._set_status("保存しました")

    def pull_remote(self, guid: str) -> None:
        session = self._sessions.get(guid)
        if session is None:
            return
        if session.remote_enml:
            self._apply_remote(guid)
            return

        def work(note_guid=guid):
            return self._client.get_note(note_guid)

        def ok(detail, note_guid=guid):
            current = self._sessions.get(note_guid)
            if current is None:
                return
            self._remember_remote(current, detail)
            self._apply_remote(note_guid)

        self._submit(work, ok, self._on_error)

    def _consider_remote(self, detail: NoteDetail) -> None:
        session = self._sessions.get(detail.guid)
        if session is None:
            return
        text, rich = parse_note_body(detail.content)
        window = self._windows.get(detail.guid)
        editor_title = normalize_title(window.note_title()) if window else normalize_title(session.title)
        editor_text = window.note_text() if window else session.text
        kind = classify_remote_change(
            editor_title=editor_title,
            editor_text=editor_text,
            synced_title=session.synced_title,
            synced_text=session.synced_text,
            remote_title=detail.title or "無題",
            remote_text=text,
            remote_usn=detail.update_sequence_num,
            local_usn=session.usn,
            rich=rich,
        )
        self._remember_remote(session, detail)
        if kind == "unchanged":
            return
        if kind == "conflict":
            session.conflict = True
            if window is not None:
                window.set_conflict(True)
            self._set_status("Evernote側が新しいため、上書きを止めています")
            return
        self._apply_remote(detail.guid)

    def _remember_remote(self, session: Session, detail: NoteDetail) -> None:
        text, _rich = parse_note_body(detail.content)
        session.remote_title = detail.title or "無題"
        session.remote_text = text
        session.remote_usn = detail.update_sequence_num
        session.remote_enml = detail.content

    def _apply_remote(self, guid: str) -> None:
        session = self._sessions.get(guid)
        if session is None or not session.remote_enml:
            return
        text, rich = parse_note_body(session.remote_enml)
        title = session.remote_title or "無題"
        session.title = title
        session.text = text
        session.usn = session.remote_usn
        session.synced_title = title
        session.synced_text = text
        session.original_enml = session.remote_enml
        session.rich = rich
        session.conflict = False
        self._store.set_last_usn(guid, session.usn)
        window = self._windows.get(guid)
        if window is not None:
            window.set_content(title, text)
            window.set_rich(rich)
            window.set_conflict(False)
        self._fill_list()
        self._set_status("Evernote側の内容を取り込みました")

    def _on_edited(self, guid: str) -> None:
        window = self._windows.get(guid)
        session = self._sessions.get(guid)
        if window is None or session is None or session.rich:
            return
        session.title = window.note_title()
        session.text = window.note_text()
        self._update_item_title(guid)
        if not session.conflict:
            self._schedule_save(guid)

    def _schedule_save(self, guid: str) -> None:
        timer = self._save_timers.get(guid)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda note_guid=guid: self.save_note(note_guid))
            self._save_timers[guid] = timer
        timer.start(SAVE_MS)

    def _on_color_changed(self, guid: str, color: str) -> None:
        state = self._store.get_note_state(guid)
        state.color = color
        state.is_open = guid in self._windows
        self._store.save_note_state(state)

    def _on_pin_changed(self, guid: str, pinned: bool) -> None:
        state = self._store.get_note_state(guid)
        state.pinned = pinned
        state.is_open = guid in self._windows
        self._store.save_note_state(state)

    def _save_geometry(self, guid: str) -> None:
        window = self._windows.get(guid)
        if window is None:
            return
        state = self._store.get_note_state(guid)
        state.x = window.x()
        state.y = window.y()
        state.width = window.width()
        state.height = window.height()
        state.color = window.color()
        state.pinned = window.pinned()
        state.is_open = True
        session = self._sessions.get(guid)
        if session is not None:
            state.last_usn = session.usn
        self._store.save_note_state(state)

    def _fill_list(self) -> None:
        selected = self._selected_guid()
        self.note_list.clear()
        for summary in self._summaries:
            session = self._sessions.get(summary.guid)
            title = (session.title if session else summary.title) or "無題"
            prefix = "● " if summary.guid in self._windows else ""
            item = QListWidgetItem(f"{prefix}{title}")
            item.setData(Qt.ItemDataRole.UserRole, summary.guid)
            self.note_list.addItem(item)
            if summary.guid == selected:
                self.note_list.setCurrentItem(item)

    def _update_item_title(self, guid: str) -> None:
        session = self._sessions.get(guid)
        if session is None:
            return
        prefix = "● " if guid in self._windows else ""
        for row in range(self.note_list.count()):
            item = self.note_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == guid:
                item.setText(f"{prefix}{session.title or '無題'}")
                return

    def _selected_guid(self) -> str:
        item = self.note_list.currentItem()
        if item is None:
            return ""
        return item.data(Qt.ItemDataRole.UserRole) or ""

    def _is_dirty(self, session: Session) -> bool:
        return (
            normalize_title(session.title) != session.synced_title
            or session.text != session.synced_text
        )

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

    def closeEvent(self, event):
        self._poll.stop()
        for guid in list(self._windows):
            self.close_sticky(guid, save=True, sync=True)
        super().closeEvent(event)
