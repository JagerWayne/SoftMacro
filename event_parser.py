"""Quick-Add command language for the macro event editor.

The catalog ``COMMANDS`` below is the single source of truth for every
command the user can type in the *Quick Add* field on the New Macro page.

When you add a new command:

  1. Add an entry to ``COMMANDS`` (name, syntax, description, examples).
  2. Add a parsing branch to ``parse_command()`` that returns the matching
     events as ``[kind, payload]`` pairs (timestamps are assigned by the
     caller, not here).
  3. Regenerate ``events.txt`` from the project root:

         python event_parser.py events.txt

  4. Add a test case to the parser's smoke test.

The runnable main at the bottom of this file does step 3.
"""

from __future__ import annotations

import re
from typing import Any


# =============================================================================
# Command catalog -- the single source of truth
# =============================================================================

COMMANDS: list[dict[str, Any]] = [
    {
        "name": "key_combo",
        "syntax": "Ctrl+T",
        "description": "Press a key with optional modifiers.",
        "details": (
            "Modifiers come first, joined by '+', then the main key. "
            "Recognized modifiers: ctrl (control), shift, alt, win (meta/cmd). "
            "The main key can be a letter, digit, or a named special key."
        ),
        "examples": [
            "Ctrl+Z",
            "Ctrl+Shift+R",
            "Alt+F4",
            "Win+E",
            "Ctrl+Alt+Delete",
        ],
    },
    {
        "name": "single_key",
        "syntax": "Enter",
        "description": "Press a single key (no modifier).",
        "details": (
            "Common names recognized: enter, return, esc, escape, tab, space, "
            "backspace, delete, home, end, page up, page down, up, down, "
            "left, right, insert, pause, caps lock, num lock, scroll lock, "
            "print screen, menu, f1..f24. Single characters also work."
        ),
        "examples": [
            "Enter",
            "Escape",
            "Tab",
            "Space",
            "F5",
            "Page Down",
            "Up",
            "a",
            "5",
        ],
    },
    {
        "name": "type_text",
        "syntax": 'Type "hello"',
        "description": "Type a string of text, character by character.",
        "details": (
            "Wrap the text in double quotes. Each character becomes a "
            "key_down + key_up pair; capital letters additionally get "
            "explicit shift bracketing. Backslash escapes are not "
            "interpreted."
        ),
        "examples": [
            'Type "yes"',
            'Type "user@example.com"',
            'Type "1234"',
        ],
    },
    {
        "name": "wait",
        "syntax": "Wait 500",
        "description": "Pause for N milliseconds before the next event.",
        "details": (
            "Inserts a single 'delay' event whose payload is the number of "
            "milliseconds. The player sleeps through it during playback."
        ),
        "examples": [
            "Wait 100",
            "Wait 500",
            "Wait 2000",
        ],
    },
    {
        "name": "click",
        "syntax": "Click 500 300",
        "description": "Click the mouse at the given screen coordinates.",
        "details": (
            "If x y are omitted, clicks at the current cursor position. "
            "Button defaults to left; you can say 'right click' or "
            "'middle click' explicitly."
        ),
        "examples": [
            "Click",
            "Click 500 300",
            "Right click 200 400",
            "Middle click 640 480",
        ],
    },
    {
        "name": "move",
        "syntax": "Move 500 300",
        "description": "Move the mouse cursor without clicking.",
        "details": "Coordinates are absolute screen pixels.",
        "examples": [
            "Move 100 200",
            "Move 1920 1080",
        ],
    },
    {
        "name": "scroll",
        "syntax": "Scroll down",
        "description": "Scroll the mouse wheel.",
        "details": (
            "Direction: up, down, left, right. Optional count after the "
            "direction (default 1)."
        ),
        "examples": [
            "Scroll up",
            "Scroll down",
            "Scroll up 3",
        ],
    },
    {
        "name": "hold_release",
        "syntax": "Hold Shift",
        "description": (
            "Press a key down without releasing it (or release a previously "
            "held key)."
        ),
        "details": (
            "Pairs with another Hold/Release to bracket a modifier or key "
            "press across multiple commands."
        ),
        "examples": [
            "Hold shift",
            "Release shift",
            "Hold ctrl",
        ],
    },
]


