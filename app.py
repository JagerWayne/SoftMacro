"""SoftMacro entry point.

Threads:
    main thread       - tkinter main loop (tkinter is not thread-safe)
    daemon: hotkey    - global hotkeys (overlay / stop playback)
    daemon: web       - Flask serving the management UI on 127.0.0.1 (port from Settings)
    daemon: playback  - one short-lived thread per macro playback

The overlay is a *playback-only* surface. Macros are created and assigned
in the web UI. When the user presses a slot key on the overlay:

    1. the overlay hides itself,
    2. focus is switched back to the application that was foreground when
       the hotkey was pressed (so the macro lands in the right app),
    3. the macro plays in a background thread after a short settle delay.

Events flow: hotkey/web/tray threads -> queue.Queue -> main thread polls
via ``root.after`` and updates the overlay.
"""

from __future__ import annotations

import os
import queue
import socket
import sys
import threading
import time
from pathlib import Path

import config
import runtime
import storage
import web
import window_info
from hotkey import (
    HotkeyListener,
    register_overlay_escape,
    unregister_overlay_escape,
)
from overlay import Overlay
from player import play

try:
    from tray import TrayIcon
    _TRAY_AVAILABLE = True
except Exception:
    _TRAY_AVAILABLE = False


class App:
    def __init__(self) -> None:
        self.queue: queue.Queue = queue.Queue()
        runtime.set_event_sink(self.queue)

        self.current_exe_name: str | None = None
        self.current_app: dict | None = None
        # HWND of the app that was foreground when the overlay opened.
        # Focus is restored here before a macro plays.
        self.target_hwnd: int | None = None
        # True while the overlay window is visible (drives the hotkey toggle).
        self.overlay_open: bool = False
        # Set to cancel the currently playing macro.
        self.playback_cancel: threading.Event | None = None

        overlay_cfg = config.get_overlay_config()
        self.overlay = Overlay(
            on_play=self._on_play,
            on_close=self._on_overlay_close,
            border_px=overlay_cfg["border_px"],
            font_size=overlay_cfg["font_size"],
            alpha=overlay_cfg["alpha"],
        )

        self.hotkey: HotkeyListener | None = None
        self.web_thread: threading.Thread | None = None
        self.tray: TrayIcon | None = None

    # ---------------------------------------------------------------- boot

    def run(self) -> None:
        # Web UI (127.0.0.1, port configurable in Settings) on its own daemon thread.
        self.web_thread = web.start_in_thread()

        # Hotkey listener on its own daemon thread.
        self.hotkey = HotkeyListener(self.queue)
        self.hotkey.start()
        # Let the web UI ask the listener to re-register hotkeys when
        # the user edits them on the /settings page.
        config.set_hotkey_listener(self.hotkey)

        # System-tray icon -- the visible home when running headless.
        if _TRAY_AVAILABLE:
            self.tray = TrayIcon(self.queue)
            try:
                self.tray.start()
                print("[SoftMacro] Tray icon ready (right-click for menu).")
            except Exception as e:
                print(f"[SoftMacro] tray icon failed: {e}")
                self.tray = None

        # Tkinter runs the main loop on the main thread and polls our queue.
        self.overlay.after(50, self._poll_queue)

        print("[SoftMacro] Ready. Press your hotkey in any application.")
        try:
            self.overlay.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()
        sys.exit(0)

    def _shutdown(self) -> None:
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        try:
            if self.hotkey:
                self.hotkey.stop()
        except Exception:
            pass
        try:
            root = self.overlay.root
            root.after(0, root.destroy)
        except Exception:
            pass

    def _restart(self) -> None:
        """Relaunch SoftMacro (after an update) and exit this process."""
        print("[SoftMacro] Restarting ...")
        # Release the single-instance guard so the new process can bind it.
        global _guard_socket
        if _guard_socket is not None:
            try:
                _guard_socket.close()
            except Exception:
                pass
            _guard_socket = None
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        try:
            if self.hotkey:
                self.hotkey.stop()
        except Exception:
            pass
        try:
            import subprocess

            if getattr(sys, "frozen", False):
                cmd = [sys.executable]
                cwd = str(Path(sys.executable).resolve().parent)
            else:
                cmd = [sys.executable, str(Path(__file__).resolve())]
                cwd = str(Path(__file__).resolve().parent)
            subprocess.Popen(
                cmd,
                cwd=cwd,
                close_fds=True,
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            )
        except Exception as e:
            print(f"[SoftMacro] restart failed: {e}")
        os._exit(0)

    # ------------------------------------------------------ queue dispatch

    def _poll_queue(self) -> None:
        try:
            while True:
                evt = self.queue.get_nowait()
                self._handle_event(evt)
        except queue.Empty:
            pass
        # Re-arm; this is the only thing that keeps tkinter ticking.
        self.overlay.after(50, self._poll_queue)

    def _handle_event(self, evt: tuple) -> None:
        kind, payload = evt
        if kind == "show":
            # Hotkey toggles: open when hidden, close when visible.
            if self.overlay_open:
                self._hide_overlay()
            else:
                self._show_overlay()
        elif kind == "escape":
            # Global Esc hook: close the overlay (or step back a group).
            self.overlay.handle_escape()
        elif kind == "restart_web":
            # Tray menu: rebind the web UI (picks up a changed port).
            web.restart_in_thread()
            print("[SoftMacro] Restarting web UI ...")
        elif kind == "restart_app":
            # Update installed: relaunch SoftMacro with the new code.
            self._restart()
        elif kind == "exit":
            self._shutdown()
        elif kind == "stop_playback":
            if self.playback_cancel is not None:
                self.playback_cancel.set()
                print("[SoftMacro] Playback cancelled.")
        elif kind == "test_macro":
            self._test_macro(payload or {})
        elif kind == "apply_overlay_settings":
            self._apply_overlay_settings(payload or {})

    # --------------------------------------------------------- show/hide

    def _show_overlay(self) -> None:
        hwnd, fg = window_info.foreground_window()

        # If the overlay itself (or something we can't identify) is in
        # front, keep using whatever app we last opened the overlay for.
        if not fg or fg == window_info.current_exe():
            fg = self.current_exe_name or "unknown.exe"
            # Keep the previous target hwnd so playback still lands
            # somewhere sensible.
            hwnd = self.target_hwnd
        else:
            self.target_hwnd = hwnd

        self.current_exe_name = fg
        self.current_app = storage.load_app(fg)
        macros_by_id = {m["id"]: m for m in self.current_app.get("macros", [])}
        groups = self.current_app.get("groups", [])
        self.overlay_open = True
        self.overlay.show(
            app_name=self.current_app.get("display_name", fg),
            app_exe=fg,
            slots=self.current_app.get("slots", {}),
            macros=macros_by_id,
            groups=groups,
        )
        self.overlay.update_state(
            slots=self.current_app.get("slots", {}),
            macros=macros_by_id,
            groups=groups,
            status="",
        )
        # Capture Esc globally while the overlay is visible so it closes
        # even if the window didn't get keyboard focus.
        register_overlay_escape(self.queue)

    def _hide_overlay(self) -> None:
        self.overlay.hide()

    def _on_overlay_close(self) -> None:
        # The overlay was hidden (Esc, close button, or before playback).
        self.overlay_open = False
        unregister_overlay_escape()

    def _apply_overlay_settings(self, cfg: dict) -> None:
        self.overlay.apply_settings(
            border_px=cfg.get("border_px"),
            font_size=cfg.get("font_size"),
            alpha=cfg.get("alpha"),
        )

    # --------------------------------------------------------------- play

    def _on_play(self, slot: str) -> None:
        if self.current_app is None or self.current_exe_name is None:
            return

        # Resolve the target for the overlay's current view: inside a group
        # the target is always a macro; in the main view the overlay only
        # calls us for macro targets (group keys open submenus itself).
        group_id = self.overlay.current_group_id
        if group_id:
            group = storage.get_group(self.current_exe_name, group_id)
            macro_id = (group or {}).get("slots", {}).get(slot)
        else:
            macro_id = self.current_app.get("slots", {}).get(slot)

        if not macro_id:
            self.overlay.update_state(status=f"Slot {slot} has no macro assigned.")
            return
        macro = next(
            (m for m in self.current_app.get("macros", []) if m["id"] == macro_id),
            None,
        )
        if not macro:
            self.overlay.update_state(status=f"Slot {slot}'s macro was deleted.")
            return

        # 1. Hide the overlay so it doesn't swallow the replayed input or
        #    keep focus.
        self.overlay.hide()

        # 2. Switch focus back to the app that was foreground when the
        #    hotkey was pressed, so the macro plays against it.
        if self.target_hwnd:
            ok = window_info.set_foreground(self.target_hwnd)
            if not ok:
                print("[SoftMacro] warning: SetForegroundWindow failed")

        self._start_playback(macro, settle=0.5, count_play=True)

    def _test_macro(self, payload: dict) -> None:
        """Countdown + play a macro (from the web UI's Test button).

        The countdown window does not steal focus, so the user can click
        the target app while it ticks down.
        """
        exe = payload.get("exe")
        macro_id = payload.get("macro_id")
        if not exe or not macro_id:
            return
        macro = storage.get_macro(exe, macro_id)
        if macro is None:
            print(f"[SoftMacro] test: macro {macro_id} not found on {exe}")
            return

        # Make sure the overlay isn't sitting over the target app.
        self.overlay.hide()

        self.overlay.show_countdown(
            3,
            on_done=lambda: self._start_playback(macro, settle=0.3, count_play=False),
            on_cancel=lambda: print("[SoftMacro] Test cancelled."),
        )

    def _start_playback(self, macro: dict, settle: float, count_play: bool) -> None:
        events = [list(ev) for ev in macro.get("events", [])]
        name = macro.get("name", macro.get("id", "macro"))
        try:
            repeat = max(1, min(999, int(macro.get("repeat", 1) or 1)))
        except (TypeError, ValueError):
            repeat = 1
        try:
            speed = max(0.1, min(10.0, float(macro.get("speed", 1.0) or 1.0)))
        except (TypeError, ValueError):
            speed = 1.0

        self.playback_cancel = threading.Event()
        cancel = self.playback_cancel

        if count_play:
            try:
                storage.touch_macro(self.current_exe_name or "unknown.exe", macro["id"])
            except Exception as e:
                print(f"[SoftMacro] touch_macro failed: {e}")

        def run():
            time.sleep(settle)
            print(
                f"[SoftMacro] playing \"{name}\" "
                f"({len(events)} events, repeat={repeat}, speed={speed}) "
                f"on {self.current_exe_name}"
            )
            try:
                play(events, repeat=repeat, speed=speed, cancel_event=cancel)
            except Exception as e:
                print(f"[SoftMacro] playback error: {e}")

        threading.Thread(target=run, daemon=True, name="softmacro-playback").start()


def main() -> None:
    _redirect_stdout_if_headless()
    if not _acquire_single_instance():
        print("[SoftMacro] Another instance is already running -- exiting.")
        return
    print("[SoftMacro] Single-instance lock acquired.")
    App().run()


# ---- single instance + headless logging ------------------------------------

_guard_socket: socket.socket | None = None


def _acquire_single_instance() -> bool:
    """Bind a loopback port as a cheap single-instance lock.

    The OS releases it automatically when the process exits, so a crashed
    instance never leaves a stale lock behind.
    """
    global _guard_socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", config.SINGLE_INSTANCE_PORT))
        s.listen(1)
    except OSError:
        s.close()
        return False
    _guard_socket = s
    return True


def _redirect_stdout_if_headless() -> None:
    """Under pythonw.exe there is no console -- route prints to a log file."""
    if sys.stdout is not None:
        return
    import os
    base = os.environ.get("APPDATA") or str(Path.home())
    log_dir = Path(base) / "SoftMacro"
    log_dir.mkdir(parents=True, exist_ok=True)
    f = open(log_dir / "softmacro.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = f
    sys.stderr = f


if __name__ == "__main__":
    main()
