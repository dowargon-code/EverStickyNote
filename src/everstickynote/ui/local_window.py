"""Read-only sticky notes loaded from the local Evernote desktop database."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from everstickynote.app_icon import app_icon
from everstickynote.enex import write_enex_file
from everstickynote.local_notes import (
    LocalEvernote,
    LocalEvernoteError,
    LocalNote,
    LocalNoteSummary,
    LocalNotebook,
    database_stamp,
    display_text,
    display_title,
)
from everstickynote.local_store import LocalStore
from everstickynote.notebook_config import (
    AppConfig,
    NotebookConfigError,
    default_config_path,
    ensure_config,
    load_config,
    save_config,
    save_launch_at_startup,
    select_notebooks,
)
from everstickynote.sync import normalize_title
from everstickynote.ui.jobs import start_async
from everstickynote.ui.sticky_window import StickyWindow, arrange_positions
from everstickynote.window_position import NotePosition, default_position_path, load_layout, save_layout
from everstickynote.windows_startup import set_launch_at_startup

READ_ONLY_MESSAGE = "読み取り専用です。編集はEvernoteで行い、更新で取り込みます。"
ALL_NOTEBOOKS_ID = "*"


@dataclass
class PendingCreation:
    title: str
    text: str
    existing_ids: set[str]


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


def open_enex_file(path: Path) -> None:
    if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        return
    if os.name == "nt":
        os.startfile(str(path))
        return
    raise OSError(".enex ファイルを開けませんでした")


class SettingsDialog(QDialog):
    """GUI dialog for editing config.toml settings."""

    def __init__(
        self,
        all_notebooks: list[LocalNotebook],
        config: AppConfig,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.resize(440, 520)
        self._build(all_notebooks, config)

    def _build(self, all_notebooks: list[LocalNotebook], config: AppConfig) -> None:
        root = QVBoxLayout(self)

        root.addWidget(QLabel("表示するノートブック"))
        self.notebook_list = QListWidget()
        selected_set = set(config.notebooks)
        seen: set[str] = set()
        for notebook in all_notebooks:
            item = QListWidgetItem(notebook.name)
            item.setData(Qt.ItemDataRole.UserRole, notebook.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if notebook.name in selected_set else Qt.CheckState.Unchecked
            )
            self.notebook_list.addItem(item)
            seen.add(notebook.name)
        for missing_name in config.notebooks:
            if missing_name in seen:
                continue
            item = QListWidgetItem(f"{missing_name}（未検出）")
            item.setData(Qt.ItemDataRole.UserRole, missing_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.notebook_list.addItem(item)
            seen.add(missing_name)
        root.addWidget(self.notebook_list, 1)

        form = QFormLayout()
        self.watch_spin = QDoubleSpinBox()
        self.watch_spin.setRange(0.0, 3600.0)
        self.watch_spin.setSingleStep(0.5)
        self.watch_spin.setDecimals(
            2 if round(config.watch_seconds, 1) != round(config.watch_seconds, 2) else 1
        )
        self.watch_spin.setSuffix(" 秒")
        self.watch_spin.setValue(config.watch_seconds)
        form.addRow("監視間隔 (watch_seconds):", self.watch_spin)

        self.flicker_spin = QDoubleSpinBox()
        self.flicker_spin.setRange(0.0, 3600.0)
        self.flicker_spin.setSingleStep(0.5)
        self.flicker_spin.setDecimals(
            2 if round(config.flicker_seconds, 1) != round(config.flicker_seconds, 2) else 1
        )
        self.flicker_spin.setSuffix(" 秒")
        self.flicker_spin.setValue(config.flicker_seconds)
        form.addRow("更新時の点滅時間 (flicker_seconds):", self.flicker_spin)

        self.close_after_flicker_check = QCheckBox("非表示付箋の点滅後に再び閉じる")
        self.close_after_flicker_check.setChecked(config.close_after_flicker)
        form.addRow("", self.close_after_flicker_check)

        self.default_notebook_combo = QComboBox()
        self.default_notebook_combo.addItem("（未設定）", "")
        db_names: set[str] = set()
        for notebook in all_notebooks:
            self.default_notebook_combo.addItem(notebook.name, notebook.name)
            db_names.add(notebook.name)
        if config.default_notebook and config.default_notebook not in db_names:
            self.default_notebook_combo.addItem(
                f"{config.default_notebook}（未検出）",
                config.default_notebook,
            )
        selected_idx = 0
        if config.default_notebook:
            for row in range(self.default_notebook_combo.count()):
                if self.default_notebook_combo.itemData(row) == config.default_notebook:
                    selected_idx = row
                    break
        self.default_notebook_combo.setCurrentIndex(selected_idx)
        self.default_notebook_combo.currentIndexChanged.connect(
            self._sync_default_notebook_check_state
        )
        form.addRow("デフォルトのノートブック（新規作成の取り込み先）:", self.default_notebook_combo)
        root.addLayout(form)
        self._sync_default_notebook_check_state()

        self.notice_label = QLabel(
            "※ Evernote の仕様上、新規作成したノートは Evernote 側の「デフォルトのノートブック（Inbox 等）」に保存されます。"
            "上の設定を Evernote 側のデフォルトノートブックに合わせておくと、そのノートブック内の他ノートは出さずに、"
            "このアプリから新規作成したノートだけを検知して付箋表示します"
            "（後から Evernote 側で表示対象ノートブックへ移動しても付箋はそのまま維持されます）。"
        )
        self.notice_label.setWordWrap(True)
        root.addWidget(self.notice_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("保存")
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _sync_default_notebook_check_state(self) -> None:
        default_nb = self.default_notebook()
        for row in range(self.notebook_list.count()):
            item = self.notebook_list.item(row)
            name = item.data(Qt.ItemDataRole.UserRole) or item.text()
            is_missing = item.text().endswith("（未検出）")
            base_label = f"{name}（未検出）" if is_missing else str(name)
            if default_nb and display_title(str(name)) == display_title(default_nb):
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setText(f"{base_label}（デフォルトNB：新規作成のみ表示）")
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
                item.setText(base_label)

    def selected_notebooks(self) -> list[str]:
        default_nb = display_title(self.default_notebook()) if self.default_notebook() else ""
        names: list[str] = []
        for row in range(self.notebook_list.count()):
            item = self.notebook_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                name = item.data(Qt.ItemDataRole.UserRole) or item.text()
                if default_nb and display_title(str(name)) == default_nb:
                    continue
                names.append(name)
        return names

    def watch_seconds(self) -> float:
        return float(self.watch_spin.value())

    def flicker_seconds(self) -> float:
        return float(self.flicker_spin.value())

    def close_after_flicker(self) -> bool:
        return self.close_after_flicker_check.isChecked()

    def default_notebook(self) -> str:
        return self.default_notebook_combo.currentData() or ""


class NewNoteDialog(QDialog):
    """Dialog for creating a new Evernote note via .enex export."""

    def __init__(self, default_notebook: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("新規ノート作成")
        self.resize(420, 360)
        self._build(default_notebook)

    def _build(self, default_notebook: str) -> None:
        root = QVBoxLayout(self)

        root.addWidget(QLabel("タイトル"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("タイトル")
        root.addWidget(self.title_edit)

        root.addWidget(QLabel("本文"))
        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("本文")
        root.addWidget(self.body_edit, 1)

        if default_notebook:
            notice = (
                f"※ 作成したノートは Evernote 側のデフォルトノートブック（{default_notebook}）に取り込まれ、"
                "検知され次第付箋として表示されます。後から別の表示対象ノートブックへ移動しても付箋は維持されます。"
            )
        else:
            notice = (
                "※ 作成したノートは Evernote 側のデフォルトノートブック（Inbox 等）に保存されます。"
                "すぐに付箋として表示するには「設定」でデフォルトのノートブックを指定してください。"
            )
        self.notice_label = QLabel(notice)
        self.notice_label.setWordWrap(True)
        root.addWidget(self.notice_label)

        row = QHBoxLayout()
        row.addStretch(1)
        self.create_button = QPushButton("作成")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.clicked.connect(self.reject)
        row.addWidget(self.create_button)
        row.addWidget(self.cancel_button)
        root.addLayout(row)

    def note_title(self) -> str:
        return self.title_edit.text()

    def note_text(self) -> str:
        return self.body_edit.toPlainText()


class LocalMainWindow(QWidget):
    def __init__(
        self,
        store: LocalStore | None = None,
        opener=None,
        config_path=None,
        url_opener=None,
        position_path=None,
        stamp=None,
        startup_apply=None,
        confirm_exit=None,
        quit_on_exit=None,
        enex_opener=None,
        enex_save_picker=None,
    ):
        super().__init__()
        self.setWindowTitle("EverStickyNote")
        self.setWindowIcon(app_icon())
        self.resize(440, 560)
        self._store = store or LocalStore()
        self._opener = opener or open_local_reader
        self._url_opener = url_opener or open_evernote_url
        self._enex_opener = enex_opener or open_enex_file
        self._enex_save_picker = enex_save_picker or self._default_enex_save_picker
        self._config_path = Path(config_path) if config_path is not None else default_config_path()
        self._position_path = (
            Path(position_path) if position_path is not None else default_position_path()
        )
        self._layout = load_layout(self._position_path)
        self._stamp = stamp or database_stamp
        self._startup_apply = startup_apply or set_launch_at_startup
        self._confirm_exit = confirm_exit or self._default_confirm_exit
        self._quit_on_exit = quit_on_exit or self._default_quit_on_exit
        self._watched_stamp = None
        self._watch_seconds = 2.0
        self._config_stamp: tuple[int, int] | None = None
        self._config_bytes: bytes | None = None
        self._config_cache: AppConfig | None = None
        self._config_error: str | None = None
        self._default_notebook_name = ""
        self._default_notebook_id = ""
        self._default_notebook_known_ids: set[str] = set()
        self._pending_creations: list[PendingCreation] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._watch)
        self._reader: LocalEvernote | None = None
        self._all_notebooks: list[LocalNotebook] = []
        self._notebooks: list[LocalNotebook] = []
        self._allowed_notebook_ids: set[str] = set()
        self._notes: list[LocalNoteSummary] = []
        self._windows: dict[str, StickyWindow] = {}
        self._seen_content: dict[str, tuple[str, str]] = {}
        self._temporary_notes: set[str] = set()
        self._flicker_notes: set[str] = set()
        self._flicker_seconds = 5.0
        self._close_after_flicker = True
        self._force_close = False
        self._closed = False
        self._window_notebooks: dict[str, str] = {}
        self._threads: list = []
        self._notebook_id = ""
        self._generation = 0
        self._tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._build()
        self._apply_watch_interval()
        self.reload()

    def _build(self) -> None:
        root = QVBoxLayout(self)

        row = QHBoxLayout()
        self.notebook_combo = QComboBox()
        self.notebook_combo.currentIndexChanged.connect(self._on_notebook_changed)
        row.addWidget(self.notebook_combo, 1)
        self.refresh_button = QPushButton("更新")
        self.refresh_button.clicked.connect(self.reload)
        row.addWidget(self.refresh_button)
        self.settings_button = QPushButton("設定")
        self.settings_button.clicked.connect(self.open_settings_dialog)
        row.addWidget(self.settings_button)
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
        self.new_button = QPushButton("新規作成")
        self.new_button.clicked.connect(self.open_new_note_dialog)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.new_button)
        root.addLayout(buttons)

        self.startup_check = QCheckBox("Windows起動時に実行する")
        self.startup_check.toggled.connect(self._on_startup_toggled)
        root.addWidget(self.startup_check)

        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._load_startup_setting()
        self._setup_tray()

    def _load_app_config(self, *, force: bool = False) -> AppConfig | None:
        try:
            ensure_config(self._config_path)
            stat = self._config_path.stat()
        except OSError as exc:
            self._on_error(str(exc))
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)
        if not force and stamp == self._config_stamp:
            if self._config_error is not None:
                self._on_error(self._config_error)
                return None
            if self._config_cache is not None:
                return self._config_cache
        try:
            raw = self._config_path.read_bytes()
        except OSError as exc:
            self._on_error(str(exc))
            return None
        if (
            not force
            and self._config_cache is not None
            and self._config_bytes is not None
            and raw == self._config_bytes
        ):
            self._config_stamp = stamp
            return self._config_cache
        try:
            config = load_config(self._config_path)
        except NotebookConfigError as exc:
            self._config_stamp = stamp
            self._config_bytes = raw
            self._config_cache = None
            self._config_error = str(exc)
            self._on_error(str(exc))
            return None
        self._config_stamp = stamp
        self._config_bytes = raw
        self._config_cache = config
        self._config_error = None
        return config

    def _apply_config_values(self, config: AppConfig) -> None:
        self._flicker_seconds = config.flicker_seconds
        self._close_after_flicker = config.close_after_flicker
        self._default_notebook_name = config.default_notebook
        self._set_watch_seconds(config.watch_seconds)

    def _set_watch_seconds(self, seconds: float) -> None:
        self._watch_seconds = seconds
        if seconds <= 0:
            self._timer.stop()
            return
        msec = max(1, int(seconds * 1000))
        if self._timer.interval() != msec:
            self._timer.setInterval(msec)
        if not self._timer.isActive():
            self._timer.start()

    def reload(self) -> None:
        self._reload()

    def _apply_watch_interval(self) -> None:
        config = self._load_app_config(force=False)
        if config is None:
            return
        self._apply_config_values(config)

    def _watch(self) -> None:
        previous_notebooks = (
            list(self._config_cache.notebooks) if self._config_cache is not None else None
        )
        previous_default = (
            self._config_cache.default_notebook if self._config_cache is not None else None
        )
        config = self._load_app_config(force=False)
        if config is not None:
            self._apply_config_values(config)
            if (
                previous_notebooks is not None
                and (
                    config.notebooks != previous_notebooks
                    or config.default_notebook != previous_default
                )
                and self._reader is not None
                and not self._threads
            ):
                if self._all_notebooks:
                    self._show_notebooks(self._all_notebooks)
                else:
                    self._reload()
                return
        if self._watch_seconds <= 0 or self._threads or self._reader is None:
            return
        try:
            stamp = self._stamp()
        except LocalEvernoteError as exc:
            self._on_error(str(exc))
            return
        if stamp == self._watched_stamp:
            return
        self._refresh_flicker_settings()
        self._reload()

    def _capture_stamp(self) -> None:
        try:
            self._watched_stamp = self._stamp()
        except LocalEvernoteError:
            self._watched_stamp = None

    def _reload(self) -> None:
        self._generation += 1
        generation = self._generation
        self.refresh_button.setEnabled(False)
        self._set_status("Evernoteのローカルデータを読み込んでいます")
        config = self._load_app_config(force=True)
        if config is not None:
            self._apply_config_values(config)

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
            self._capture_stamp()
            self._show_notebooks(notebooks)

        def err(message, gen=generation):
            self.refresh_button.setEnabled(True)
            if gen != self._generation:
                return
            self._on_error(message)

        self._submit(work, ok, err)

    def _resolve_default_notebook_id(self, notebooks: list[LocalNotebook]) -> str:
        if not self._default_notebook_name:
            return ""
        target = display_title(self._default_notebook_name)
        for notebook in notebooks:
            if display_title(notebook.name) == target:
                return notebook.id
        return ""

    def _is_note_allowed(
        self,
        note_id: str,
        notebook_id: str,
        tracked: set[str] | None = None,
    ) -> bool:
        if self._default_notebook_id and notebook_id == self._default_notebook_id:
            tracked_ids = self._store.get_tracked_created_notes() if tracked is None else tracked
            return note_id in tracked_ids
        if notebook_id in self._allowed_notebook_ids:
            return True
        return False

    def _show_notebooks(self, notebooks: list[LocalNotebook]) -> None:
        self._all_notebooks = list(notebooks)
        config = self._load_app_config(force=True)
        if config is None:
            self._allowed_notebook_ids = set()
            self._default_notebook_id = ""
            self._close_disallowed()
            self._notes = []
            self._fill_list()
            self.notebook_combo.clear()
            self.open_button.setEnabled(False)
            return
        self._apply_config_values(config)
        self._default_notebook_id = self._resolve_default_notebook_id(notebooks)
        default_norm = (
            display_title(self._default_notebook_name) if self._default_notebook_name else ""
        )
        names = [
            name
            for name in config.notebooks
            if not (default_norm and display_title(name) == default_norm)
        ]
        matched, missing = select_notebooks(notebooks, names)
        prev_allowed_count = len(self._allowed_notebook_ids)
        self._notebooks = matched
        self._allowed_notebook_ids = {notebook.id for notebook in matched}
        self._close_disallowed()
        saved = self._store.get_notebook_guid()
        self.notebook_combo.blockSignals(True)
        self.notebook_combo.clear()
        if len(matched) > 1:
            self.notebook_combo.addItem("すべてのノートブック", ALL_NOTEBOOKS_ID)
        for notebook in matched:
            self.notebook_combo.addItem(notebook.name, notebook.id)
        if not matched and self._default_notebook_id:
            self.notebook_combo.addItem("新規作成したノート", ALL_NOTEBOOKS_ID)
        index = 0
        if not (prev_allowed_count == 1 and len(matched) > 1):
            for row in range(self.notebook_combo.count()):
                if self.notebook_combo.itemData(row) == saved:
                    index = row
                    break
        self.notebook_combo.setCurrentIndex(index if self.notebook_combo.count() else -1)
        self.notebook_combo.blockSignals(False)
        if not names and not self._default_notebook_id:
            self._notes = []
            self._fill_list()
            self.open_button.setEnabled(False)
            self._set_status(
                f"config.toml の notebooks にノートブック名を書いてください ({self._config_path})"
            )
            return
        if not matched and not self._default_notebook_id:
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

    def _close_disallowed(self) -> None:
        tracked = self._store.get_tracked_created_notes()
        for note_id, notebook_id in list(self._window_notebooks.items()):
            if not self._is_note_allowed(note_id, notebook_id, tracked):
                self._hide_sticky(note_id)

    def _on_notebook_changed(self, index: int) -> None:
        notebook_id = self.notebook_combo.itemData(index)
        if not notebook_id or notebook_id == self._notebook_id:
            return
        self._notebook_id = notebook_id
        self._store.set_notebook_guid(notebook_id)
        self._load_notes(notebook_id)

    def _match_pending_creations(
        self,
        default_notes: list[LocalNoteSummary],
        tracked_ids: set[str],
        pending_snapshot: list[PendingCreation],
    ) -> list[tuple[int, str]]:
        matches: list[tuple[int, str]] = []
        consumed_note_ids: set[str] = set()
        for idx, pending in enumerate(pending_snapshot):
            candidates = [
                note
                for note in default_notes
                if note.id not in tracked_ids
                and note.id not in consumed_note_ids
                and note.id not in pending.existing_ids
                and display_title(note.title) == pending.title
            ]
            if not candidates:
                continue
            chosen = candidates[0]
            if len(candidates) > 1 and pending.text:
                for candidate in candidates:
                    try:
                        detail = self._reader.get_note(candidate.id)
                    except LocalEvernoteError:
                        continue
                    if detail.text.strip() == pending.text.strip():
                        chosen = candidate
                        break
            consumed_note_ids.add(chosen.id)
            matches.append((idx, chosen.id))
        return matches

    def _load_notes(self, notebook_id: str) -> None:
        self._generation += 1
        generation = self._generation
        allowed_ids = [notebook.id for notebook in self._notebooks]
        default_nb_id = self._default_notebook_id
        fetch_default_separately = bool(default_nb_id and default_nb_id not in allowed_ids)
        tracked_snapshot = self._store.get_tracked_created_notes()
        pending_snapshot = list(self._pending_creations)

        def work():
            regular_notes: list[LocalNoteSummary] = []
            for allowed_id in allowed_ids:
                regular_notes.extend(self._reader.list_notes(allowed_id))
            if fetch_default_separately:
                default_notes = self._reader.list_notes(default_nb_id)
            elif default_nb_id:
                default_notes = [n for n in regular_notes if n.notebook_id == default_nb_id]
            else:
                default_notes = []
            newly_matched = (
                self._match_pending_creations(default_notes, tracked_snapshot, pending_snapshot)
                if pending_snapshot and default_notes
                else []
            )
            return regular_notes, default_notes, newly_matched

        def ok(payload, gen=generation):
            if gen != self._generation or self._closed:
                return
            regular_notes, default_notes, newly_matched = payload
            self._default_notebook_known_ids = {note.id for note in default_notes}
            for idx, matched_id in newly_matched:
                pending_obj = pending_snapshot[idx]
                if pending_obj in self._pending_creations:
                    self._pending_creations.remove(pending_obj)
                self._store.add_tracked_created_note(matched_id)

            tracked_ids = self._store.get_tracked_created_notes()
            all_notes = list(regular_notes)
            seen_ids = {note.id for note in all_notes}
            for note in default_notes:
                if note.id in tracked_ids and note.id not in seen_ids:
                    all_notes.append(note)
                    seen_ids.add(note.id)

            if notebook_id == ALL_NOTEBOOKS_ID or len(self._notebooks) <= 1:
                visible_notes = list(all_notes)
            else:
                visible_notes = [note for note in regular_notes if note.notebook_id == notebook_id]
            self._notes = visible_notes
            self._fill_list()
            self._set_status(f"{len(visible_notes)}件")
            listed = {note.id for note in all_notes}
            self._remove_deleted_notes(listed, gen)
            open_ids = [
                note.id
                for note in all_notes
                if note.id in self._windows or self._note_should_show(note.id)
            ]
            hidden_ids = [
                note.id
                for note in all_notes
                if note.id not in open_ids and self._note_is_hidden(note.id)
            ]
            if open_ids or hidden_ids:
                self._fetch_notes(open_ids + hidden_ids, gen)

        self._submit(work, ok, self._on_error)

    def open_selected(self) -> None:
        note_id = self._selected_id()
        if note_id:
            self.open_note(note_id)

    def close_selected(self) -> None:
        note_id = self._selected_id()
        if note_id and note_id in self._windows:
            self.close_sticky(note_id)
            return

    def _open_item(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        self.note_list.setCurrentItem(item)
        self.open_selected()

    def open_note(self, note_id: str) -> None:
        if self._reader is None:
            return
        self._temporary_notes.discard(note_id)
        if self._note_is_hidden(note_id):
            self._set_note_visible(note_id, True)
        window = self._windows.get(note_id)
        if window is not None:
            self._restore_sticky_window(window)
            self._store.set_open(note_id, True)
            self._fill_list()
            return
        self._fetch_notes([note_id], self._generation, force_show=True)

    def _fetch_notes(self, note_ids: list[str], generation: int, force_show: bool = False) -> None:
        def work(ids=list(note_ids)):
            return [self._reader.get_note(note_id) for note_id in ids]

        def ok(notes, gen=generation):
            if gen != self._generation and len(note_ids) != 1:
                return
            for note in notes:
                if force_show or note.id in self._windows or self._note_should_show(note.id):
                    self.show_note(note)
                else:
                    self._consider_hidden_update(note)

        self._submit(work, ok, self._on_error)

    def show_note(self, note: LocalNote) -> None:
        if self._closed:
            return
        window = self._windows.get(note.id)
        if window is None:
            state = self._store.get_note_state(note.id)
            window = StickyWindow(note.id, color=state.color, pinned=state.pinned)
            window.set_read_only(READ_ONLY_MESSAGE)
            window.closeRequested.connect(self.close_sticky)
            window.colorChanged.connect(self._on_color_changed)
            window.pinChanged.connect(self._on_pin_changed)
            window.geometryChanged.connect(self._save_geometry)
            window.openRequested.connect(self.open_in_evernote)
            window.arrangeRequested.connect(self.arrange_stickies)
            window.mainRequested.connect(self.show_main_form)
            window.newNoteRequested.connect(lambda _id: self.open_new_note_dialog())
            window.updateNoticeFinished.connect(self._on_update_notice_finished)
            self._windows[note.id] = window
            saved = self._layout.notes.get(note.id)
            if saved is None:
                window.place(state.x, state.y, state.width, state.height, len(self._windows) - 1)
            else:
                window.place(saved.x, saved.y, saved.width, saved.height, len(self._windows) - 1)
            window.show()
            self._save_geometry(note.id)
        current = (note.title, note.text)
        previous = self._seen_content.get(note.id)
        changed = (
            note.id in self._temporary_notes
            or note.id in self._flicker_notes
            or (previous is not None and previous != current)
        )
        window.set_content(note.title, note.text)
        self._seen_content[note.id] = current
        if changed:
            self._flicker_notes.discard(note.id)
            self._refresh_flicker_settings()
            window.mark_updated(self._flicker_seconds)
            self._restore_sticky_window(window)
        window.set_read_only(READ_ONLY_MESSAGE)
        self._window_notebooks[note.id] = note.notebook_id
        self._store.set_open(note.id, True)
        self._fill_list()

    def arrange_stickies(self, _note_id: str = "") -> None:
        windows: list[StickyWindow] = []
        seen: set[str] = set()
        for note in self._notes:
            window = self._windows.get(note.id)
            if window is not None:
                windows.append(window)
                seen.add(note.id)
        for note_id, window in self._windows.items():
            if note_id not in seen:
                windows.append(window)
        if not windows:
            return
        pressed = self._windows.get(_note_id)
        if pressed is not None and pressed in windows:
            windows.remove(pressed)
            windows.insert(0, pressed)
        screen = pressed.screen() if pressed is not None else None
        if screen is None:
            screen = windows[0].screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        positions = arrange_positions(
            [(window.width(), window.height()) for window in windows],
            (area.x(), area.y(), area.width(), area.height()),
        )
        for window, (x, y) in zip(windows, positions):
            window.move(x, y)
            self._save_geometry(window.guid)

    def open_in_evernote(self, note_id: str) -> None:
        if self._reader is None:
            return
        try:
            url = self._reader.note_app_url(note_id)
            self._url_opener(url)
        except Exception as exc:
            self._set_status(str(exc) or "Evernoteでノートを開けませんでした")

    def open_settings_dialog(self) -> None:
        config = self._load_app_config(force=True)
        if config is None:
            config = AppConfig(notebooks=[])
        notebooks = list(self._all_notebooks)
        if not notebooks and self._reader is not None:
            try:
                notebooks = self._reader.list_notebooks()
            except LocalEvernoteError:
                notebooks = []
        dialog = SettingsDialog(notebooks, config, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.apply_settings(
            notebooks=dialog.selected_notebooks(),
            watch_seconds=dialog.watch_seconds(),
            flicker_seconds=dialog.flicker_seconds(),
            close_after_flicker=dialog.close_after_flicker(),
            default_notebook=dialog.default_notebook(),
        )

    def apply_settings(
        self,
        *,
        notebooks: list[str],
        watch_seconds: float,
        flicker_seconds: float,
        close_after_flicker: bool,
        default_notebook: str = "",
    ) -> None:
        try:
            save_config(
                self._config_path,
                notebooks=notebooks,
                watch_seconds=watch_seconds,
                flicker_seconds=flicker_seconds,
                close_after_flicker=close_after_flicker,
                default_notebook=default_notebook,
            )
        except (NotebookConfigError, OSError) as exc:
            self._on_error(str(exc))
            return
        config = self._load_app_config(force=True)
        if config is not None:
            self._apply_config_values(config)
        if self._reader is None:
            self._reload()
            return
        if self._all_notebooks:
            self._show_notebooks(self._all_notebooks)
        else:
            self._reload()

    def open_new_note_dialog(self) -> None:
        config = self._load_app_config(force=False)
        default_nb = (
            config.default_notebook if config is not None else self._default_notebook_name
        )
        dialog = NewNoteDialog(default_notebook=default_nb, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.create_new_note(dialog.note_title(), dialog.note_text())

    def _default_enex_save_picker(self, default_name: str) -> str:
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "新規ノート (.enex) の保存先を選択",
            default_name,
            "Evernote Export (*.enex)",
        )
        return chosen

    def _snapshot_default_notebook_ids(self) -> set[str]:
        existing = set(self._default_notebook_known_ids)
        if self._reader is not None and self._default_notebook_id:
            try:
                existing.update(
                    note.id for note in self._reader.list_notes(self._default_notebook_id)
                )
            except LocalEvernoteError:
                pass
        return existing

    def _record_pending_creation(
        self,
        title: str,
        text: str,
        existing_ids: set[str] | None = None,
    ) -> None:
        if not self._default_notebook_name:
            return
        snapshot = (
            self._snapshot_default_notebook_ids()
            if existing_ids is None
            else set(existing_ids)
        )
        self._pending_creations.append(
            PendingCreation(
                title=normalize_title(title),
                text=display_text(text, None),
                existing_ids=snapshot,
            )
        )

    def create_new_note(self, title: str, text: str) -> Path | None:
        temp_dir = Path(tempfile.gettempdir())
        try:
            output = write_enex_file(temp_dir, title, text)
        except OSError as exc:
            self._set_status(f"新規ノートの作成に失敗しました: {exc}")
            return None
        existing_snapshot = self._snapshot_default_notebook_ids()
        try:
            self._enex_opener(output)
        except OSError:
            chosen = self._enex_save_picker(output.name)
            if not chosen:
                self._set_status(f"新規ノートを出力しました: {output}")
                return output
            target = Path(chosen)
            try:
                saved = write_enex_file(target.parent, title, text)
                if saved != target:
                    os.replace(saved, target)
                self._record_pending_creation(title, text, existing_ids=existing_snapshot)
                self._set_status(f"新規ノートを保存しました: {target}")
                return target
            except OSError as exc:
                self._set_status(f"新規ノートの保存に失敗しました: {exc}")
                return None

        self._record_pending_creation(title, text, existing_ids=existing_snapshot)
        if self._default_notebook_name:
            self._set_status(
                f"Evernoteに新規ノートを渡しました（{self._default_notebook_name} への取り込みを監視中）"
            )
        else:
            self._set_status(f"Evernoteに新規ノートを渡しました ({output.name})")
        return output

    def close_sticky(self, note_id: str) -> None:
        window = self._windows.get(note_id)
        if window is None:
            return
        self._save_geometry(note_id)
        window.showMinimized()
        self._fill_list()

    def _restore_sticky_window(self, window: StickyWindow) -> None:
        if window.isMinimized():
            window.showNormal()
        window.show()
        window.raise_()
        window.activateWindow()

    def _default_confirm_exit(self) -> bool:
        answer = QMessageBox.question(
            self,
            "EverStickyNote",
            "EverStickyNote を終了しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _default_quit_on_exit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _hide_sticky(self, note_id: str) -> None:
        window = self._windows.get(note_id)
        if window is not None:
            self._save_geometry(note_id)
            self._set_note_visible(note_id, False)
            state = self._store.get_note_state(note_id)
            state.is_open = False
            self._store.save_note_state(state)
            window.hide()
            window.deleteLater()
            del self._windows[note_id]
            self._window_notebooks.pop(note_id, None)
        self._fill_list()

    def _remove_deleted_notes(self, listed: set[str], generation: int) -> None:
        for note_id, owner in list(self._window_notebooks.items()):
            monitored = owner in self._allowed_notebook_ids or (
                bool(self._default_notebook_id) and owner == self._default_notebook_id
            )
            if monitored and note_id not in listed:
                self._remove_note_display(note_id, forget_tracked=True)
        orphans = [
            note_id
            for note_id in self._layout.notes
            if note_id not in listed and note_id not in self._windows
        ]
        if orphans:
            self._drop_missing_notes(orphans, generation)

    def _drop_missing_notes(self, note_ids: list[str], generation: int) -> None:
        tracked = self._store.get_tracked_created_notes()

        def work(ids=list(note_ids)):
            missing: list[tuple[str, bool]] = []
            for note_id in ids:
                try:
                    note = self._reader.get_note(note_id)
                except LocalEvernoteError:
                    missing.append((note_id, True))
                else:
                    if not self._is_note_allowed(note_id, note.notebook_id, tracked):
                        forget = bool(self._default_notebook_id) or note_id not in tracked
                        missing.append((note_id, forget))
            return missing

        def ok(missing, gen=generation):
            if gen != self._generation:
                return
            for note_id, forget_tracked in missing:
                self._remove_note_display(note_id, forget_tracked=forget_tracked)

        self._submit(work, ok, self._on_error)

    def _remove_note_display(self, note_id: str, *, forget_tracked: bool = True) -> None:
        if self._closed:
            return
        window = self._windows.pop(note_id, None)
        self._window_notebooks.pop(note_id, None)
        self._seen_content.pop(note_id, None)
        self._temporary_notes.discard(note_id)
        self._flicker_notes.discard(note_id)
        if forget_tracked:
            self._store.remove_tracked_created_note(note_id)
        if window is not None:
            window.cancel_pending_geometry()
            window.hide()
            window.deleteLater()
        if note_id in self._layout.notes:
            del self._layout.notes[note_id]
            save_layout(self._position_path, self._layout)
        state = self._store.get_note_state(note_id)
        state.is_open = False
        self._store.save_note_state(state)
        self._fill_list()

    def _consider_hidden_update(self, note: LocalNote) -> None:
        current = (note.title, note.text)
        previous = self._seen_content.get(note.id)
        self._seen_content[note.id] = current
        if previous is None or previous == current:
            return
        self._refresh_flicker_settings()
        self._flicker_notes.add(note.id)
        if self._close_after_flicker:
            self._temporary_notes.add(note.id)
        else:
            self._set_note_visible(note.id, True)
        self.show_note(note)

    def _on_update_notice_finished(self, note_id: str) -> None:
        if note_id not in self._temporary_notes:
            return
        self._refresh_flicker_settings()
        self._temporary_notes.discard(note_id)
        if self._close_after_flicker:
            self._hide_sticky(note_id)
            return
        self._set_note_visible(note_id, True)

    def _refresh_flicker_settings(self) -> None:
        config = self._load_app_config(force=False)
        if config is None:
            return
        self._apply_config_values(config)

    def _note_is_hidden(self, note_id: str) -> bool:
        saved = self._layout.notes.get(note_id)
        return saved is not None and not saved.visible

    def _note_should_show(self, note_id: str) -> bool:
        saved = self._layout.notes.get(note_id)
        if saved is not None:
            return saved.visible
        return True

    def _set_note_visible(self, note_id: str, visible: bool) -> None:
        saved = self._layout.notes.get(note_id)
        if saved is None:
            return
        saved.visible = visible
        save_layout(self._position_path, self._layout)

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

    def _save_geometry(self, note_id: str) -> None:
        if self._closed:
            return
        window = self._windows.get(note_id)
        if window is None:
            return
        window.cancel_pending_geometry()
        self._persist_window_geometry(note_id, window)

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

    def _load_startup_setting(self) -> None:
        config = self._load_app_config(force=False)
        if config is None:
            return
        enabled = config.launch_at_startup
        self.startup_check.blockSignals(True)
        self.startup_check.setChecked(enabled)
        self.startup_check.blockSignals(False)
        self._startup_apply(enabled)

    def _on_startup_toggled(self, checked: bool) -> None:
        try:
            save_launch_at_startup(self._config_path, checked)
            self._startup_apply(checked)
            self._load_app_config(force=True)
        except (NotebookConfigError, OSError) as exc:
            self.startup_check.blockSignals(True)
            self.startup_check.setChecked(not checked)
            self.startup_check.blockSignals(False)
            self._on_error(str(exc))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "_layout"):
            if self.isMinimized() and not self._force_close:
                QTimer.singleShot(0, self._hide_to_tray)
                return
            if not self.isMinimized():
                self._remember_minimized(False)

    def show_saved_state(self) -> None:
        self._hide_to_tray()

    def show_main_form(self, _note_id: str = "") -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._remember_minimized(False)

    def _setup_tray(self) -> None:
        self._tray = None
        menu = QMenu(self)
        menu.addAction("メインフォームを開く", self.show_main_form)
        menu.addAction("新規作成", self.open_new_note_dialog)
        menu.addAction("終了", self.close)
        self._tray_menu = menu
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(app_icon(), self)
        tray.setToolTip("EverStickyNote")
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_main_form()

    def _hide_to_tray(self) -> None:
        self._remember_minimized(True)
        self.setWindowState(Qt.WindowState.WindowNoState)
        self.hide()
        if self._tray is not None:
            self._tray.show()

    def closeEvent(self, event):
        quit_app = False
        if not self._force_close:
            if not self._confirm_exit():
                event.ignore()
                return
            self._force_close = True
            self._closed = True
            quit_app = True
        else:
            self._closed = True
        self._timer.stop()
        self._remember_minimized(self.isMinimized())
        for note_id in list(self._windows):
            window = self._windows[note_id]
            window.cancel_pending_geometry()
            self._persist_window_geometry(note_id, window)
            self._windows.pop(note_id)
            self._window_notebooks.pop(note_id, None)
            window.hide()
            window.deleteLater()
        if self._reader is not None:
            self._reader.close()
        super().closeEvent(event)
        if quit_app:
            self._quit_on_exit()

    def _persist_window_geometry(self, note_id: str, window: StickyWindow) -> None:
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
            visible=note_id not in self._temporary_notes,
        )
        save_layout(self._position_path, self._layout)

    def _remember_minimized(self, minimized: bool) -> None:
        self._layout.minimized = bool(minimized)
        save_layout(self._position_path, self._layout)
