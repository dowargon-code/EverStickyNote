"""Notebook names that may be shown as sticky notes."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from local_notes import LocalNotebook, display_title

# TEMPLATE = """\
# # 付箋として表示する Evernote のノートブック名です。
# # 名前は Evernote 上の表示名と一致させてください。複数指定できます。
# notebooks = []
# """
# 2026/09/24 変更 ---＞
# TEMPLATE = """\
# # 付箋として表示する Evernote のノートブック名です。
# # 名前は Evernote 上の表示名と一致させてください。複数指定できます。
# notebooks = []
#
# # ローカルデータの確認間隔（秒）です。0 にすると定周期監視を止めます。
# watch_seconds = 2
# """
# <--- 2026/09/24 変更
# 2026/09/24 変更 ---＞
TEMPLATE = """\
# 付箋として表示する Evernote のノートブック名です。
# 名前は Evernote 上の表示名と一致させてください。複数指定できます。
notebooks = []

# ローカルデータの確認間隔（秒）です。0 にすると定周期監視を止めます。
watch_seconds = 2

# Windowsにログインしたとき、このアプリを起動します。
launch_at_startup = false

# 更新を知らせる枠の点滅時間（秒）です。
flicker_seconds = 5

# 非表示だった付箋を、点滅が終わったあと再び閉じます。
close_after_flicker = true
"""
# <--- 2026/09/24 変更


class NotebookConfigError(Exception):
    pass


def default_config_path() -> Path:
    # return Path(__file__).resolve().parent / "config.toml"
    # 2026/09/24 変更 ---＞
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config.toml"
    return Path(__file__).resolve().parent / "config.toml"
    # <--- 2026/09/24 変更


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


def load_watch_seconds(path: Path) -> float:
    ensure_config(path)
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise NotebookConfigError(f"config.toml を読めません: {exc}") from exc
    if "watch_seconds" not in data:
        return 2
    value = data["watch_seconds"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NotebookConfigError("watch_seconds は秒数にしてください")
    if value < 0:
        raise NotebookConfigError("watch_seconds は 0 以上にしてください")
    return float(value)


def load_launch_at_startup(path: Path) -> bool:
    ensure_config(path)
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise NotebookConfigError(f"config.toml を読めません: {exc}") from exc
    if "launch_at_startup" not in data:
        return False
    value = data["launch_at_startup"]
    if not isinstance(value, bool):
        raise NotebookConfigError("launch_at_startup は true か false にしてください")
    return value


def save_launch_at_startup(path: Path, enabled: bool) -> None:
    ensure_config(path)
    text = path.read_text(encoding="utf-8")
    line = f"launch_at_startup = {'true' if enabled else 'false'}"
    if re.search(r"(?m)^launch_at_startup\s*=", text):
        text = re.sub(r"(?m)^launch_at_startup\s*=.*$", line, text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n# Windowsにログインしたとき、このアプリを起動します。\n" + line + "\n"
    path.write_text(text, encoding="utf-8")


def load_flicker_seconds(path: Path) -> float:
    data = _load_config(path)
    if "flicker_seconds" not in data:
        return 5
    value = data["flicker_seconds"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NotebookConfigError("flicker_seconds は秒数にしてください")
    if value < 0:
        raise NotebookConfigError("flicker_seconds は 0 以上にしてください")
    return float(value)


def load_close_after_flicker(path: Path) -> bool:
    data = _load_config(path)
    if "close_after_flicker" not in data:
        return True
    value = data["close_after_flicker"]
    if not isinstance(value, bool):
        raise NotebookConfigError("close_after_flicker は true か false にしてください")
    return value


def _load_config(path: Path) -> dict:
    ensure_config(path)
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise NotebookConfigError(f"config.toml を読めません: {exc}") from exc


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
