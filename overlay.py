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

import tkinter as tk
from typing import Callable

from storage import FKEYS, NUMPAD, LETTERS, SLOT_KEYS, slot_label
from branding import APP_TITLE
import window_info

BG          = "#6a6a6a"   # window background
FG          = "#ffffff"
FG_MUTED    = "#c8c8c8"
FG_DIM      = "#a0a0a8"
ACCENT      = "#ffffff"
HOVER_BG    = "#7a7a7a"
ROW_PADDING = 18          # vertical spacing between rows
GROUP_INDENT_PX = 32     # indent for macro rows inside a group view


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
    ) -> None:
        self.on_play = on_play
        self.on_close = on_close
        self.border_px = int(border_px)
        self.font_size = int(font_size)
        self.alpha = float(alpha)

        # Navigation stack of open group ids; empty = top level. Groups can
        # nest, so this is the path Main -> group -> sub-group -> ...
        self.stack: list[str] = []

        self.slots: dict[str, str] = {}        # slot -> macro_id | group_id
        self.macros: dict[str, dict] = {}
        self.groups: list[dict] = []
        self.groups_by_id: dict[str, dict] = {}

        # Active test-countdown window state (see show_countdown).
        self._countdown: dict | None = None

        self.root = tk.Tk()
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

    def apply_settings(
        self,
        *,
        border_px: int | None = None,
        font_size: int | None = None,
        alpha: float | None = None,
    ) -> None:
        """Update overlay appearance. Geometry re-applies on next ``show()``."""
        if border_px is not None:
            self.border_px = int(border_px)
        if font_size is not None:
            self.font_size = int(font_size)
        if alpha is not None:
            self.alpha = float(alpha)
            self.win.attributes("-alpha", self.alpha)
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
        self.slots = dict(slots or {})
        self.macros = dict(macros or {})
        self.groups = list(groups or [])
        self.groups_by_id = {g["id"]: g for g in self.groups}

        # Always open at the top level.
        self.stack = []
        self.status_var.set("")

        self._refresh_title(app_name, app_exe)
        self._refresh_rows()

        # Spans the screen minus the configured border.
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        m = max(0, self.border_px)
        w = max(100, sw - 2 * m)
        h = max(100, sh - 2 * m)
        self.win.geometry(f"{w}x{h}+{m}+{m}")
        self.win.attributes("-alpha", self.alpha)

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
        try:
            self.win.withdraw()
        except tk.TclError:
            pass
        self.stack = []
        self.on_close()

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
            self.status_var.set(status)
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
                tk.Label(
                    row,
                    text=f"   ({count} item{'s' if count != 1 else ''})",
                    font=self._font(delta=-2),
                    fg=FG_DIM,
                    bg=BG,
                ).pack(side="left")
            elif target in self.macros:
                macro = self.macros[target]
                self._make_row(
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
            any_shown = True

        if not any_shown:
            self._render_empty("Nothing here yet.")

    def _on_entry_click(self, slot: str) -> None:
        target = self._current_slots().get(slot)
        if target in self.groups_by_id:
            self._open_group(target)
        elif target in self.macros:
            self.on_play(slot)
        else:
            self.status_var.set(f"{slot_label(slot)} is not assigned.")

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

        # Click anywhere on the row to play/open (unless disabled).
        if on_click is not None and not click_disabled:
            widgets = (row, letter_lbl, dash_lbl, name_lbl)
            for w in widgets:
                w.bind("<Button-1>", lambda _e, cb=on_click: cb())
                w.bind("<Enter>", lambda _e, ws=widgets: [x.configure(bg=HOVER_BG) for x in ws])
                w.bind("<Leave>", lambda _e, ws=widgets: [x.configure(bg=BG) for x in ws])
        return row

    def _render_empty(self, message: str) -> None:
        tk.Label(
            self.rows_frame,
            text=message,
            font=self._font(delta=0),
            fg=FG_DIM,
            bg=BG,
        ).pack(anchor="w", pady=ROW_PADDING)

    # -- navigation ----------------------------------------------------------

    def _open_group(self, group_id: str) -> None:
        # Refuse unknown groups and (defensive) any link that would loop.
        if group_id not in self.groups_by_id or group_id in self.stack:
            return
        self.stack.append(group_id)
        self.status_var.set("")
        self._refresh_title_only()
        self._refresh_rows()

    def _on_escape(self) -> None:
        if self.stack:
            self.stack.pop()
            self.status_var.set("")
            self._refresh_title_only()
            self._refresh_rows()
        else:
            self.hide()

    def handle_escape(self) -> None:
        """Esc while the overlay is open: back one level, or close.

        Called by the Tk ``<Escape>`` binding and by the global Esc hook
        (see ``hotkey.register_overlay_escape``) so it works even when the
        window did not receive keyboard focus. No-ops when already hidden,
        because on some systems both paths can fire for one keypress.
        """
        try:
            if not self.win.winfo_viewable():
                return
        except tk.TclError:
            return
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
