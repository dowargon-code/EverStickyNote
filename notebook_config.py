"""Notebook names that may be shown as sticky notes."""

from __future__ import annotations

import tomllib
from pathlib import Path

from local_notes import LocalNotebook, display_title

TEMPLATE = """\
# 付箋として表示する Evernote のノートブック名です。
# 名前は Evernote 上の表示名と一致させてください。複数指定できます。
notebooks = []
"""


class NotebookConfigError(Exception):
    pass


def default_config_path() -> Path:
    return Path(__file__).resolve().parent / "config.toml"


def ensure_config(path: Path) -> None:
    if not path.exists():
        path.write_text(TEMPLATE, encoding="utf-8")


def load_notebook_names(path: Path) -> list[str]:
    ensure_config(path)
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise NotebookConfigError(f"config.toml を読めません: {exc}") from exc
    raw = data.get("notebooks", [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise NotebookConfigError("notebooks はノートブック名の配列にしてください")
    names: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise NotebookConfigError("notebooks にはノートブック名を書いてください")
        name = display_title(item)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def select_notebooks(
    notebooks: list[LocalNotebook], names: list[str]
) -> tuple[list[LocalNotebook], list[str]]:
    by_name: dict[str, LocalNotebook] = {}
    for notebook in notebooks:
        by_name.setdefault(display_title(notebook.name), notebook)
    matched: list[LocalNotebook] = []
    missing: list[str] = []
    for name in names:
        found = by_name.get(display_title(name))
        if found is None:
            missing.append(name)
        else:
            matched.append(found)
    return matched, missing