# =============================================================================
# Key name normalization
# =============================================================================

_MODIFIER_ALIASES: dict[str, str] = {
    "ctrl":    "Key.ctrl_l",
    "control": "Key.ctrl_l",
    "shift":   "Key.shift",
    "alt":     "Key.alt_l",
    "win":     "Key.cmd",
    "meta":    "Key.cmd",
    "cmd":     "Key.cmd",
}

_SPECIAL_KEYS: dict[str, str] = {
    "enter":        "Key.enter",
    "return":       "Key.enter",
    "esc":          "Key.esc",
    "escape":       "Key.esc",
    "tab":          "Key.tab",
    "space":        "Key.space",
    "backspace":    "Key.backspace",
    "delete":       "Key.delete",
    "del":          "Key.delete",
    "home":         "Key.home",
    "end":          "Key.end",
    "page up":      "Key.page_up",
    "pageup":       "Key.page_up",
    "page down":    "Key.page_down",
    "pagedown":     "Key.page_down",
    "up":           "Key.up",
    "down":         "Key.down",
    "left":         "Key.left",
    "right":        "Key.right",
    "caps lock":    "Key.caps_lock",
    "capslock":     "Key.caps_lock",
    "num lock":     "Key.num_lock",
    "numlock":      "Key.num_lock",
    "scroll lock":  "Key.scroll_lock",
    "scrolllock":   "Key.scroll_lock",
    "pause":        "Key.pause",
    "break":        "Key.pause",
    "insert":       "Key.insert",
    "menu":         "Key.menu",
    "print screen": "Key.print_screen",
    "printscreen":  "Key.print_screen",
    "prtsc":        "Key.print_screen",
    "context menu": "Key.menu",
    # Numpad: store as "Numpad0".."Numpad9"; player maps to VK_NUMPADn.
    "numpad0": "Numpad0",
    "numpad1": "Numpad1",
    "numpad2": "Numpad2",
    "numpad3": "Numpad3",
    "numpad4": "Numpad4",
    "numpad5": "Numpad5",
    "numpad6": "Numpad6",
    "numpad7": "Numpad7",
    "numpad8": "Numpad8",
    "numpad9": "Numpad9",
    "kp0": "Numpad0",
    "kp1": "Numpad1",
    "kp2": "Numpad2",
    "kp3": "Numpad3",
    "kp4": "Numpad4",
    "kp5": "Numpad5",
    "kp6": "Numpad6",
    "kp7": "Numpad7",
    "kp8": "Numpad8",
    "kp9": "Numpad9",
}

_BUTTON_ALIASES: dict[str, str] = {
    "left":   "left",
    "right":  "right",
    "middle": "middle",
}

_MODIFIER_NAMES = set(_MODIFIER_ALIASES.keys())


def parse_key(name: str) -> str:
    """Translate a friendly key name to a pynput-compatible key string.

    Examples:
        'ctrl'      -> 'Key.ctrl_l'
        'Enter'     -> 'Key.enter'
        'Page Down' -> 'Key.page_down'
        'a'         -> 'a'
        'F5'        -> 'Key.f5'
    """
    if not name:
        return name
    n = name.strip().lower()
    if n in _MODIFIER_ALIASES:
        return _MODIFIER_ALIASES[n]
    if n in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[n]
    fm = re.fullmatch(r"f(\d+)", n)
    if fm and 1 <= int(fm.group(1)) <= 24:
        return f"Key.f{fm.group(1)}"
    # Already looks like a pynput Key.something -> pass through.
    if name.startswith("Key.") or name.startswith("KeyCode."):
        return name
    # Single character: literal.
    if len(name) == 1:
        return name
    return name  # last resort


