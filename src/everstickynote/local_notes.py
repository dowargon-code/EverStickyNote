"""Read notebooks and note text from the Evernote desktop app's local database.

The database is opened from a snapshot so the live Evernote app keeps its lock.
Nothing is written back.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

if os.name == "nt":
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _KERNEL32.GetExitCodeProcess.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
else:
    _KERNEL32 = None

SERVICE_DIR = "https%3A%2F%2Fwww.evernote.com"


class LocalEvernoteError(Exception):
    pass


@dataclass
class LocalNotebook:
    id: str
    name: str


@dataclass
class LocalNoteSummary:
    id: str
    title: str
    notebook_id: str


@dataclass
class LocalNote:
    id: str
    title: str
    text: str
    notebook_id: str


def default_base_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise LocalEvernoteError("APPDATA が見つかりません")
    return Path(appdata) / "Evernote"


def find_database(base_dir: Path) -> Path:
    storage = base_dir / "conduit-storage" / SERVICE_DIR
    candidates = [
        path
        for path in storage.glob("UDB-User*+RemoteGraph.sql")
        if path.is_file() and "Backup" not in path.name
    ]
    if not candidates:
        raise LocalEvernoteError(
            "Evernoteのローカルデータが見つかりません。Evernoteアプリにログインしているか確認してください。"
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def database_stamp(base_dir: Path | None = None) -> tuple:
    """Identity of the live database files, without copying them."""
    source = find_database(base_dir or default_base_dir())
    stamps = []
    for path in (source, Path(str(source) + "-wal"), Path(str(source) + "-shm")):
        if not path.exists():
            continue
        stat = path.stat()
        stamps.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(stamps)


_SNAPSHOT_NAME_RE = re.compile(r"eversticky-(\d+)-\d+\.sqlite(?:-(?:wal|shm))?$")
_ACTIVE_SNAPSHOTS_LOCK = threading.Lock()
_ACTIVE_SNAPSHOTS: set[Path] = set()


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if _KERNEL32 is not None:
        process_query_limited_information = 0x1000
        still_active = 259
        error_access_denied = 5
        handle = _KERNEL32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() == error_access_denied
        try:
            exit_code = wintypes.DWORD()
            if _KERNEL32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == still_active
            return True
        finally:
            _KERNEL32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _snapshot_key(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return Path(os.path.abspath(path))


def _register_snapshot(path: Path) -> None:
    key = _snapshot_key(path)
    with _ACTIVE_SNAPSHOTS_LOCK:
        _ACTIVE_SNAPSHOTS.add(key)


def _unregister_snapshot(path: Path) -> None:
    key = _snapshot_key(path)
    with _ACTIVE_SNAPSHOTS_LOCK:
        _ACTIVE_SNAPSHOTS.discard(key)


def cleanup_stale_snapshots(temp_dir: Path | None = None, is_alive=None) -> int:
    """Remove leftover snapshot files from dead processes or unclosed current-process opens."""
    directory = temp_dir or Path(tempfile.gettempdir())
    if not directory.exists():
        return 0
    alive_check = is_alive or _is_process_alive
    removed = 0
    current_pid = os.getpid()
    for candidate in directory.glob("eversticky-*.sqlite*"):
        match = _SNAPSHOT_NAME_RE.fullmatch(candidate.name)
        if match is None:
            continue
        pid = int(match.group(1))
        base_name = candidate.name.split(".sqlite", 1)[0] + ".sqlite"
        base_key = _snapshot_key(directory / base_name)
        if pid == current_pid:
            with _ACTIVE_SNAPSHOTS_LOCK:
                if base_key in _ACTIVE_SNAPSHOTS:
                    continue
        elif alive_check(pid):
            continue
        try:
            candidate.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _remove_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        try:
            if candidate.exists():
                candidate.unlink()
        except OSError:
            pass


def snapshot_database(source: Path, destination: Path) -> None:
    if destination.exists():
        destination.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(destination) + suffix)
        if extra.exists():
            extra.unlink()
    try:
        src = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
        dst = sqlite3.connect(destination)
        src.backup(dst)
        src.close()
        dst.close()
    except sqlite3.Error:
        shutil.copy2(source, destination)
        for suffix in ("-wal", "-shm"):
            extra = Path(str(source) + suffix)
            if extra.exists():
                shutil.copy2(extra, Path(str(destination) + suffix))


def display_title(label: str | None) -> str:
    title = " ".join((label or "").split())
    return title or "無題"


_NOISE = {
    "content",
    "en-note",
    "div",
    "span",
    "title",
    "customnotestyle",
    "customnotestyles",
    "headingstyles",
    "isempty",
    "meta",
    "resources",
    "fontfamily",
    "fontsize",
    "color",
    "fontweight",
    "fontstyle",
    "textdecoration",
    "inherit",
    "bold",
    "italic",
    "underline",
    "strike",
    "checkbox",
    "schemaversion",
    "left",
    "right",
    "center",
    "justify",
    "background",
    "font",
    "size",
    "link",
    "task",
    "list",
    "bullet",
    "ordered",
    "indent",
    "align",
    "heading",
    "paragraph",
    "normal",
    "default",
    "none",
    "true",
    "false",
    "null",
    "note",
    "style",
    "width",
    "height",
}


def _has_cjk(text: str) -> bool:
    return any(
        "\u3040" <= char <= "\u30ff" or "\u4e00" <= char <= "\u9fff" or "\uff00" <= char <= "\uffef"
        for char in text
    )


_URL_CHUNK_RE = re.compile(r"^(?:https?://|evernote:///)", re.IGNORECASE)
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_CAMEL_KEY_RE = re.compile(r"[a-z]{2,}(?:[A-Z][a-z0-9]+)+")


def _keep_chunk(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 2 or stripped.casefold() in _NOISE:
        return False
    if re.fullmatch(r"[0-9a-f-]{8,}", stripped) or _UUID_RE.fullmatch(stripped):
        return False
    if _URL_CHUNK_RE.match(stripped):
        return True
    if not _has_cjk(stripped):
        if not any(char.isalnum() for char in stripped):
            return False
        if _CAMEL_KEY_RE.fullmatch(stripped):
            return False
    words = re.findall(r"[A-Za-z]+", stripped)
    if words and not _has_cjk(stripped) and all(word.casefold() in _NOISE for word in words):
        return False
    return True


def extract_dat_text(data: bytes) -> str:
    """Pull readable text out of an Evernote note body file."""
    chunks: list[str] = []
    buffer = bytearray()

    def flush() -> None:
        if len(buffer) < 2:
            buffer.clear()
            return
        text = buffer.decode("utf-8", errors="ignore").strip()
        buffer.clear()
        if _keep_chunk(text):
            chunks.append(text)

    index = 0
    while index < len(data):
        byte = data[index]
        if 0x20 <= byte <= 0x7E or byte in (0x09, 0x0A):
            buffer.append(byte)
            index += 1
            continue
        if 0xC2 <= byte <= 0xDF and index + 1 < len(data) and 0x80 <= data[index + 1] <= 0xBF:
            buffer.extend(data[index : index + 2])
            index += 2
            continue
        if (
            0xE0 <= byte <= 0xEF
            and index + 2 < len(data)
            and 0x80 <= data[index + 1] <= 0xBF
            and 0x80 <= data[index + 2] <= 0xBF
        ):
            buffer.extend(data[index : index + 3])
            index += 3
            continue
        if (
            0xF0 <= byte <= 0xF4
            and index + 3 < len(data)
            and all(0x80 <= item <= 0xBF for item in data[index + 1 : index + 4])
        ):
            buffer.extend(data[index : index + 4])
            index += 4
            continue
        flush()
        index += 1
    flush()
    return "\n".join(chunks)


def find_content_dat(base_dir: Path, note_id: str) -> Path | None:
    root = base_dir / "conduit-fs" / SERVICE_DIR
    if not root.exists() or len(note_id) < 3:
        return None
    matches = list(
        root.glob(f"*/rte/Note/internal_rteDoc/{note_id[:3]}/{note_id[-3:]}/{note_id}.dat")
    )
    return matches[0] if matches else None


# def display_text(content: str | None, snippet: str | None) -> str:
#     body = (content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
#     if body:
#         return body
#     return (snippet or "").replace("\r\n", "\n").replace("\r", "\n").strip()
# 2026/09/23 変更 ---＞
def _normalize_newlines(text: str | None) -> str:
    body = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    body = body.replace("\\n", "\n").replace("/n", "\n")
    return body.strip()


def display_text(content: str | None, snippet: str | None) -> str:
    body = _normalize_newlines(content)
    if body:
        return body
    return _normalize_newlines(snippet)
# <--- 2026/09/23 変更


_LINE_BREAKS = (b"\x03div", b"\x02br")


def layout_search_text(content: str | None, data: bytes | None) -> str | None:
    """Keep search text, but break only where the note body starts a new line.

    Evernote's search index marks every text run with ``/n``. A visual line
    break is a ``div`` or ``br`` between those runs in the note body.
    """
    if not content or data is None or "/n" not in content:
        return None
    parts = content.split("/n")
    spans: list[tuple[int, int] | None] = []
    cursor = 0
    for part in parts:
        if not part:
            spans.append(None)
            continue
        raw = part.encode("utf-8")
        index = data.find(raw, cursor)
        if index < 0:
            return None
        spans.append((index, index + len(raw)))
        cursor = index + len(raw)

    pieces: list[str] = []
    for index, part in enumerate(parts):
        if index and _gap_is_line_break(data, spans, index):
            pieces.append("\n")
        pieces.append(part)
    body = "".join(pieces).replace("\r\n", "\n").replace("\r", "\n").replace("\\n", "\n")
    body = "\n".join(line.rstrip() for line in body.split("\n")).strip()
    return body or None


def _gap_is_line_break(data: bytes, spans: list[tuple[int, int] | None], index: int) -> bool:
    if spans[index] is None:
        return True
    previous = next((spans[item] for item in range(index - 1, -1, -1) if spans[item] is not None), None)
    current = spans[index]
    if previous is None or current is None:
        return True
    gap = data[previous[1] : current[0]]
    return any(token in gap for token in _LINE_BREAKS)


def evernote_app_url(owner: int | float | str, shard: str, note_id: str, parent_id: str | None) -> str:
    """Build the desktop link Evernote uses to open one note."""
    owner_id = int(float(owner))
    parent = parent_id or note_id
    return f"evernote:///view/{owner_id}/{shard}/{note_id}/{parent}"


class LocalEvernote:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir
        self._resolved_base: Path | None = None
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._snapshot: Path | None = None

    # def open(self) -> None:
    #     base = self.base_dir or default_base_dir()
    #     self._resolved_base = base
    #     source = find_database(base)
    #     snapshot_database(source, self._snapshot)
    #     connection = sqlite3.connect(self._snapshot, check_same_thread=False)
    #     connection.row_factory = sqlite3.Row
    #     with self._lock:
    #         if self._conn is not None:
    #             self._conn.close()
    #         self._conn = connection
    # 2026/09/23 変更 ---＞
    def open(self) -> None:
        base = self.base_dir or default_base_dir()
        self._resolved_base = base
        source = find_database(base)
        cleanup_stale_snapshots()
        destination = (
            Path(tempfile.gettempdir()) / f"eversticky-{os.getpid()}-{time.time_ns()}.sqlite"
        )
        _register_snapshot(destination)
        connection: sqlite3.Connection | None = None
        try:
            snapshot_database(source, destination)
            connection = sqlite3.connect(destination, check_same_thread=False)
            connection.row_factory = sqlite3.Row
        except Exception:
            if connection is not None:
                connection.close()
            _unregister_snapshot(destination)
            _remove_sqlite_files(destination)
            raise
        with self._lock:
            previous = self._conn
            previous_path = self._snapshot
            self._conn = connection
            self._snapshot = destination
        if previous is not None:
            previous.close()
        if previous_path is not None:
            _unregister_snapshot(previous_path)
            _remove_sqlite_files(previous_path)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            snapshot = self._snapshot
            self._snapshot = None
        if snapshot is not None:
            _unregister_snapshot(snapshot)
            _remove_sqlite_files(snapshot)

    def list_notebooks(self) -> list[LocalNotebook]:
        rows = self._query(
            "SELECT id, label FROM Nodes_Notebook ORDER BY label COLLATE NOCASE"
        )
        return [LocalNotebook(id=row["id"], name=display_title(row["label"])) for row in rows]

    def list_notes(self, notebook_id: str) -> list[LocalNoteSummary]:
        rows = self._query(
            """
            SELECT id, label
            FROM Nodes_Note
            WHERE deleted IS NULL AND parent_Notebook_id = ?
            ORDER BY updated DESC
            """,
            (notebook_id,),
        )
        return [
            LocalNoteSummary(
                id=row["id"],
                title=display_title(row["label"]),
                notebook_id=notebook_id,
            )
            for row in rows
        ]

    def get_note(self, note_id: str) -> LocalNote:
        rows = self._query(
            """
            SELECT n.id, n.label, n.parent_Notebook_id, n.snippet, c.content
            FROM Nodes_Note n
            LEFT JOIN Offline_Search_Note_Content c ON c.id = n.id
            WHERE n.id = ? AND n.deleted IS NULL
            """,
            (note_id,),
        )
        if not rows:
            raise LocalEvernoteError("ノートが見つかりません")
        row = rows[0]
        # text = display_text(row["content"], row["snippet"])
        # if not text and self._resolved_base is not None:
        #     dat_path = find_content_dat(self._resolved_base, row["id"])
        #     if dat_path is not None:
        #         text = extract_dat_text(dat_path.read_bytes())
        # 2026/09/23 変更 ---＞
        text = display_text(row["content"], row["snippet"])
        dat_path = None
        if self._resolved_base is not None:
            dat_path = find_content_dat(self._resolved_base, row["id"])
        if dat_path is not None:
            laid_out = layout_search_text(row["content"], dat_path.read_bytes())
            if laid_out:
                text = laid_out
            elif not text:
                text = extract_dat_text(dat_path.read_bytes())
        # <--- 2026/09/23 変更
        return LocalNote(
            id=row["id"],
            title=display_title(row["label"]),
            text=text,
            notebook_id=row["parent_Notebook_id"] or "",
        )

    def note_app_url(self, note_id: str) -> str:
        rows = self._query(
            """
            SELECT id, owner, shardId, parent_Notebook_id
            FROM Nodes_Note
            WHERE id = ? AND deleted IS NULL
            """,
            (note_id,),
        )
        if not rows:
            raise LocalEvernoteError("ノートが見つかりません")
        row = rows[0]
        if row["owner"] is None or not row["shardId"]:
            raise LocalEvernoteError("Evernoteでこのノートを開く情報がありません")
        return evernote_app_url(row["owner"], row["shardId"], row["id"], row["parent_Notebook_id"])

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            if self._conn is None:
                raise LocalEvernoteError("Evernoteのデータをまだ開いていません")
            return list(self._conn.execute(sql, params))
