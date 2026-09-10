"""Shared runtime bridge between threads and the App's tk event loop.

Threads that can't touch tkinter directly (web, hotkey, tray) post plain
tuples here; the App installs its ``queue.Queue`` via ``set_event_sink`` and
polls it on the main thread.

Event kinds handled by the App::

    ("show", None)                    toggle overlay
    ("escape", None)                  close / step back the overlay
    ("exit", None)                    shut down
    ("stop_playback", None)           cancel the currently playing macro
    ("test_macro", {exe, macro_id})   countdown + play a macro
    ("restart_web", None)             rebind the web UI (tray menu)
    ("restart_app", None)             relaunch SoftMacro (after an update)
"""

from __future__ import annotations

import queue
import threading

_sink: queue.Queue | None = None
_lock = threading.Lock()


def set_event_sink(sink: queue.Queue) -> None:
    global _sink
    with _lock:
        _sink = sink


def post(event: tuple) -> bool:
    """Post an event to the App. Returns False if no sink is installed."""
    with _lock:
        sink = _sink
    if sink is None:
        return False
    sink.put(event)
    return True
