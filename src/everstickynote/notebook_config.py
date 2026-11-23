"""Notebook names and app settings stored in config.toml."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from everstickynote.local_notes import LocalNotebook, display_title
from everstickynote.paths import app_root

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

# 新規作成したノートが取り込まれる Evernote 側のデフォルトノートブック名です（例: "0. Inbox"）。
# 表示するノートブック（notebooks）に含まれていない場合でも、このアプリから新規作成したノートだけを検知して付箋表示します。
default_notebook = ""
"""


class NotebookConfigError(Exception):
    pass


@dataclass
class AppConfig:
    notebooks: list[str]
    watch_seconds: float = 2.0
    launch_at_startup: bool = False
    flicker_seconds: float = 5.0
    close_after_flicker: bool = True
    default_notebook: str = ""
    import_dir: str = ""


def default_config_path() -> Path:
    return app_root() / "config.toml"


def ensure_config(path: Path) -> None:
    if not path.exists():
        path.write_text(TEMPLATE, encoding="utf-8")


def _load_config(path: Path) -> dict:
    ensure_config(path)
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise NotebookConfigError(f"config.toml を読めません: {exc}") from exc


def _parse_notebook_names(data: dict) -> list[str]:
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


def _parse_seconds(data: dict, key: str, default: float) -> float:
    if key not in data:
        return float(default)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NotebookConfigError(f"{key} は秒数にしてください")
    if value < 0:
        raise NotebookConfigError(f"{key} は 0 以上にしてください")
    return float(value)


def _parse_bool(data: dict, key: str, default: bool) -> bool:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise NotebookConfigError(f"{key} は true か false にしてください")
    return value


def _parse_import_dir(data: dict) -> str:
    if "import_dir" not in data:
        return ""
    value = data["import_dir"]
    if not isinstance(value, str):
        raise NotebookConfigError("import_dir はフォルダパス文字列にしてください")
    return value.strip()


def _parse_default_notebook(data: dict) -> str:
    if "default_notebook" not in data:
        return ""
    value = data["default_notebook"]
    if not isinstance(value, str):
        raise NotebookConfigError("default_notebook はノートブック名にしてください")
    if not value.strip():
        return ""
    return display_title(value)


def load_config(path: Path) -> AppConfig:
    data = _load_config(path)
    return AppConfig(
        notebooks=_parse_notebook_names(data),
        watch_seconds=_parse_seconds(data, "watch_seconds", 2),
        launch_at_startup=_parse_bool(data, "launch_at_startup", False),
        flicker_seconds=_parse_seconds(data, "flicker_seconds", 5),
        close_after_flicker=_parse_bool(data, "close_after_flicker", True),
        default_notebook=_parse_default_notebook(data),
        import_dir=_parse_import_dir(data),
    )


def load_notebook_names(path: Path) -> list[str]:
    return _parse_notebook_names(_load_config(path))


def load_watch_seconds(path: Path) -> float:
    return _parse_seconds(_load_config(path), "watch_seconds", 2)


def load_launch_at_startup(path: Path) -> bool:
    return _parse_bool(_load_config(path), "launch_at_startup", False)


def load_flicker_seconds(path: Path) -> float:
    return _parse_seconds(_load_config(path), "flicker_seconds", 5)


def load_close_after_flicker(path: Path) -> bool:
    return _parse_bool(_load_config(path), "close_after_flicker", True)


def load_default_notebook(path: Path) -> str:
    return _parse_default_notebook(_load_config(path))


def load_import_dir(path: Path) -> str:
    return _parse_import_dir(_load_config(path))


def save_launch_at_startup(path: Path, enabled: bool) -> None:
    save_config(path, launch_at_startup=enabled)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_number(value: float) -> str:
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.4f}".rstrip("0").rstrip(".")


def _find_key_span(lines: list[str], key: str) -> tuple[int, int] | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for start, line in enumerate(lines):
        if not pattern.match(line):
            continue
        depth = 0
        in_quote: str | None = None
        escaped = False
        first_chunk = line.split("=", 1)[1]
        for end in range(start, len(lines)):
            segment = first_chunk if end == start else lines[end]
            for ch in segment:
                if in_quote is not None:
                    if in_quote == '"' and not escaped and ch == "\\":
                        escaped = True
                        continue
                    if ch == in_quote and not escaped:
                        in_quote = None
                    escaped = False
                    continue
                if ch == "#":
                    break
                if ch in ('"', "'"):
                    in_quote = ch
                elif ch == "[":
                    depth += 1
                elif ch == "]":
                    depth = max(0, depth - 1)
            if depth == 0 and in_quote is None:
                return start, end
        return start, len(lines) - 1
    return None