# =============================================================================
# Command parser
# =============================================================================

def parse_command(cmd: str) -> tuple[list[list] | None, str | None]:
    """Parse a Quick Add command string into a list of ``[kind, payload]``.

    Returns ``(events, error)``. On success ``events`` is a list of
    ``[kind, payload]`` pairs (timestamps are assigned by the caller). On
    failure ``events`` is ``None`` and ``error`` explains why.
    """
    if cmd is None:
        return None, "Empty command."
    s = cmd.strip()
    if not s:
        return None, "Empty command."

    low = s.lower()

    # ---- Type "text" ----
    m = re.fullmatch(r'type\s+"((?:[^"\\]|\\.)*)"', s, re.IGNORECASE)
    if m:
        text = m.group(1)
        events: list[list] = []
        for ch in text:
            if ch == "\\":
                continue  # simple -- skip escapes
            if ch.isupper():
                # Capital letters get explicit shift bracketing so the
                # player can treat bare chars as physical keys.
                events.append(["key_down", "Key.shift"])
                events.append(["key_down", ch.lower()])
                events.append(["key_up", ch.lower()])
                events.append(["key_up", "Key.shift"])
            else:
                events.append(["key_down", ch])
                events.append(["key_up", ch])
        return events, None

    # ---- Wait N (ms) ----
    m = re.fullmatch(r"wait\s+(\d+)\s*(ms|milliseconds?|s|seconds?)?", s, re.IGNORECASE)
    if m:
        ms = int(m.group(1))
        unit = (m.group(2) or "ms").lower()
        if unit in ("s", "second", "seconds"):
            ms *= 1000
        return [["delay", ms]], None

    # ---- <button> click [x y] ----
    m = re.fullmatch(
        r"(left|right|middle)\s+click(?:\s+(-?\d+)\s+(-?\d+))?",
        s, re.IGNORECASE,
    )
    if m:
        button = m.group(1).lower()
        x, y = m.group(2), m.group(3)
        events = []
        if x is not None and y is not None:
            events.append(["mouse_move", [int(x), int(y)]])
        events.append(["mouse_down", button])
        events.append(["mouse_up", button])
        return events, None

    # ---- click [x y] (shorthand for left click) ----
    m = re.fullmatch(r"click(?:\s+(-?\d+)\s+(-?\d+))?", s, re.IGNORECASE)
    if m:
        x, y = m.group(1), m.group(2)
        events = []
        if x is not None and y is not None:
            events.append(["mouse_move", [int(x), int(y)]])
        events.append(["mouse_down", "left"])
        events.append(["mouse_up", "left"])
        return events, None

    # ---- Move x y ----
    m = re.fullmatch(r"move\s+(-?\d+)\s+(-?\d+)", s, re.IGNORECASE)
    if m:
        return [["mouse_move", [int(m.group(1)), int(m.group(2))]]], None

    # ---- Scroll <dir> [count] ----
    m = re.fullmatch(
        r"scroll\s+(up|down|left|right)(?:\s+(\d+))?",
        s, re.IGNORECASE,
    )
    if m:
        direction = m.group(1).lower()
        amount = int(m.group(2)) if m.group(2) else 1
        return [["scroll", {"direction": direction, "amount": amount}]], None

    # ---- Hold <key> / Release <key> ----
    m = re.fullmatch(r"hold\s+(.+)", s, re.IGNORECASE)
    if m:
        return [["key_down", parse_key(m.group(1).strip())]], None
    m = re.fullmatch(r"release\s+(.+)", s, re.IGNORECASE)
    if m:
        return [["key_up", parse_key(m.group(1).strip())]], None

    # ---- Key combo: Ctrl+Shift+T ----
    if "+" in s:
        # Reject leading/trailing '+' or empty segments.
        if s.startswith("+") or s.endswith("+"):
            return None, "Combo cannot start or end with '+'."
        parts = [p.strip() for p in s.split("+")]
        if any(not p for p in parts):
            return None, "Empty segment in combo."
        non_mods = [p for p in parts if p.lower() not in _MODIFIER_NAMES]
        if not non_mods:
            return None, "Combo has modifiers but no key."
        key = parse_key(non_mods[-1])
        has_shift = any(p.lower() == "shift" for p in parts)
        # Physical-key semantics: bare letter keys are lowercase; the
        # player never injects implicit shift. Uppercase only via an
        # explicit shift modifier in the combo.
        if len(key) == 1 and not has_shift:
            key = key.lower()
        mods = [parse_key(p) for p in parts if p.lower() in _MODIFIER_NAMES]
        events = []
        for mname in mods:
            events.append(["key_down", mname])
        events.append(["key_down", key])
        events.append(["key_up", key])
        for mname in reversed(mods):
            events.append(["key_up", mname])
        return events, None

    # ---- Bare single key ----
    key = parse_key(s)
    if len(key) == 1 and key.isupper():
        key = key.lower()
    return [["key_down", key], ["key_up", key]], None


