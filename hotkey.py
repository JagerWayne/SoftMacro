"""Global hotkey listener using the ``keyboard`` library.

Hotkeys are read from ``config.py`` so the user can change them from the
web UI without restarting the app. ``reload()`` re-registers the hooks on
demand.

Registered actions (posted onto the app queue):
    show_overlay    -> ("show", None)           toggle the overlay
    stop_playback   -> ("stop_playback", None)  cancel a playing macro

While the overlay is visible, Esc is captured globally (see
``register_overlay_escape``) and posts ``("escape", None)`` so it closes the
overlay even when the window did not get keyboard focus.
"""

from __future__ import annotations

import queue
import re
import threading

import keyboard

import config


# Event tuples posted onto the queue
EVT_SHOW_OVERLAY = ("show", None)

# name -> event tuple to post
_ACTIONS: dict[str, tuple] = {
    "show_overlay":  ("show", None),
    "stop_playback": ("stop_playback", None),
}

# Esc is captured globally only while the overlay is open, so it always
# closes (or steps back through) the overlay even when the window did not
# get keyboard focus. ``_esc_handle`` is the ``keyboard`` hotkey handle.
_esc_handle = None
_esc_lock = threading.Lock()


def register_overlay_escape(sink: queue.Queue) -> None:
    """Start capturing Esc globally (no-op if already capturing)."""
    global _esc_handle
    with _esc_lock:
        if _esc_handle is not None:
            return
        _esc_handle = keyboard.add_hotkey(
            "esc", lambda: sink.put(("escape", None)), suppress=True
        )


def unregister_overlay_escape() -> None:
    """Stop capturing Esc globally (safe to call when not capturing)."""
    global _esc_handle
    with _esc_lock:
        if _esc_handle is None:
            return
        try:
            keyboard.remove_hotkey(_esc_handle)
        except Exception:
            pass
        _esc_handle = None


def _take_esc_handle():
    """Forget the Esc handle (used after ``unhook_all_hotkeys``)."""
    global _esc_handle
    with _esc_lock:
        handle, _esc_handle = _esc_handle, None
        return handle


_KEY_ERROR = re.compile(r"Key '([^']+)' is not mapped")


def validate_combo(combo: str) -> str | None:
    """Return an error message when ``combo`` isn't a valid hotkey.

    Uses the ``keyboard`` library's own parser, so it accepts exactly the
    key names the library can register.
    """
    try:
        keyboard.parse_hotkey(combo)
    except Exception as e:
        match = _KEY_ERROR.search(str(e))
        if match:
            return f"Unknown key '{match.group(1)}'."
        return "Not a valid key combination."
    return None


class HotkeyListener(threading.Thread):
    daemon = True

    def __init__(self, sink: queue.Queue) -> None:
        super().__init__(name="softmacro-hotkey")
        self.sink = sink
        self._stopped = False
        self._lock = threading.Lock()

    def run(self) -> None:
        with self._lock:
            self._register_all()
        port = config.get_web_port()
        print(
            "[SoftMacro] Hotkeys registered "
            f"(change via Settings -> http://127.0.0.1:{port}/settings)"
        )
        try:
            keyboard.wait()
        except Exception as e:
            if not self._stopped:
                print(f"[SoftMacro] hotkey listener exited: {e}")

    # ------------------------------------------------------- public api

    def stop(self) -> None:
        self._stopped = True
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

    def reload(self) -> None:
        """Unregister everything and re-register from current config.

        Safe to call from any thread.
        """
        with self._lock:
            try:
                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
            # unhook_all_hotkeys() also dropped the overlay Esc capture.
            esc_was_active = _take_esc_handle() is not None
            try:
                self._register_all()
                if esc_was_active:
                    register_overlay_escape(self.sink)
                print("[SoftMacro] Hotkeys reloaded.")
            except Exception as e:
                print(f"[SoftMacro] hotkey reload failed: {e}")

    # ---------------------------------------------------------- internal

    def _register_all(self) -> None:
        cfg = config.load_config()
        hk = cfg.get("hotkeys", {}) or {}
        for name, evt in _ACTIONS.items():
            combo = hk.get(name)
            if combo:
                keyboard.add_hotkey(
                    combo,
                    lambda e=evt: self.sink.put(e),
                    suppress=True,
                )
                print(f"[SoftMacro]   {name} = {combo}")
            else:
                print(f"[SoftMacro]   {name} = (disabled)")
