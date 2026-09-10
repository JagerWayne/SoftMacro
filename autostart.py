"""Windows startup (autorun) management.

Stores a value under ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``
so SoftMacro starts when the user logs in. Source installs launch
``pythonw.exe app.py``; frozen (installer) builds launch the exe directly.
"""

from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SoftMacro"


def _command() -> str:
    """The exact command line the Run key should execute."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    app = Path(__file__).resolve().parent / "app.py"
    return f'"{pythonw}" "{app}"'


def is_enabled() -> bool:
    """True if the Run key currently contains a SoftMacro entry."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return bool(value)
    except OSError:
        return False


def enable() -> None:
    """Create (or update) the Run key entry."""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())


def disable() -> None:
    """Remove the Run key entry (no-op if absent)."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except OSError:
        pass