def _upsert_toml_key(text: str, key: str, rendered_line: str, comment: str) -> str:
    lines = text.splitlines()
    span = _find_key_span(lines, key)
    if span is not None:
        start, end = span
        lines[start : end + 1] = [rendered_line]
        return "\n".join(lines) + "\n"
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(comment)
    lines.append(rendered_line)
    return "\n".join(lines) + "\n"


def save_config(
    path: Path,
    notebooks: list[str] | None = None,
    watch_seconds: float | None = None,
    flicker_seconds: float | None = None,
    close_after_flicker: bool | None = None,
    launch_at_startup: bool | None = None,
    default_notebook: str | None = None,
    import_dir: str | None = None,
) -> None:
    """Update specified settings in ``config.toml`` while preserving existing comments."""
    ensure_config(path)
    text = path.read_text(encoding="utf-8")

    if notebooks is not None:
        clean_names: list[str] = []
        seen: set[str] = set()
        for item in notebooks:
            if not isinstance(item, str):
                raise NotebookConfigError("notebooks にはノートブック名を書いてください")
            stripped = item.strip()
            if not stripped:
                continue
            name = display_title(stripped)
            if name not in seen:
                seen.add(name)
                clean_names.append(name)
        rendered = "notebooks = [" + ", ".join(_toml_string(n) for n in clean_names) + "]"
        text = _upsert_toml_key(
            text,
            "notebooks",
            rendered,
            "# 付箋として表示する Evernote のノートブック名です。",
        )

    if watch_seconds is not None:
        if isinstance(watch_seconds, bool) or not isinstance(watch_seconds, (int, float)):
            raise NotebookConfigError("watch_seconds は秒数にしてください")
        if watch_seconds < 0:
            raise NotebookConfigError("watch_seconds は 0 以上にしてください")
        text = _upsert_toml_key(
            text,
            "watch_seconds",
            f"watch_seconds = {_toml_number(watch_seconds)}",
            "# ローカルデータの確認間隔（秒）です。0 にすると定周期監視を止めます。",
        )

    if launch_at_startup is not None:
        if not isinstance(launch_at_startup, bool):
            raise NotebookConfigError("launch_at_startup は true か false にしてください")
        text = _upsert_toml_key(
            text,
            "launch_at_startup",
            f"launch_at_startup = {'true' if launch_at_startup else 'false'}",
            "# Windowsにログインしたとき、このアプリを起動します。",
        )

    if flicker_seconds is not None:
        if isinstance(flicker_seconds, bool) or not isinstance(flicker_seconds, (int, float)):
            raise NotebookConfigError("flicker_seconds は秒数にしてください")
        if flicker_seconds < 0:
            raise NotebookConfigError("flicker_seconds は 0 以上にしてください")
        text = _upsert_toml_key(
            text,
            "flicker_seconds",
            f"flicker_seconds = {_toml_number(flicker_seconds)}",
            "# 更新を知らせる枠の点滅時間（秒）です。",
        )

    if close_after_flicker is not None:
        if not isinstance(close_after_flicker, bool):
            raise NotebookConfigError("close_after_flicker は true か false にしてください")
        text = _upsert_toml_key(
            text,
            "close_after_flicker",
            f"close_after_flicker = {'true' if close_after_flicker else 'false'}",
            "# 非表示だった付箋を、点滅が終わったあと再び閉じます。",
        )

    if default_notebook is not None:
        if not isinstance(default_notebook, str):
            raise NotebookConfigError("default_notebook はノートブック名にしてください")
        clean_default = display_title(default_notebook) if default_notebook.strip() else ""
        text = _upsert_toml_key(
            text,
            "default_notebook",
            f"default_notebook = {_toml_string(clean_default)}",
            "# 新規作成したノートが取り込まれる Evernote 側のデフォルトノートブック名です（例: \"0. Inbox\"）。\n"
            "# 表示するノートブック（notebooks）に含まれていない場合でも、このアプリから新規作成したノートだけを検知して付箋表示します。",
        )

    if import_dir is not None:
        if not isinstance(import_dir, str):
            raise NotebookConfigError("import_dir はフォルダパス文字列にしてください")
        text = _upsert_toml_key(
            text,
            "import_dir",
            f"import_dir = {_toml_string(import_dir.strip())}",
            "# 新規ノート作成時に .enex ファイルを出力する Evernote のインポートフォルダです（空欄可）。",
        )

    path.write_text(text, encoding="utf-8")


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
