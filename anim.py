"""Lightweight tween/animation helpers for the tkinter overlay.

Everything here runs on the Tk main thread: frames are scheduled with
``widget.after`` and callbacks are invoked there. This module never touches
widgets from another thread (see AGENTS.md).

Usage::

    animator = Animator(self.win)
    animator.run(160, lambda e: self.win.attributes("-alpha", e),
                 on_done=self._finish_open)

Values passed to ``on_frame`` are the *eased* progress in ``[0.0, 1.0]``.
Every handle is cancellable, and runs sharing a ``key`` replace each other so
a widget never has two tweens fighting over the same property.
"""

from __future__ import annotations

import time
import tkinter as tk
from typing import Callable

# ---- easing -----------------------------------------------------------------


def linear(t: float) -> float:
    return t


def ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_quad(t: float) -> float:
    if t < 0.5:
        return 2.0 * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 2) / 2.0


EASINGS: dict[str, Callable[[float], float]] = {
    "linear": linear,
    "ease_out_cubic": ease_out_cubic,
    "ease_in_out_quad": ease_in_out_quad,
}


# ---- value helpers -----------------------------------------------------------


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _channel(hex_color: str, index: int) -> int:
    return int(hex_color[index:index + 2], 16)


def lerp_color(c1: str, c2: str, t: float) -> str:
    """Blend two ``#rrggbb`` colors. ``t=0`` -> c1, ``t=1`` -> c2."""
    if t <= 0:
        return c1
    if t >= 1:
        return c2
    a = "#%02x%02x%02x" % (
        round(lerp(_channel(c1, 1), _channel(c2, 1), t)),
        round(lerp(_channel(c1, 3), _channel(c2, 3), t)),
        round(lerp(_channel(c1, 5), _channel(c2, 5), t)),
    )
    return a


# ---- animation engine --------------------------------------------------------


class _Handle:
    """A single scheduled animation/delayed callback."""

    __slots__ = ("_owner", "key", "_after_id", "cancelled")

    def __init__(self, owner: "Animator", key) -> None:
        self._owner = owner
        self.key = key
        self._after_id = None
        self.cancelled = False

    def cancel(self) -> None:
        if self.cancelled:
            return
        self.cancelled = True
        if self._after_id is not None:
            try:
                self._owner.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._owner._forget(self)

    def _complete(self) -> None:
        self.cancelled = True
        self._owner._forget(self)


class Animator:
    """Schedules tweens and delayed callbacks on one Tk widget."""

    def __init__(self, widget) -> None:
        self.widget = widget
        self._active: set[_Handle] = set()

    # ------------------------------------------------------------- public

    def run(
        self,
        duration_ms: float,
        on_frame: Callable[[float], None],
        *,
        on_done: Callable[[], None] | None = None,
        easing: Callable[[float], float] = ease_out_cubic,
        fps: int = 40,
        key=None,
    ) -> _Handle:
        """Tween ``on_frame(eased)`` over ``duration_ms``.

        ``key`` groups runs: starting a new one with the same key cancels the
        previous, so a widget property is never driven by two tweens at once.
        """
        self._cancel_key(key)
        handle = _Handle(self, key)
        self._active.add(handle)

        duration = max(0.0, float(duration_ms) / 1000.0)
        interval = max(1, int(round(1000.0 / max(1, int(fps)))))
        start = time.monotonic()

        def step() -> None:
            if handle.cancelled:
                return
            if duration <= 0:
                progress = 1.0
            else:
                progress = min(1.0, (time.monotonic() - start) / duration)
            try:
                on_frame(easing(progress))
            except tk.TclError:
                handle.cancel()
                return
            if progress >= 1.0:
                handle._complete()
                if on_done is not None:
                    try:
                        on_done()
                    except tk.TclError:
                        pass
                return
            handle._after_id = self.widget.after(interval, step)

        step()
        return handle

    def after(self, delay_ms: int, callback: Callable[[], None], *, key=None) -> _Handle:
        """Schedule a one-shot ``callback`` after ``delay_ms`` (cancellable)."""
        self._cancel_key(key)
        handle = _Handle(self, key)
        self._active.add(handle)

        def fire() -> None:
            if handle.cancelled:
                return
            try:
                callback()
            except tk.TclError:
                handle.cancel()
                return
            handle._complete()

        handle._after_id = self.widget.after(max(0, int(delay_ms)), fire)
        return handle

    def cancel_all(self) -> None:
        """Cancel every pending tween and delayed callback."""
        for handle in list(self._active):
            handle.cancel()

    def cancel(self, key) -> None:
        """Cancel pending runs that were started with ``key``."""
        self._cancel_key(key)

    # ---------------------------------------------------------- internal

    def _cancel_key(self, key) -> None:
        if key is None:
            return
        for handle in list(self._active):
            if handle.key == key:
                handle.cancel()

    def _forget(self, handle: _Handle) -> None:
        self._active.discard(handle)
