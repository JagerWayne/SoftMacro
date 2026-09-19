"""Tkinter floating window -- the on-screen macro keyboard.

Playback-only UI. Every directory (the main slots or any group) shows its
own entries: macros play, groups open. Groups can nest, so navigation is a
stack:

    Chrome (chrome.exe)
    ─────────────────────
    A  Group Name 1
    B  Group Name 2

Pressing a key bound to a group opens it:

    Chrome (chrome.exe)  ·  Group Name 1
    ─────────────────────
            A  Macro 1
            B  Sub-group
            C  Macro 2

Pressing a macro key plays it (overlay hides, focus goes back to the
previous app, macro runs there). Pressing a sub-group key descends another
level. Esc goes back one level; Esc at the top closes the overlay.

If the app has NO groups, the same rendering shows the flat macro list.
The window is frameless (``overrideredirect``) and spans the screen minus
a configurable border.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from typing import Callable

from anim import Animator, ease_out_cubic, lerp, lerp_color
from storage import FKEYS, NUMPAD, LETTERS, SLOT_KEYS, slot_label
from branding import APP_TITLE
import window_info

BG          = "#6a6a6a"   # window background
FG          = "#ffffff"
FG_MUTED    = "#c8c8c8"
FG_DIM      = "#a0a0a8"
ACCENT      = "#ffffff"
HOVER_BG    = "#7a7a7a"
PRESS_BG    = "#8f8f8f"   # brief flash when a key is activated
ROW_PADDING = 18          # vertical spacing between rows
GROUP_INDENT_PX = 32     # indent for macro rows inside a group view

# Motion timings (milliseconds before the speed multiplier is applied).
OPEN_MS      = 170        # overlay fade/zoom in
CLOSE_MS     = 130        # overlay fade/zoom out
ROW_MS       = 150        # a single row fading in
ROW_STAGGER  = 28         # delay between consecutive rows
HOVER_MS     = 110        # background tween on hover
PRESS_MS     = 170        # key-press flash
STATUS_MS    = 220        # status/toast fade-in


class Overlay:
    """Owns the hidden ``Tk`` root and a visible ``Toplevel`` window."""

    def __init__(
        self,
        on_play: Callable[[str], None],
        on_close: Callable[[], None],
        *,
        border_px: int = 20,
        font_size: int = 18,
        alpha: float = 0.75,
        animations: bool = True,
        animation_speed: float = 1.0,
        reduce_motion: bool = False,
    ) -> None:
        self.on_play = on_play
        self.on_close = on_close
        self.border_px = int(border_px)
        self.font_size = int(font_size)
        self.alpha = float(alpha)
        self._animations_enabled = bool(animations)
        self._animation_speed = float(animation_speed) or 1.0
        self._reduce_motion = bool(reduce_motion)

        # Navigation stack of open group ids; empty = top level. Groups can
        # nest, so this is the path Main -> group -> sub-group -> ...
        self.stack: list[str] = []

        self.slots: dict[str, str] = {}        # slot -> macro_id | group_id
        self.macros: dict[str, dict] = {}
        self.groups: list[dict] = []
        self.groups_by_id: dict[str, dict] = {}

        # Rows currently on screen: slot -> row frame (for press feedback).
        self._rows_by_slot: dict[str, tk.Frame] = {}

        # Active test-countdown window state (see show_countdown).
        self._countdown: dict | None = None

        # Debounce for Esc: the Tk binding and the global Esc hook can both
        # fire for one keypress. A few tens of ms apart is still one press.
        self._last_escape_at = 0.0

        self.root = tk.Tk()
        self.animator = Animator(self.root)
        self.root.withdraw()
        self.root.title(APP_TITLE)
        self.root.protocol("WM_DELETE_WINDOW", self._close_root)

        self.win = tk.Toplevel(self.root)
        self.win.title(APP_TITLE)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", self.alpha)
        self.win.overrideredirect(True)
        self.win.configure(bg=BG)
        self.win.bind("<Escape>", lambda _e: self.handle_escape())
        self.win.withdraw()

        # Keyboard bindings for every supported slot key (only fire while
        # the overlay has focus).
        for letter in LETTERS:
            self.win.bind(f"<KeyPress-{letter.lower()}>", self._make_key_handler(letter))
            self.win.bind(f"<KeyPress-{letter}>", self._make_key_handler(letter))
        for fkey in FKEYS:
            self.win.bind(f"<KeyPress-{fkey}>", self._make_key_handler(fkey))
        for n in range(10):
            self.win.bind(
                f"<KeyPress-KP_{n}>", self._make_key_handler(f"KP{n}")
            )

        self._build_ui()

    # ---------------------------------------------------------------- ui

    def _font(self, delta: int = 0, bold: bool = False) -> tuple:
        size = max(self.font_size + delta, 10)
        return ("Segoe UI", size, "bold" if bold else "normal")

    def _build_ui(self) -> None:
        # Title (app name) and subtitle (group context when inside one).
        self.title_label = tk.Label(
            self.win,
            text=APP_TITLE,
            font=self._font(delta=12, bold=True),
            fg=ACCENT,
            bg=BG,
            anchor="w",
        )
        self.title_label.pack(fill="x", padx=24, pady=(22, 2))

        self.subtitle_label = tk.Label(
            self.win,
            text="",
            font=self._font(delta=2),
            fg=FG_MUTED,
            bg=BG,
            anchor="w",
        )
        self.subtitle_label.pack(fill="x", padx=24, pady=(0, 4))

        # Rows area -- one row per visible entry.
        self.rows_frame = tk.Frame(self.win, bg=BG)
        self.rows_frame.pack(fill="both", expand=True, padx=24, pady=(8, 14))

        # Status / hint line.
        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(
            self.win,
            textvariable=self.status_var,
            font=self._font(delta=-4),
            fg=FG_MUTED,
            bg=BG,
            anchor="w",
        )
        self.status_label.pack(fill="x", padx=24, pady=(0, 20))

    # ------------------------------------------------------ appearance

    # ------------------------------------------------------------ motion

    @property
    def _motion(self) -> bool:
        """True when animations should run (master switch + reduce-motion)."""
        return self._animations_enabled and not self._reduce_motion

    def _scaled(self, ms: float) -> float:
        """Apply the user's speed multiplier (higher = snappier)."""
        return max(1.0, float(ms) / self._animation_speed)

    def _set_status(self, text: str, *, animate: bool = True) -> None:
        """Set the status/toast line, fading it in when motion is enabled."""
        self.status_var.set(text)
        if not text or not animate or not self._motion:
            self.animator.cancel("status")
            try:
                self.status_label.configure(fg=FG_MUTED)
            except tk.TclError:
                pass
            return
        try:
            self.status_label.configure(fg=BG)
        except tk.TclError:
            return
        self.animator.run(
            self._scaled(STATUS_MS),
            lambda e: self.status_label.configure(
                fg=lerp_color(BG, FG_MUTED, e)
            ),
            key="status",
        )

    def apply_settings(
        self,
        *,
        border_px: int | None = None,
        font_size: int | None = None,
        alpha: float | None = None,
        animations: bool | None = None,
        animation_speed: float | None = None,
        reduce_motion: bool | None = None,
    ) -> None:
        """Update overlay appearance. Geometry re-applies on next ``show()``."""
        if border_px is not None:
            self.border_px = int(border_px)
        if font_size is not None:
            self.font_size = int(font_size)
        if animations is not None:
            self._animations_enabled = bool(animations)
        if animation_speed is not None:
            self._animation_speed = float(animation_speed) or 1.0
        if reduce_motion is not None:
            self._reduce_motion = bool(reduce_motion)
        if alpha is not None:
            self.alpha = float(alpha)
            if not self._motion:
                try:
                    self.win.attributes("-alpha", self.alpha)
                except tk.TclError:
                    pass
        # A settings change drops any running motion; snap to a settled state.
        if not self._motion:
            self.animator.cancel_all()
            try:
                if self.win.winfo_viewable():
                    self._set_geometry(*self._screen_rect())
                    self.win.attributes("-alpha", self.alpha)
            except tk.TclError:
                pass
        # Live-update fonts on the always-visible widgets.
        try:
            self.title_label.configure(font=self._font(delta=12, bold=True))
            self.subtitle_label.configure(font=self._font(delta=2))
            self.status_label.configure(font=self._font(delta=-4))
        except tk.TclError:
            pass
        # Re-render rows so they pick up the new font sizes.
        try:
            self._refresh_rows()
        except tk.TclError:
            pass

    # ------------------------------------------------------- countdown

    def show_countdown(
        self,
        seconds: int,
        on_done: Callable[[], None],
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        """Small top-most countdown that does not steal focus.

        Used by the web UI's Test button so the user can switch to the
        target application while it ticks down. Esc (or a click on the
        window) cancels.
        """
        self.hide_countdown()

        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=BG)

        label = tk.Label(
            win, text="", font=self._font(delta=10, bold=True), fg=ACCENT, bg=BG
        )
        label.pack(padx=56, pady=(26, 4))
        hint = tk.Label(
            win, text="Esc to cancel", font=self._font(delta=-4), fg=FG_MUTED, bg=BG
        )
        hint.pack(pady=(0, 18))

        win.update_idletasks()
        width = max(win.winfo_reqwidth(), 200)
        height = win.winfo_reqheight()
        x = (win.winfo_screenwidth() - width) // 2
        y = int(win.winfo_screenheight() * 0.16)
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.deiconify()
        win.lift()

        state = {
            "win": win,
            "after": None,
            "remaining": max(1, int(seconds)),
        }
        self._countdown = state

        def tick() -> None:
            if self._countdown is not state:
                return
            if state["remaining"] > 0:
                label.configure(text=str(state["remaining"]))
                state["remaining"] -= 1
                state["after"] = self.root.after(1000, tick)
            else:
                label.configure(text="Go")
                self._countdown = None
                self.root.after(200, self._destroy_countdown_win, win)
                on_done()

        def cancel(_event=None) -> None:
            if self._countdown is not state:
                return
            self.hide_countdown()
            if on_cancel:
                on_cancel()

        win.bind("<Escape>", cancel)
        win.bind("<Button-1>", cancel)
        tick()

    def hide_countdown(self) -> None:
        state = self._countdown
        if state is None:
            return
        self._countdown = None
        if state["after"] is not None:
            try:
                self.root.after_cancel(state["after"])
            except tk.TclError:
                pass
        self._destroy_countdown_win(state["win"])

    @staticmethod
    def _destroy_countdown_win(win) -> None:
        try:
            win.destroy()
        except tk.TclError:
            pass

    # ------------------------------------------------------- public state

    @property
    def current_group_id(self) -> str | None:
        """Group id when the overlay is showing a group's entries, else None."""
        return self.stack[-1] if self.stack else None

    def show(
        self,
        app_name: str,
        app_exe: str,
        slots: dict[str, str],
        macros: dict[str, dict] | None = None,
        groups: list[dict] | None = None,
    ) -> None:
        # Cancel anything mid-flight (e.g. a close fade) before re-opening.
        self.animator.cancel_all()

        self.slots = dict(slots or {})
        self.macros = dict(macros or {})
        self.groups = list(groups or [])
        self.groups_by_id = {g["id"]: g for g in self.groups}

        # Always open at the top level.
        self.stack = []
        self._set_status("")

        self._refresh_title(app_name, app_exe)

        fx, fy, fw, fh = self._screen_rect()
        if self._motion:
            # Start slightly inset and transparent, then ease to the target.
            ix, iy, iw, ih = self._inset_rect(fx, fy, fw, fh)
            self.win.attributes("-alpha", 0.0)
            self._set_geometry(ix, iy, iw, ih)
        else:
            self.win.attributes("-alpha", self.alpha)
            self._set_geometry(fx, fy, fw, fh)

        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        # The very first deiconify() maps the window asynchronously, so the
        # immediate focus_force() can be dropped. Re-assert once the window
        # is actually viewable (and again shortly after, in case Windows'
        # foreground lock needed a moment to clear).
        self._grab_focus()
        self.win.after(30, self._grab_focus)
        self.win.after(150, self._grab_focus)

        if self._motion:
            self._animate_open(fx, fy, fw, fh)
        # Build rows now that the window is (becoming) visible so the reveal
        # animation is actually seen.
        self._refresh_rows()

    # -- geometry helpers ---------------------------------------------------

    def _screen_rect(self) -> tuple[int, int, int, int]:
        """Target rectangle ``(x, y, w, h)``: screen minus the border."""
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        m = max(0, self.border_px)
        w = max(100, sw - 2 * m)
        h = max(100, sh - 2 * m)
        return m, m, w, h

    @staticmethod
    def _inset_rect(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        """A slightly smaller rectangle, for the open/close zoom."""
        inset = max(6, min(28, int(min(w, h) * 0.025)))
        return x + inset, y + inset, max(100, w - 2 * inset), max(100, h - 2 * inset)

    def _set_geometry(self, x: int, y: int, w: int, h: int) -> None:
        try:
            self.win.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        except tk.TclError:
            pass

    def _animate_open(self, fx: int, fy: int, fw: int, fh: int) -> None:
        ix, iy, iw, ih = self._inset_rect(fx, fy, fw, fh)
        target = self.alpha

        def frame(e: float) -> None:
            self._set_geometry(
                round(lerp(ix, fx, e)),
                round(lerp(iy, fy, e)),
                round(lerp(iw, fw, e)),
                round(lerp(ih, fh, e)),
            )
            self.win.attributes("-alpha", lerp(0.0, target, e))

        def done() -> None:
            self._set_geometry(fx, fy, fw, fh)
            self.win.attributes("-alpha", target)

        self.animator.run(
            self._scaled(OPEN_MS), frame, on_done=done, key="window", fps=60
        )

    def _grab_focus(self) -> None:
        """Bring the overlay to the foreground and give it keyboard focus.

        Uses the Win32 path (with the Alt-tap fallback in window_info) so a
        background process can take focus, then Tk's own focus_force().
        No-op when the window has been hidden in the meantime.
        """
        try:
            if not self.win.winfo_exists() or not self.win.winfo_viewable():
                return
            hwnd = self.win.winfo_id()
        except tk.TclError:
            return
        if hwnd:
            window_info.set_foreground(hwnd)
        try:
            self.win.focus_force()
        except tk.TclError:
            pass

    def hide(self) -> None:
        # Mark closed / release the global Esc watch immediately; the fade-out
        # below is purely cosmetic.
        self.stack = []
        self.on_close()

        try:
            viewable = bool(self.win.winfo_viewable())
        except tk.TclError:
            viewable = False

        if self._motion and viewable:
            self._animate_close()
        else:
            self._finish_close()

    def _animate_close(self) -> None:
        self.animator.cancel("window")
        try:
            self.win.update_idletasks()
            cx = self.win.winfo_x()
            cy = self.win.winfo_y()
            cw = self.win.winfo_width()
            ch = self.win.winfo_height()
            start_alpha = float(self.win.attributes("-alpha"))
        except tk.TclError:
            self._finish_close()
            return
        tx, ty, tw, th = self._inset_rect(cx, cy, cw, ch)

        def frame(e: float) -> None:
            self._set_geometry(
                round(lerp(cx, tx, e)),
                round(lerp(cy, ty, e)),
                round(lerp(cw, tw, e)),
                round(lerp(ch, th, e)),
            )
            self.win.attributes("-alpha", lerp(start_alpha, 0.0, e))

        self.animator.run(
            self._scaled(CLOSE_MS),
            frame,
            on_done=self._finish_close,
            key="window",
            fps=60,
        )

    def _finish_close(self) -> None:
        try:
            self.win.withdraw()
        except tk.TclError:
            pass

    def update_state(
        self,
        *,
        slots: dict[str, str] | None = None,
        macros: dict[str, dict] | None = None,
        groups: list[dict] | None = None,
        status: str | None = None,
    ) -> None:
        if slots is not None:
            self.slots = slots
        if macros is not None:
            self.macros = macros
        if groups is not None:
            self.groups = groups
            self.groups_by_id = {g["id"]: g for g in self.groups}
        # Drop any open groups that no longer exist.
        self.stack = [gid for gid in self.stack if gid in self.groups_by_id]
        if status is not None:
            self._set_status(status)
        self._refresh_title_only()
        self._refresh_rows()

    # ---------------------------------------------------------- internals

    def _refresh_title(self, app_name: str | None = None, app_exe: str | None = None) -> None:
        if app_name is not None:
            self._app_name = app_name
        if app_exe is not None:
            self._app_exe = app_exe
        # Refresh everything we have.
        self._refresh_title_only()

    def _refresh_title_only(self) -> None:
        name = getattr(self, "_app_name", APP_TITLE)
        if self.stack:
            current = self.groups_by_id.get(self.stack[-1], {})
            trail = " › ".join(
                self.groups_by_id.get(gid, {}).get("name", "?")
                for gid in self.stack
            )
            self.title_label.configure(
                text=f"{name}",
                fg=ACCENT,
                font=self._font(delta=12, bold=True),
            )
            self.subtitle_label.configure(
                text=f"  ·  {trail}",
                fg=current.get("color", FG_MUTED),
                font=self._font(delta=2),
            )
        else:
            self.title_label.configure(
                text=name if name else APP_TITLE,
                fg=ACCENT,
                font=self._font(delta=12, bold=True),
            )
            if self.groups:
                self.subtitle_label.configure(
                    text="Press a letter to open a group",
                    fg=FG_MUTED,
                    font=self._font(delta=0),
                )
            else:
                self.subtitle_label.configure(text="", fg=FG_MUTED)

    def _refresh_rows(self) -> None:
        for child in self.rows_frame.winfo_children():
            child.destroy()
        self._rows_by_slot = {}
        self._render_dir_rows()

    # -- entries (macros and sub-groups) of the current directory ----------

    def _current_slots(self) -> dict[str, str]:
        if self.stack:
            return self.groups_by_id.get(self.stack[-1], {}).get("slots", {})
        return self.slots

    def _render_dir_rows(self) -> None:
        slots = self._current_slots()
        indent = GROUP_INDENT_PX if self.stack else 0
        order = {key: i for i, key in enumerate(SLOT_KEYS)}

        rows: list[tk.Frame] = []
        any_shown = False
        for slot in sorted(slots.keys(), key=lambda s: order.get(s, len(order))):
            target = slots[slot]
            if target in self.groups_by_id:
                group = self.groups_by_id[target]
                row = self._make_row(
                    label=slot_label(slot),
                    name=group.get("name", "Group"),
                    color=group.get("color"),
                    bold=True,
                    on_click=lambda s=slot: self._on_entry_click(s),
                    click_disabled=False,
                    indent=indent,
                )
                count = len(group.get("slots", {}))
                count_lbl = tk.Label(
                    row,
                    text=f"   ({count} item{'s' if count != 1 else ''})",
                    font=self._font(delta=-2),
                    fg=FG_DIM,
                    bg=BG,
                )
                count_lbl.pack(side="left")
                self._register_row_widget(row, count_lbl, fg=FG_DIM)
            elif target in self.macros:
                macro = self.macros[target]
                row = self._make_row(
                    label=slot_label(slot),
                    name=macro.get("name", "(unnamed)"),
                    color=None,
                    bold=False,
                    on_click=lambda s=slot: self._on_entry_click(s),
                    click_disabled=False,
                    indent=indent,
                )
            else:
                continue
            self._rows_by_slot[slot] = row
            rows.append(row)
            any_shown = True

        if not any_shown:
            self._render_empty("Nothing here yet.")
            return
        self._reveal_rows(rows)

    def _on_entry_click(self, slot: str) -> None:
        # Immediate press feedback survives the navigation/play that follows.
        self._pulse_row(self._rows_by_slot.get(slot))
        target = self._current_slots().get(slot)
        if target in self.groups_by_id:
            self._open_group(target)
        elif target in self.macros:
            self.on_play(slot)
        else:
            self._set_status(f"{slot_label(slot)} is not assigned.")

    # -- row motion (reveal, hover, press) ----------------------------------

    def _register_row_widget(self, row: tk.Frame, widget, *, fg: str) -> None:
        row._sm_fade.append((widget, fg))
        row._sm_bg_widgets.append(widget)

    def _row_widgets(self, row: tk.Frame) -> list:
        return getattr(row, "_sm_bg_widgets", [row])

    def _reveal_rows(self, rows: list[tk.Frame]) -> None:
        if not rows or not self._motion:
            return
        duration = self._scaled(ROW_MS)
        stagger = self._scaled(ROW_STAGGER)
        for i, row in enumerate(rows):
            self._prepare_row_hidden(row)
            self.animator.after(
                int(i * stagger),
                lambda r=row: self._animate_row_in(r, duration),
                key=("reveal", id(row)),
            )

    def _prepare_row_hidden(self, row: tk.Frame) -> None:
        for widget, _final in getattr(row, "_sm_fade", []):
            try:
                widget.configure(fg=BG)
            except tk.TclError:
                pass
        base = getattr(row, "_sm_base_pady", ROW_PADDING // 2)
        try:
            row.pack_configure(pady=(base + 8, base))
        except tk.TclError:
            pass

    def _animate_row_in(self, row: tk.Frame, duration: float) -> None:
        entries = getattr(row, "_sm_fade", [])
        base = getattr(row, "_sm_base_pady", ROW_PADDING // 2)

        def frame(e: float) -> None:
            for widget, final in entries:
                try:
                    widget.configure(fg=lerp_color(BG, final, e))
                except tk.TclError:
                    pass
            try:
                row.pack_configure(pady=(round(lerp(base + 8, base, e)), base))
            except tk.TclError:
                pass

        self.animator.run(duration, frame, key=("row", id(row)), easing=ease_out_cubic)

    def _on_row_enter(self, row: tk.Frame) -> None:
        if getattr(row, "_sm_bg_target", BG) == HOVER_BG:
            return
        row._sm_bg_target = HOVER_BG
        self._tween_row_bg(row, HOVER_BG)

    def _on_row_leave(self, row: tk.Frame) -> None:
        if getattr(row, "_sm_bg_target", BG) == BG:
            return
        row._sm_bg_target = BG
        self._tween_row_bg(row, BG)

    def _tween_row_bg(self, row: tk.Frame, target: str) -> None:
        widgets = self._row_widgets(row)
        starts: list[str] = []
        for w in widgets:
            try:
                starts.append(w.cget("bg"))
            except tk.TclError:
                starts.append(BG)
        duration = self._scaled(HOVER_MS)

        def frame(e: float) -> None:
            for w, c0 in zip(widgets, starts):
                try:
                    w.configure(bg=lerp_color(c0, target, e))
                except tk.TclError:
                    pass

        self.animator.run(duration, frame, key=("bg", id(row)))

    def _pulse_row(self, row: tk.Frame | None) -> None:
        if row is None or not self._motion:
            return
        base = getattr(row, "_sm_bg_target", BG)
        widgets = self._row_widgets(row)
        # Flash immediately so it is visible even if the overlay hides next.
        self.animator.cancel(("bg", id(row)))
        for w in widgets:
            try:
                w.configure(bg=PRESS_BG)
            except tk.TclError:
                pass

        def frame(e: float) -> None:
            for w in widgets:
                try:
                    w.configure(bg=lerp_color(PRESS_BG, base, e))
                except tk.TclError:
                    pass

        self.animator.run(self._scaled(PRESS_MS), frame, key=("bg", id(row)))

    # -- shared row builder --------------------------------------------------

    def _make_row(
        self,
        *,
        label: str,
        name: str,
        color: str | None,
        bold: bool,
        on_click: Callable[[], None] | None,
        click_disabled: bool,
        indent: int = 0,
    ) -> tk.Frame:
        row = tk.Frame(
            self.rows_frame,
            bg=BG,
            cursor=("hand2" if not click_disabled else "arrow"),
        )
        row.pack(fill="x", pady=ROW_PADDING // 2, padx=(indent, 0))
        row._sm_base_pady = ROW_PADDING // 2
        row._sm_bg_target = BG

        label_color = color if color else ACCENT
        letter_lbl = tk.Label(
            row,
            text=label,
            font=self._font(delta=4, bold=bold),
            fg=label_color,
            bg=BG,
        )
        letter_lbl.pack(side="left")

        dash_lbl = tk.Label(
            row,
            text="  —  ",
            font=self._font(delta=0),
            fg=FG_DIM,
            bg=BG,
        )
        dash_lbl.pack(side="left")

        name_lbl = tk.Label(
            row,
            text=name,
            font=self._font(delta=2, bold=bold),
            fg=FG if bold else FG,
            bg=BG,
        )
        name_lbl.pack(side="left")

        row._sm_bg_widgets = [row, letter_lbl, dash_lbl, name_lbl]
        row._sm_fade = [
            (letter_lbl, label_color),
            (dash_lbl, FG_DIM),
            (name_lbl, FG),
        ]

        # Click anywhere on the row to play/open (unless disabled).
        if on_click is not None and not click_disabled:
            widgets = (row, letter_lbl, dash_lbl, name_lbl)
            for w in widgets:
                w.bind("<Button-1>", lambda _e, cb=on_click: cb())
                w.bind("<Enter>", lambda _e, r=row: self._on_row_enter(r))
                w.bind("<Leave>", lambda _e, r=row: self._on_row_leave(r))
        return row

    def _render_empty(self, message: str) -> None:
        lbl = tk.Label(
            self.rows_frame,
            text=message,
            font=self._font(delta=0),
            fg=FG_DIM,
            bg=BG,
        )
        lbl.pack(anchor="w", pady=ROW_PADDING)
        if self._motion:
            lbl.configure(fg=BG)
            self.animator.run(
                self._scaled(ROW_MS),
                lambda e: lbl.configure(fg=lerp_color(BG, FG_DIM, e)),
                key=("empty", id(lbl)),
            )

    # -- navigation ----------------------------------------------------------

    def _open_group(self, group_id: str) -> None:
        # Refuse unknown groups and (defensive) any link that would loop.
        if group_id not in self.groups_by_id or group_id in self.stack:
            return
        self.stack.append(group_id)
        self._set_status("")
        self._refresh_title_only()
        self._refresh_rows()

    def _on_escape(self) -> None:
        if self.stack:
            self.stack.pop()
            self._set_status("")
            self._refresh_title_only()
            self._refresh_rows()
        else:
            self.hide()

    def handle_escape(self) -> None:
        """Esc while the overlay is open: back one level, or close.

        Called by the Tk ``<Escape>`` binding and by the global Esc hook
        (see ``hotkey.register_overlay_escape``) so it works even when the
        window did not receive keyboard focus. No-ops when already hidden,
        and debounces the two paths so one keypress steps back only once.
        """
        try:
            if not self.win.winfo_viewable():
                return
        except tk.TclError:
            return
        now = time.monotonic()
        if now - self._last_escape_at < 0.12:
            return
        self._last_escape_at = now
        self._on_escape()

    def _make_key_handler(self, slot: str):
        def handler(_event):
            self._on_entry_click(slot)
        return handler

    def _close_root(self) -> None:
        self.hide()
        self.root.after(50, self.root.destroy)

    # ------------------------------------------------------- mainloop glue

    def mainloop(self) -> None:
        self.root.mainloop()

    def after(self, ms: int, func) -> None:
        self.root.after(ms, func)
