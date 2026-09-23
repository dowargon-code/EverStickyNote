"""Local window layout and the Evernote token. The token is not kept in source."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

DEFAULT_COLOR = "yellow"


def default_db_path() -> Path:
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home()
    directory = root / "EverStickyNote"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "state.sqlite"


@dataclass
class NoteWindowState:
    guid: str
    is_open: bool
    x: int | None
    y: int | None
    width: int | None
    height: int | None
    color: str
    pinned: bool
    last_usn: int | None


class LocalStore:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS note_state (
                guid TEXT PRIMARY KEY,
                is_open INTEGER NOT NULL DEFAULT 0,
                x INTEGER,
                y INTEGER,
                width INTEGER,
                height INTEGER,
                color TEXT NOT NULL DEFAULT 'yellow',
                pinned INTEGER NOT NULL DEFAULT 1,
                last_usn INTEGER
            );
            """
        )
        self._conn.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return row["value"]

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self._conn.commit()

    def get_token(self) -> str:
        return self.get_setting("token", "") or ""

    def set_token(self, token: str) -> None:
        self.set_setting("token", token.strip())

    def get_notebook_guid(self) -> str:
        return self.get_setting("notebook_guid", "") or ""

    def set_notebook_guid(self, guid: str) -> None:
        self.set_setting("notebook_guid", guid)

    def get_note_state(self, guid: str) -> NoteWindowState:
        row = self._conn.execute(
            "SELECT * FROM note_state WHERE guid = ?", (guid,)
        ).fetchone()
        if row is None:
            return NoteWindowState(
                guid=guid,
                is_open=False,
                x=None,
                y=None,
                width=None,
                height=None,
                color=DEFAULT_COLOR,
                pinned=True,
                last_usn=None,
            )
        return NoteWindowState(
            guid=row["guid"],
            is_open=bool(row["is_open"]),
            x=row["x"],
            y=row["y"],
            width=row["width"],
            height=row["height"],
            color=row["color"] or DEFAULT_COLOR,
            pinned=bool(row["pinned"]),
            last_usn=row["last_usn"],
        )

    def save_note_state(self, state: NoteWindowState) -> None:
        self._conn.execute(
            """
            INSERT INTO note_state (
                guid, is_open, x, y, width, height, color, pinned, last_usn
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guid) DO UPDATE SET
                is_open = excluded.is_open,
                x = excluded.x,
                y = excluded.y,
                width = excluded.width,
                height = excluded.height,
                color = excluded.color,
                pinned = excluded.pinned,
                last_usn = excluded.last_usn
            """,
            (
                state.guid,
                1 if state.is_open else 0,
                state.x,
                state.y,
                state.width,
                state.height,
                state.color or DEFAULT_COLOR,
                1 if state.pinned else 0,
                state.last_usn,
            ),
        )
        self._conn.commit()

    def set_open(self, guid: str, is_open: bool) -> None:
        state = self.get_note_state(guid)
        state.is_open = is_open
        self.save_note_state(state)

    def set_last_usn(self, guid: str, usn: int) -> None:
        state = self.get_note_state(guid)
        state.last_usn = usn
        self.save_note_state(state)
