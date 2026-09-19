"""Startup splash screen shown while SoftMacro boots.

A small frameless, rounded window with the product mark, version and an
indeterminate progress sweep. It fades in, holds for a moment, then fades
out. Everything runs on the Tk main thread (created from ``App.run`` before
the main loop starts), and the whole thing degrades to a plain window if
Pillow is unavailable.

Use::

    splash = Splash(root)
    ...
    splash.finish(after_ms=1200)   # fade out shortly, then destroy
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

import branding

WIDTH = 460
HEIGHT = 260
CORNER = 24
TRANSPARENT = "#ff00ff"        # colorkey for rounded corners (unlikely in art)

_BG_TOP = (30, 30, 44)
_BG_BOTTOM = (12, 12, 20)
_ACCENT = (99, 102, 241)       # matches the web UI accent (#6366f1)
_ACCENT_2 = (165, 180, 252)
_TEXT = (232, 232, 240)
_MUTED = (138, 138, 156)
_DIM = (90, 90, 108)
_BORDER = (44, 44, 60)

FADE_IN_MS = 280
FADE_OUT_MS = 260


def _load_font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = (
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    )
    for path in candidates:
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _center_text(draw, y: int, text: str, font, fill, width: int = WIDTH) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    x = (width - (box[2] - box[0])) // 2 - box[0]
    draw.text((x, y), text, font=font, fill=fill)


def _build_card_image():
    """Render the rounded gradient card + title/version with Pillow."""
    from PIL import Image, ImageDraw

    card = Image.new("RGB", (WIDTH, HEIGHT), TRANSPARENT)
    d = ImageDraw.Draw(card)

    # Vertical gradient fill.
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = tuple(
            round(_BG_TOP[i] + (_BG_BOTTOM[i] - _BG_TOP[i]) * t) for i in range(3)
        )
        d.line([(0, y), (WIDTH, y)], fill=color)

    # Rounded mask -> transparent corners.
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, WIDTH - 1, HEIGHT - 1], radius=CORNER, fill=255
    )
    out = Image.new("RGB", (WIDTH, HEIGHT), TRANSPARENT)
    out.paste(card, (0, 0), mask)
    d = ImageDraw.Draw(out)

    # Border + a soft top accent sheen.
    d.rounded_rectangle(
        [0, 0, WIDTH - 1, HEIGHT - 1], radius=CORNER, outline=_BORDER, width=1
    )
    d.line([(CORNER, 1), (WIDTH - CORNER, 1)], fill=(60, 62, 96), width=1)

    # Brand mark: three little key caps (mirrors the tray icon).
    key_w, gap = 30, 8
    total = key_w * 3 + gap * 2
    x0 = (WIDTH - total) // 2
    y0 = 34
    for i, letter in enumerate("ABC"):
        x = x0 + i * (key_w + gap)
        d.rounded_rectangle(
            [x, y0, x + key_w, y0 + key_w],
            radius=7,
            fill=(20, 20, 30),
            outline=(70, 72, 110),
            width=1,
        )
        lf = _load_font(15, bold=True)
        box = d.textbbox((0, 0), letter, font=lf)
        d.text(
            (x + (key_w - (box[2] - box[0])) // 2 - box[0],
             y0 + (key_w - (box[3] - box[1])) // 2 - box[1] - 1),
            letter,
            font=lf,
            fill=_ACCENT_2 if i == 0 else _MUTED,
        )

    # Title, accent underline, version.
    title_font = _load_font(40, bold=True)
    _center_text(d, 74, "SoftMacro", title_font, _TEXT)
    u_w = 84
    d.rounded_rectangle(
        [(WIDTH - u_w) // 2, 128, (WIDTH + u_w) // 2, 132], radius=2, fill=_ACCENT
    )
    _center_text(d, 142, f"version {branding.APP_VERSION}", _load_font(13), _MUTED)

    return out


class Splash:
    """The splash window. Create on the Tk main thread."""

    def __init__(self, root: tk.Misc, *, min_ms: int = 1400) -> None:
        self.root = root
        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._photo = None
        self._bar = None
        self._status = None
        self._track = (0, 0)
        self._phase = 0.0
        self._closed = False
        self._fading_out = False
        self._tick_id = None
        self._fade_id = None

        self._build()

    # ------------------------------------------------------------- build

    def _build(self) -> None:
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=TRANSPARENT)
        try:
            win.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        win.attributes("-alpha", 0.0)

        self._canvas = tk.Canvas(
            win,
            width=WIDTH,
            height=HEIGHT,
            highlightthickness=0,
            bd=0,
            bg=TRANSPARENT,
        )
        self._canvas.pack()

        # Background art (Pillow); fall back to a flat card if it fails.
        try:
            from PIL import ImageTk

            self._photo = ImageTk.PhotoImage(_build_card_image(), master=win)
            self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        except Exception:
            self._canvas.configure(bg="#14141c")
            self._canvas.create_text(
                WIDTH // 2, 90, text="SoftMacro", fill="#e8e8f0",
                font=("Segoe UI", 30, "bold"),
            )
            self._canvas.create_text(
                WIDTH // 2, 126, text=f"version {branding.APP_VERSION}",
                fill="#8a8a9c", font=("Segoe UI", 11),
            )

        # Status line + indeterminate progress bar (drawn, so it can animate).
        self._status = self._canvas.create_text(
            WIDTH // 2, 182, text="Starting up…", fill="#8a8a9c",
            font=("Segoe UI", 11),
        )
        track_w = 300
        tx = (WIDTH - track_w) // 2
        self._canvas.create_rectangle(
            tx, 200, tx + track_w, 204, fill="#26263a", outline=""
        )
        self._bar = self._canvas.create_rectangle(
            tx, 200, tx + 90, 204, fill="#6366f1", outline=""
        )
        self._track = (tx, track_w)
        self._win = win

        # Center on screen.
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = (sw - WIDTH) // 2
        y = (sh - HEIGHT) // 2 - 40
        win.geometry(f"{WIDTH}x{HEIGHT}+{x}+{max(0, y)}")

    # ------------------------------------------------------------- public

    def set_status(self, text: str) -> None:
        if self._closed or self._canvas is None:
            return
        try:
            self._canvas.itemconfigure(self._status, text=text)
        except tk.TclError:
            pass

    def finish(self, *, after_ms: int = 0) -> None:
        """Fade out after a short delay, then destroy."""
        if self._closed or self._win is None:
            return
        self._fade_in()
        self._start_progress()
        try:
            self._fade_id = self._win.after(max(0, after_ms), self._fade_out)
        except tk.TclError:
            pass

    def close(self) -> None:
        """Force an immediate fade-out (e.g. the overlay opened early)."""
        self._fade_out()

    # ------------------------------------------------------------ motion

    def _fade_in(self) -> None:
        if self._win is None:
            return
        try:
            self._win.deiconify()
            self._win.lift()
        except tk.TclError:
            return
        self._fade(0.0, 0.98, FADE_IN_MS)

    def _fade_out(self) -> None:
        if self._closed or self._fading_out or self._win is None:
            return
        self._fading_out = True
        self._fade(0.98, 0.0, FADE_OUT_MS, then=self._destroy)

    def _fade(self, start: float, end: float, duration: int, then=None) -> None:
        win = self._win
        if win is None:
            return
        steps = max(1, duration // 16)
        i = 0

        def step() -> None:
            nonlocal i
            if self._closed or self._win is None:
                return
            i += 1
            t = min(1.0, i / steps)
            eased = 1 - (1 - t) ** 3
            try:
                win.attributes("-alpha", start + (end - start) * eased)
            except tk.TclError:
                return
            if t < 1.0:
                try:
                    win.after(16, step)
                except tk.TclError:
                    return
            elif then is not None:
                then()

        step()

    def _start_progress(self) -> None:
        self._tick()

    def _tick(self) -> None:
        if self._closed or self._canvas is None:
            return
        self._phase = (self._phase + 0.018) % 1.0
        tx, track_w = self._track
        bar_w = 96
        pos = -0.35 + self._phase * 1.7
        x1 = tx + pos * track_w
        try:
            self._canvas.coords(self._bar, x1, 200, x1 + bar_w, 204)
        except tk.TclError:
            return
        try:
            self._tick_id = self._win.after(16, self._tick)
        except tk.TclError:
            pass

    def _destroy(self) -> None:
        self._closed = True
        for attr in ("_tick_id", "_fade_id"):
            aid = getattr(self, attr)
            if aid is not None:
                try:
                    self.root.after_cancel(aid)
                except Exception:
                    pass
        try:
            if self._win is not None:
                self._win.destroy()
        except tk.TclError:
            pass
        self._win = None
        self._canvas = None
