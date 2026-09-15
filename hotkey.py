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
from typing import Callable

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
    """Start watching Esc globally (no-op if already watching).

    Deliberately **not** suppressed. ``add_hotkey(..., suppress=True)``
    never fires for a single non-modifier key in the ``keyboard`` library,
    and suppressing Esc there also stops the overlay's own Tk ``<Escape>``
    binding from ever seeing the key -- so Esc did nothing at all. Leaving
    it unsuppressed means both the global hook and the focused overlay can
    handle it (``Overlay.handle_escape`` debounces the double call), which
    keeps Esc working even if one of the two paths is unavailable.
    """
    global _esc_handle
    with _esc_lock:
        if _esc_handle is not None:
            return

        def on_esc(event) -> None:
            if event.event_type == keyboard.KEY_DOWN:
                sink.put(("escape", None))

        _esc_handle = keyboard.hook_key("esc", on_esc, suppress=False)


def unregister_overlay_escape() -> None:
    """Stop capturing Esc globally (safe to call when not capturing)."""
    global _esc_handle
    with _esc_lock:
        if _esc_handle is None:
            return
        try:
            keyboard.unhook(_esc_handle)
        except Exception:
            pass
        _esc_handle = None


def _esc_active() -> bool:
    with _esc_lock:
        return _esc_handle is not None


def _register_action(combo: str, callback) -> Callable[[], None]:
    """Register one action hotkey and return a function that removes it.

    ``keyboard.add_hotkey(..., suppress=True)`` never fires when the hotkey
    is a single non-modifier key (e.g. the default ``pause``), so single
    keys use ``hook_key``, which can block one key. Combos keep using
    ``add_hotkey``. The returned remover hides the different teardown APIs
    (``remove_hotkey`` vs ``unhook``).
    """
    if "+" in combo:
        handle = keyboard.add_hotkey(combo, callback, suppress=True)
        return lambda: keyboard.remove_hotkey(handle)

    def on_key(event) -> bool:
        if event.event_type == keyboard.KEY_DOWN:
            callback()
        return False

    handle = keyboard.hook_key(combo, on_key, suppress=True)
    return lambda: keyboard.unhook(handle)


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
        self._removers: list[Callable[[], None]] = []

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
        unregister_overlay_escape()
        self._unregister_all()

    def reload(self) -> None:
        """Unregister everything and re-register from current config.

        Safe to call from any thread.
        """
        with self._lock:
            # unhook_all_hotkeys() does NOT clear single-key hooks (the
            # overlay Esc capture and any single-key action), so remove them
            # explicitly first.
            esc_was_active = _esc_active()
            unregister_overlay_escape()
            self._unregister_all()
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
                try:
                    self._removers.append(
                        _register_action(combo, lambda e=evt: self.sink.put(e))
                    )
                    print(f"[SoftMacro]   {name} = {combo}")
                except Exception as e:
                    print(f"[SoftMacro]   {name} = {combo} (failed: {e})")
            else:
                print(f"[SoftMacro]   {name} = (disabled)")

    def _unregister_all(self) -> None:
        for remove in self._removers:
            try:
                remove()
            except Exception:
                pass
        self._removers = []
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
