"""JSON-per-application storage for SoftMacro.

Schema (v2)::

    {
        "exe":          "chrome.exe",            # primary key (lowercase filename)
        "display_name": "Chrome",               # friendly name for the UI
        "macros": [                              # ordered list of macros
            {
                "id":     "m_a1b2c3d4",          # stable, generated on creation
                "name":   "New tab",
                "events": [[0, ["key_down", "Key.ctrl_l"]], ...]
            },
            ...
        ],
        "slots": {                               # letter -> macro_id
            "Q": "m_a1b2c3d4",
            "C": "m_..."
        }
    }

A macro can exist without any slot pointing at it (``unassigned``).
A single macro can be referenced by multiple slots. Deleting a macro
auto-clears any slots that referenced it.

The old v1 schema (``slots: {letter: {name, events}}``) is auto-migrated
on first load.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any


# ---- canonical slot keys ----------------------------------------------------

LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
FKEYS = [f"F{i}" for i in range(1, 13)]
NUMPAD = [f"KP{i}" for i in range(10)]

# Display labels for non-letter slots (used by the web UI and the overlay).
SLOT_LABELS: dict[str, str] = {f"KP{i}": f"Num{i}" for i in range(10)}

SLOT_KEYS = LETTERS + FKEYS + NUMPAD


def is_valid_slot(key: str) -> bool:
    return key in SLOT_KEYS


def slot_label(key: str) -> str:
    return SLOT_LABELS.get(key, key)


# ---- paths -----------------------------------------------------------------

def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".softmacro")
    path = Path(base) / "SoftMacro" / "apps"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _app_file(exe: str) -> Path:
    return data_dir() / f"{exe.lower()}.json"


def humanize(exe: str) -> str:
    name = exe.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return " ".join(
        w.capitalize() for w in name.replace("_", " ").replace("-", " ").split()
    )


# ---- ID generation ---------------------------------------------------------

def new_macro_id() -> str:
    return "m_" + secrets.token_hex(4)


def new_group_id() -> str:
    return "g_" + secrets.token_hex(4)


_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate_color(color: str | None) -> str:
    """Accept a #rrggbb color, falling back to the accent blue."""
    color = (color or "").strip()
    if _COLOR_RE.match(color):
        return color.lower()
    return "#88c0ff"


# ---- v1 -> v2 migration ----------------------------------------------------

def _migrate_v1_to_v2(data: dict) -> dict:
    """If ``data`` is in the v1 layout, convert it to v2 in-place and return.

    v1:  ``slots: {letter: {name, events}}``
    v2:  ``macros: [...]`` + ``slots: {letter: macro_id}``
    """
    if "macros" in data:
        return data  # already v2
    macros: list[dict] = []
    slots: dict[str, str] = {}
    for letter, macro in (data.get("slots") or {}).items():
        if not isinstance(macro, dict):
            continue
        mid = new_macro_id()
        macros.append(
            {
                "id": mid,
                "name": macro.get("name") or letter,
                "events": macro.get("events") or [],
            }
        )
        slots[letter] = mid
    data["macros"] = macros
    data["slots"] = slots
    return data


# ---- v2 -> v3 defaults ------------------------------------------------------

def _apply_v3_defaults(data: dict) -> dict:
    """Fill in v3/v4 fields (playback options, usage stats, groups)."""
    data.setdefault("title_patterns", [])
    data.setdefault("groups", [])
    for m in data.get("macros", []):
        m.setdefault("repeat", 1)
        m.setdefault("speed", 1.0)
        m.setdefault("plays", 0)
        m.setdefault("last_played", None)
    return data


# ---- load / save -----------------------------------------------------------

def load_app(exe: str) -> dict[str, Any]:
    """Load the file for ``exe``; return a blank app if missing.

    Always returns the v2 shape, even for v1 files (they are migrated in
    memory but the original file is only rewritten when ``save_app`` is
    called -- which happens after any mutating action through this module).
    """
    path = _app_file(exe)
    if not path.exists():
        return {
            "exe": exe.lower(),
            "display_name": humanize(exe),
            "title_patterns": [],
            "groups": [],
            "macros": [],
            "slots": {},
        }
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # IMPORTANT: migrate first, then apply defaults. If we defaulted first
    # the migration would see ``"macros" in data`` (as an empty list) and
    # think the file is already v2.
    data = _migrate_v1_to_v2(data)
    data = _apply_v3_defaults(data)
    data["exe"] = exe.lower()
    data.setdefault("display_name", humanize(exe))
    data.setdefault("slots", {})
    # ``macros`` is guaranteed to exist after migration.
    return data