# =============================================================================
# Help text generation
# =============================================================================

def generate_help_text() -> str:
    """Return the human-readable content for events.txt."""
    lines: list[str] = []
    lines.append("SoftMacro -- Event Quick-Add Commands")
    lines.append("=" * 38)
    lines.append("")
    lines.append(
        "These are the commands accepted by the Quick Add input on the\n"
        "'New macro' page. Type a command, press Enter (or click Add), and\n"
        "the parsed events are appended to the macro."
    )
    lines.append("")
    lines.append(
        "Each command expands to one or more events. The events table on the\n"
        "web page shows exactly what was generated, and you can edit or\n"
        "delete any of them before saving."
    )
    lines.append("")
    lines.append(
        "Available event kinds: key_down, key_up, mouse_down, mouse_up,\n"
        "mouse_move, scroll, delay."
    )
    lines.append("")
    lines.append("-" * 64)
    lines.append("")

    for i, c in enumerate(COMMANDS, 1):
        lines.append(f"{i}. {c['syntax']}")
        lines.append(f"   {c['description']}")
        if c.get("details"):
            for detail_line in c["details"].splitlines():
                lines.append(f"   {detail_line}")
        lines.append("   Examples:")
        for ex in c["examples"]:
            lines.append(f"     - {ex}")
        lines.append("")

    lines.append("-" * 64)
    lines.append("")
    lines.append("Notes:")
    lines.append("  - Commands are case-insensitive (Ctrl+T == ctrl+t == CTRL+T).")
    lines.append(
        "  - When you add events via Quick Add they are placed at\n"
        "    'current time + N ms', where N is the per-event delay you\n"
        "    set next to the Quick Add input (default 50 ms)."
    )
    lines.append(
        "  - The 'Type' command quotes its argument with double quotes.\n"
        "    Backslash escapes are not interpreted -- the literal text is\n"
        "    typed character by character."
    )
    lines.append("  - 'Wait' accepts s or ms; 'Wait 2' = 2000 ms.")
    lines.append("")
    lines.append("Adding a new command")
    lines.append("-------------------")
    lines.append("  1. Add an entry to the COMMANDS list in event_parser.py.")
    lines.append("  2. Add a parsing branch to parse_command().")
    lines.append(
        "  3. Regenerate this file by running, from the project root:\n"
        "         python event_parser.py events.txt"
    )
    lines.append("  4. Add a unit test for the new branch.")
    lines.append("")
    return "\n".join(lines)


def write_help_file(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(generate_help_text())


# =============================================================================
# CLI: regenerate events.txt
# =============================================================================

if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "events.txt"
    write_help_file(target)
    print(f"Wrote {target}")
