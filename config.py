"""User-facing configuration (hotkeys, etc.).

Stored at ``%APPDATA%\\SoftMacro\\config.json`` as plain JSON. Defaults are
merged in on load so adding a new key never breaks an existing file.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

# Reference to the running HotkeyListener so the web UI can ask it to
# re-register hotkeys after the user edits them.
_hotkey_listener = None
_set_lock = threading.Lock()


DEFAULT_CONFIG: dict[str, Any] = {
    "hotkeys": {
        # ``keyboard`` library syntax: modifiers joined with '+', lowercase.
        "show_overlay":    "ctrl+z",
        "stop_playback":   "pause",
    },
    "overlay": {
        # Margins around the fullscreen overlay (pixels).
        "border_px":  20,
        # Base font size for row labels.
        "font_size":  18,
        # Window opacity (1.0 = opaque, 0.0 = invisible).
        "alpha":      0.75,
    },
    "web": {
        # Port for the local management UI. The server always binds to
        # 127.0.0.1 (loopback only), never to the network.
        "port": 5000,
    },
}

# The single-instance guard in app.py binds this loopback port; the web UI
# must never use it.
SINGLE_INSTANCE_PORT = 47777

WEB_PORT_MIN = 1024
WEB_PORT_MAX = 65535


def is_valid_web_port(port: int) -> bool:
    return WEB_PORT_MIN <= port <= WEB_PORT_MAX and port != SINGLE_INSTANCE_PORT


def get_web_port() -> int:
    """Return the configured web UI port (5000 when missing or invalid)."""
    cfg = load_config()
    try:
        port = int((cfg.get("web") or {}).get("port", 5000))
    except (TypeError, ValueError):
        port = 5000
    return port if is_valid_web_port(port) else 5000


def _config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".softmacro")
    return Path(base) / "SoftMacro" / "config.json"


def load_config() -> dict[str, Any]:
    """Load config, merging defaults for any missing keys."""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    path = _config_path()
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                on_disk = json.load(f)
            _deep_merge(cfg, on_disk)
        except Exception as e:
            print(f"[SoftMacro] config load failed ({e}); using defaults.")
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def set_hotkey_listener(listener) -> None:
    """Called by ``app.py`` after the listener is constructed."""
    global _hotkey_listener
    with _set_lock:
        _hotkey_listener = listener


def reload_hotkeys() -> bool:
    """Ask the running listener to re-read config. Returns True if it ran."""
    with _set_lock:
        listener = _hotkey_listener
    if listener is None:
        return False
    try:
        listener.reload()
        return True
    except Exception as e:
        print(f"[SoftMacro] hotkey reload failed: {e}")
        return False


def get_hotkey(action: str) -> str:
    """Return the configured combo for ``action`` (e.g. ``'show_overlay'``)."""
    cfg = load_config()
    return cfg.get("hotkeys", {}).get(action, DEFAULT_CONFIG["hotkeys"].get(action, ""))


def get_overlay_config() -> dict[str, Any]:
    """Return the overlay appearance config with defaults applied."""
    cfg = load_config()
    out = dict(DEFAULT_CONFIG["overlay"])
    out.update(cfg.get("overlay") or {})
    return out


# ---- helpers ---------------------------------------------------------------

def _deep_merge(dst: dict, src: dict) -> None:
    """Recursive dict merge -- ``src`` values win, ``dst`` keeps unknowns."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
