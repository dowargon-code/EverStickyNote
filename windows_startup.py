"""Register this app to start when Windows signs in."""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "EverStickyNote"


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main = Path(__file__).resolve().parent / "main.py"
    return f'"{sys.executable}" "{main}"'


def set_launch_at_startup(enabled: bool, command: str | None = None) -> None:
    command = startup_command() if command is None else command
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
            return
        try:
            winreg.DeleteValue(key, RUN_NAME)
        except FileNotFoundError:
            pass
