"""アプリのフォルダ（config.toml と position.toml を置く場所）を求める。"""

from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """EXE のときは EXE のフォルダ、ソースから動かすときはプロジェクトのフォルダ。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]
