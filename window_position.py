"""Sticky positions and whether the main window was closed minimized."""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NotePosition:
    x: int
    y: int
    width: int
    height: int
    visible: bool = True


@dataclass
class WindowLayout:
    minimized: bool = False
    notes: dict[str, NotePosition] = field(default_factory=dict)


def default_position_path() -> Path:
    # return Path(__file__).resolve().parent / "position.toml"
    # 2026/09/24 変更 ---＞
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "position.toml"
    return Path(__file__).resolve().parent / "position.toml"
    # <--- 2026/09/24 変更


def load_layout(path: Path) -> WindowLayout:
    if not path.exists():
        return WindowLayout()
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return WindowLayout()
    notes: dict[str, NotePosition] = {}
    raw_notes = data.get("notes", {})
    if isinstance(raw_notes, dict):
        for note_id, raw in raw_notes.items():
            position = _note_position(raw)
            if position is not None:
                notes[str(note_id)] = position
    return WindowLayout(minimized=data.get("minimized") is True, notes=notes)


def save_layout(path: Path, layout: WindowLayout) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(_render(layout), encoding="utf-8")
    os.replace(temporary, path)


def _note_position(raw: object) -> NotePosition | None:
    if not isinstance(raw, dict):
        return None
    values: list[int] = []
    for key in ("x", "y", "width", "height"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        values.append(value)
    if values[2] < 1 or values[3] < 1:
        return None
    visible = raw.get("visible", True)
    if not isinstance(visible, bool):
        return None
    return NotePosition(*values, visible=visible)


def _render(layout: WindowLayout) -> str:
    lines = [
        "# 付箋の位置と、本体フォームを最小化の状態で閉じたかを記録します。",
        f"minimized = {'true' if layout.minimized else 'false'}",
        "",
    ]
    for note_id, position in layout.notes.items():
        lines.append(f"[notes.{_quoted(note_id)}]")
        lines.append(f"x = {position.x}")
        lines.append(f"y = {position.y}")
        lines.append(f"width = {position.width}")
        lines.append(f"height = {position.height}")
        lines.append(f"visible = {'true' if position.visible else 'false'}")
        lines.append("")
    return "\n".join(lines)


def _quoted(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