def save_app(data: dict[str, Any]) -> None:
    path = _app_file(data["exe"])
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def list_apps() -> list[dict[str, Any]]:
    apps: list[dict[str, Any]] = []
    for f in sorted(data_dir().glob("*.json")):
        try:
            with f.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
            data = _migrate_v1_to_v2(data)
            apps.append(
                {
                    "exe": data.get("exe", f.stem),
                    "display_name": data.get("display_name", f.stem),
                    "macro_count": len(data.get("macros", [])),
                    "slot_count": len(data.get("slots", {})),
                }
            )
        except Exception:
            continue
    return apps


# ---- macro CRUD ------------------------------------------------------------

def add_macro(
    exe: str,
    name: str,
    events: list,
    *,
    repeat: int = 1,
    speed: float = 1.0,
) -> dict:
    """Create a new macro and persist. Returns the created macro (with id)."""
    data = load_app(exe)
    macro = {
        "id": new_macro_id(),
        "name": (name or "").strip(),
        "events": events or [],
        "repeat": repeat,
        "speed": speed,
        "plays": 0,
        "last_played": None,
    }
    data["macros"].append(macro)
    save_app(data)
    return macro


def get_macro(exe: str, macro_id: str) -> dict | None:
    data = load_app(exe)
    for m in data["macros"]:
        if m["id"] == macro_id:
            return m
    return None


def update_macro(
    exe: str,
    macro_id: str,
    *,
    name: str | None = None,
    events: list | None = None,
    repeat: int | None = None,
    speed: float | None = None,
) -> bool:
    data = load_app(exe)
    for m in data["macros"]:
        if m["id"] == macro_id:
            if name is not None:
                m["name"] = name.strip()
            if events is not None:
                m["events"] = events
            if repeat is not None:
                m["repeat"] = repeat
            if speed is not None:
                m["speed"] = speed
            save_app(data)
            return True
    return False


def touch_macro(exe: str, macro_id: str) -> bool:
    """Increment the play counter and stamp the last-played time."""
    data = load_app(exe)
    for m in data["macros"]:
        if m["id"] == macro_id:
            m["plays"] = int(m.get("plays", 0)) + 1
            m["last_played"] = time.time()
            save_app(data)
            return True
    return False


def remove_macro(exe: str, macro_id: str) -> bool:
    """Delete a macro and unassign any slots pointing to it (main + groups)."""
    data = load_app(exe)
    before = len(data["macros"])
    data["macros"] = [m for m in data["macros"] if m["id"] != macro_id]
    # Drop main slot assignments pointing at the removed macro.
    for letter, mid in list(data["slots"].items()):
        if mid == macro_id:
            del data["slots"][letter]
    # Drop group slot assignments too.
    for g in data.get("groups", []):
        for letter, mid in list(g.get("slots", {}).items()):
            if mid == macro_id:
                del g["slots"][letter]
    if len(data["macros"]) < before:
        save_app(data)
        return True
    return False


# ---- groups -----------------------------------------------------------------

def add_group(exe: str, name: str, color: str = "#88c0ff") -> dict:
    """Create a new macro group (submenu). Returns the created group."""
    data = load_app(exe)
    group = {
        "id": new_group_id(),
        "name": (name or "Group").strip(),
        "color": validate_color(color),
        "slots": {},
    }
    data["groups"].append(group)
    save_app(data)
    return group


def get_group(exe: str, group_id: str) -> dict | None:
    data = load_app(exe)
    for g in data.get("groups", []):
        if g["id"] == group_id:
            return g
    return None


def update_group(
    exe: str,
    group_id: str,
    *,
    name: str | None = None,
    color: str | None = None,
) -> bool:
    data = load_app(exe)
    for g in data.get("groups", []):
        if g["id"] == group_id:
            if name is not None:
                g["name"] = (name or "").strip() or g["name"]
            if color is not None:
                g["color"] = validate_color(color)
            save_app(data)
            return True
    return False


def remove_group(exe: str, group_id: str) -> bool:
    """Delete a group and clear every key that pointed at it (main + nested)."""
    data = load_app(exe)
    before = len(data.get("groups", []))
    data["groups"] = [g for g in data.get("groups", []) if g["id"] != group_id]
    for letter, target in list(data["slots"].items()):
        if target == group_id:
            del data["slots"][letter]
    # Nested references: a group may be opened from other groups' keys.
    for g in data.get("groups", []):
        for letter, target in list(g.get("slots", {}).items()):
            if target == group_id:
                del g["slots"][letter]
    if len(data["groups"]) < before:
        save_app(data)
        return True
    return False


