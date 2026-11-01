"""Application icon for windows and the packaged executable."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtGui import QIcon


def icon_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS"))
    else:
        base = Path(__file__).resolve().parent
    return base / "assets" / "app-icon.png"


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    path = icon_path()
    if path.is_file():
        return QIcon(str(path))
    return QIcon()