# ---- slot assignments ------------------------------------------------------

def _slots_dict(data: dict, group_id: str | None) -> dict | None:
    """Resolve the slots dict for ``group_id`` (None = main slots)."""
    if not group_id:
        return data.get("slots")
    for g in data.get("groups", []):
        if g["id"] == group_id:
            return g.setdefault("slots", {})
    return None


def groups_by_id(data: dict) -> dict[str, dict]:
    return {g["id"]: g for g in data.get("groups", [])}


def group_descendants(data: dict, group_id: str) -> set[str]:
    """All group ids reachable from ``group_id`` (excluding itself)."""
    by_id = groups_by_id(data)
    seen: set[str] = set()
    stack = [group_id]
    while stack:
        gid = stack.pop()
        for target in by_id.get(gid, {}).get("slots", {}).values():
            if target in by_id and target not in seen:
                seen.add(target)
                stack.append(target)
    return seen


def can_nest_group(data: dict, parent_id: str, child_id: str) -> bool:
    """True when ``child_id`` may be placed inside ``parent_id``.

    Rejects self-nesting and any link that would create a cycle (i.e. the
    parent being reachable from the child).
    """
    if parent_id == child_id:
        return False
    return parent_id not in group_descendants(data, child_id)


def assign_slot(
    exe: str,
    letter: str,
    target_id: str | None,
    group_id: str | None = None,
) -> bool:
    """Assign ``letter`` to a macro or a group.

    ``group_id=None`` targets the main slots. Inside a group the target may
    be a macro *or* another group (nested groups), as long as it doesn't
    create a cycle. Pass ``None`` or empty to unassign.
    """
    if not isinstance(letter, str):
        return False
    letter = letter.upper()
    if not is_valid_slot(letter):
        return False
    data = load_app(exe)
    slots = _slots_dict(data, group_id)
    if slots is None:
        return False
    if target_id in (None, ""):
        slots.pop(letter, None)
        save_app(data)
        return True

    by_id = groups_by_id(data)
    is_macro = any(m["id"] == target_id for m in data["macros"])
    is_group = target_id in by_id
    if not (is_macro or is_group):
        return False
    if is_group and group_id and not can_nest_group(data, group_id, target_id):
        return False

    slots[letter] = target_id
    save_app(data)
    return True


def set_display_name(exe: str, display_name: str) -> None:
    data = load_app(exe)
    name = (display_name or "").strip()
    data["display_name"] = name or humanize(exe)
    save_app(data)


def rename_app(
    old_exe: str, new_exe: str, display_name: str | None = None
) -> tuple[str | None, str | None]:
    """Change the .exe filename an application is stored under.

    Renames the JSON file, updates its ``exe`` field and (optionally) the
    display name. Returns ``(final_exe, error)``; ``final_exe`` is ``None``
    when the rename was refused (invalid name or target already exists).
    """
    old_exe = (old_exe or "").strip().lower()
    new_exe = (new_exe or "").strip().lower()
    if not new_exe:
        return None, "Application .exe filename is required."
    if "/" in new_exe or "\\" in new_exe or ":" in new_exe:
        return None, "Just the filename, e.g. 'chrome.exe'."
    if not new_exe.endswith(".exe"):
        new_exe += ".exe"

    if display_name is not None:
        display_name = display_name.strip()

    if new_exe == old_exe:
        data = load_app(old_exe)
        if display_name is not None:
            data["display_name"] = display_name or humanize(old_exe)
        save_app(data)
        return new_exe, None

    if _app_file(new_exe).exists():
        return None, f"An application for '{new_exe}' already exists."

    data = load_app(old_exe)
    data["exe"] = new_exe
    if display_name is not None:
        data["display_name"] = display_name or humanize(new_exe)
    save_app(data)
    try:
        _app_file(old_exe).unlink()
    except OSError:
        pass
    return new_exe, None


def delete_app(exe: str) -> bool:
    """Delete an application and everything stored for it.

    The whole JSON file goes, so all macros, groups and key assignments for
    that executable are removed too.
    """
    try:
        _app_file(exe).unlink()
        return True
    except OSError:
        return False
