"""Flask app serving the SoftMacro management UI on http://127.0.0.1:5000.

The port is configurable (Settings -> Web UI); the server always binds to
the loopback interface and rejects non-loopback Host/Origin headers.

Data model (v2): each app file holds ``{exe, display_name, macros[], slots{}}``.
Macros and slot assignments are managed separately so a macro can exist
without being assigned and the same macro can back multiple letters.

Endpoints:

    GET  /                                    list every app
    GET  /app/<exe>                           overview (macros + slot grid)
    POST /app/<exe>/rename                    change display_name
    GET  /app/<exe>/macro/new                 create-macro form
    POST /app/<exe>/macro/new                 create
    GET  /app/<exe>/macro/<id>                edit-macro form
    POST /app/<exe>/macro/<id>                save edits
    POST /app/<exe>/macro/<id>/delete         delete (and unassign)
    POST /app/<exe>/slot                      assign/unassign letter -> macro
    GET  /settings                            hotkey settings
    POST /settings                            save hotkeys
    POST /parse                               expand a Quick-Add command
"""

from __future__ import annotations

import io
import json
import socket
import threading
from collections import deque
from urllib.parse import urlsplit

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.serving import make_server

import autostart
import backup
import branding
import config
import event_parser
import hotkey
import runtime
import storage
import updater
import window_info


LETTERS = storage.LETTERS
FKEYS = storage.FKEYS
NUMPAD = storage.NUMPAD

# Last update-check / install result, shown on the Settings page.
_update_state: dict = {}

# Last backup-restore result, shown on the Settings page.
_restore_state: dict = {}

# QWERTY layout for the slot grid -- mirrors overlay.py.
QWERTY_ROWS = [
    ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
    ["A", "S", "D", "F", "G", "H", "J", "K", "L"],
    ["Z", "X", "C", "V", "B", "N", "M"],
]

# Numpad layout rows for the assign keyboard (keypad arrangement).
NUMPAD_ROWS = [
    ["KP7", "KP8", "KP9"],
    ["KP4", "KP5", "KP6"],
    ["KP1", "KP2", "KP3"],
    ["KP0"],
]


# ---- helpers ---------------------------------------------------------------

def _normalize_combo(raw: str) -> tuple[str | None, str | None]:
    raw = (raw or "").strip().lower()
    if not raw:
        return None, "Hotkey cannot be empty."
    parts = [p.strip() for p in raw.split("+") if p.strip()]
    if not parts:
        return None, "Hotkey cannot be empty."
    if any(len(p) > 24 for p in parts):
        return None, "One of the keys looks too long."
    combo = "+".join(parts)
    error = hotkey.validate_combo(combo)
    if error:
        return None, error
    return combo, None


def _coerce_events(raw: str) -> tuple[list | None, str | None]:
    """Parse the events JSON the user pasted. Returns (events, error)."""
    raw = (raw or "").strip()
    if not raw:
        return None, "Events JSON is required."
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    if not isinstance(data, list):
        return None, "Events must be a JSON array."
    cleaned: list = []
    for i, entry in enumerate(data):
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            return None, f"Entry #{i} must be [ms, [kind, payload]]."
        ms, ev = entry
        try:
            ms_int = int(ms)
        except (TypeError, ValueError):
            return None, f"Entry #{i}: timestamp must be a number (got {ms!r})."
        if not isinstance(ev, (list, tuple)) or len(ev) != 2:
            return None, f"Entry #{i}: payload must be [kind, value]."
        kind, payload = ev[0], ev[1]
        if not isinstance(kind, str):
            return None, f"Entry #{i}: kind must be a string."
        cleaned.append([ms_int, [kind, payload]])
    return cleaned, None


def _macros_by_id(data: dict) -> dict[str, dict]:
    return {m["id"]: m for m in data.get("macros", [])}


def _slot_sort_key(slot: str) -> int:
    """Natural keyboard order (letters, F-keys, numpad) for stable lists."""
    try:
        return storage.SLOT_KEYS.index(slot)
    except ValueError:
        return len(storage.SLOT_KEYS)


def _resolve_keys(
    slots: dict, groups_by_id: dict[str, dict], macros_by_id: dict[str, dict]
) -> dict:
    """Build the keyboard layout for one directory with bindings resolved.

    Returns ``{"fkeys": [...], "qwerty": [[...], ...], "numpad": [[...]]}``
    where every key is a dict the template can render directly.
    """
    def resolve(slot: str) -> dict:
        target_id = slots.get(slot) or ""
        key = {
            "slot": slot,
            "label": storage.slot_label(slot),
            "target_id": target_id,
            "target_name": "",
            "kind": "free",
            "color": "",
        }
        if target_id in groups_by_id:
            group = groups_by_id[target_id]
            key.update(target_name=group["name"], kind="group", color=group["color"])
        elif target_id in macros_by_id:
            key.update(target_name=macros_by_id[target_id]["name"], kind="macro")
        elif target_id:
            key.update(target_name="Unknown target", kind="unknown")
        return key

    return {
        "fkeys": [resolve(f) for f in FKEYS],
        "qwerty": [[resolve(letter) for letter in row] for row in QWERTY_ROWS],
        "numpad": [[resolve(k) for k in row] for row in NUMPAD_ROWS],
    }


def _flatten_keys(keyboard: dict) -> list[dict]:
    keys = list(keyboard["fkeys"])
    for row in keyboard["qwerty"]:
        keys.extend(row)
    for row in keyboard["numpad"]:
        keys.extend(row)
    return keys


def _running_apps() -> list[dict]:
    """Visible apps with an ``added`` flag against the stored app files."""
    added = {a["exe"].lower() for a in storage.list_apps()}
    items = []
    for app in window_info.running_apps():
        entry = dict(app)
        entry["added"] = entry["exe"].lower() in added
        items.append(entry)
    return items


def _group_parents(data: dict) -> dict[str, list[str]]:
    """child group id -> ids of directories that can open it."""
    by_id = {g["id"]: g for g in data.get("groups", [])}
    parents: dict[str, list[str]] = {}

    def add(parent_id: str, target: str) -> None:
        if target in by_id:
            parents.setdefault(target, []).append(parent_id)

    for target in data.get("slots", {}).values():
        add("main", target)
    for g in data.get("groups", []):
        for target in g.get("slots", {}).values():
            add(g["id"], target)
    return parents


def _group_ancestors(data: dict, group_id: str) -> set[str]:
    """Groups that can (transitively) open ``group_id``."""
    parents = _group_parents(data)
    seen: set[str] = set()
    stack = [group_id]
    while stack:
        node = stack.pop()
        for parent in parents.get(node, []):
            if parent != "main" and parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def _group_path(data: dict, group_id: str) -> list[str]:
    """Shortest chain of group ids from the main slots down to ``group_id``.

    Returns ``[]`` for main, or ``[group_id]`` when the group isn't
    reachable from any key yet (newly created / unbound).
    """
    parents = _group_parents(data)  # child -> [parent ids]
    queue = deque([(group_id, [group_id])])
    seen = {group_id}
    while queue:
        node, path = queue.popleft()
        for parent in parents.get(node, []):
            if parent == "main":
                return path
            if parent in seen:
                continue
            seen.add(parent)
            queue.append((parent, [parent] + path))
    return [group_id]



def _parse_playback_opts(form) -> tuple[int, float]:
    """Extract and clamp the repeat/speed form fields."""
    try:
        repeat = int(form.get("repeat") or "1")
    except (TypeError, ValueError):
        repeat = 1
    repeat = max(1, min(999, repeat))

    try:
        speed = float(form.get("speed") or "1.0")
    except (TypeError, ValueError):
        speed = 1.0
    speed = max(0.1, min(10.0, speed))
    return repeat, speed


def _parse_overlay_form(form) -> dict:
    """Parse and clamp the overlay-appearance form fields."""
    try:
        border_px = int(form.get("overlay_border_px", "20"))
    except (TypeError, ValueError):
        border_px = 20
    if not (0 <= border_px <= 400):
        return {"config": {}, "error": "Border must be between 0 and 400 px."}
    try:
        font_size = int(form.get("overlay_font_size", "18"))
    except (TypeError, ValueError):
        font_size = 18
    if not (10 <= font_size <= 64):
        return {"config": {}, "error": "Font size must be between 10 and 64."}
    try:
        alpha = float(form.get("overlay_alpha", "0.75"))
    except (TypeError, ValueError):
        alpha = 0.75
    if not (0.1 <= alpha <= 1.0):
        return {"config": {}, "error": "Transparency must be between 0.1 and 1.0."}
    return {
        "config": {"border_px": border_px, "font_size": font_size, "alpha": alpha},
        "error": None,
    }


def _parse_web_port(form, current: int) -> tuple[int | None, str | None]:
    """Validate the requested web UI port. Returns (port, error)."""
    raw = (form.get("web_port") or "").strip()
    if not raw:
        return None, "Web UI port is required."
    if not raw.isdigit():
        return None, "Web UI port must be a number."
    port = int(raw)
    if not (config.WEB_PORT_MIN <= port <= config.WEB_PORT_MAX):
        return None, (
            f"Web UI port must be between {config.WEB_PORT_MIN} and "
            f"{config.WEB_PORT_MAX} (ports below 1024 need admin rights)."
        )
    if port == config.SINGLE_INSTANCE_PORT:
        return None, f"Port {port} is reserved by SoftMacro."
    # Check the port is actually free; skip when unchanged (our own server
    # is using it).
    if port != current:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                return None, f"Port {port} is already in use."
    return port, None


# ---- factory ---------------------------------------------------------------

def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.jinja_env.globals["app_title"] = branding.APP_TITLE
    # Cap uploads (backup restores); larger requests get a 413.
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

    # ============================================================ security
    # The UI can inject keystrokes, so it must only ever be reachable from
    # this machine's loopback interface and from same-origin pages.

    loopback_hosts = {"127.0.0.1", "localhost", "::1"}

    def host_name(value: str) -> str:
        """Hostname part of a Host/Origin/Referer value ('' when absent)."""
        value = (value or "").strip()
        if not value:
            return ""
        if value.startswith("["):                      # [::1]:5000
            return value[1:].split("]", 1)[0].lower()
        return value.split(":", 1)[0].lower()

    @app.before_request
    def _guard_request():
        # 1. Host header must be loopback. This blocks DNS-rebinding
        #    attacks, where evil.com resolves to 127.0.0.1.
        if host_name(request.host) not in loopback_hosts:
            abort(403)
        # 2. State-changing requests must be same-origin. This blocks
        #    CSRF from any website the user has open in another tab.
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            site = (request.headers.get("Sec-Fetch-Site") or "").strip().lower()
            if site in ("cross-site", "same-site"):
                abort(403)
            source = request.headers.get("Origin")
            if source is not None:
                source = source.strip()
                if source.lower() == "null":
                    # Some privacy setups strip the origin; only trust the
                    # browser's own same-origin declaration then.
                    if site != "same-origin":
                        abort(403)
                elif host_name(urlsplit(source).netloc) not in loopback_hosts:
                    abort(403)
            else:
                referer = request.headers.get("Referer")
                if referer and host_name(urlsplit(referer).netloc) not in loopback_hosts:
                    abort(403)

    @app.after_request
    def _secure_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'none'; object-src 'none'",
        )
        return resp

    # ============================================================== index

    @app.route("/")
    def index():
        return render_template("index.html", apps=storage.list_apps())

    # ========================================================== new app

    @app.route("/new-app", methods=["GET", "POST"])
    def new_app():
        error: str | None = None
        exe = ""
        display_name = ""
        if request.method == "POST":
            exe = (request.form.get("exe") or "").strip().lower()
            display_name = (request.form.get("display_name") or "").strip()
            if not exe:
                error = "Application .exe filename is required."
            elif "/" in exe or "\\" in exe or ":" in exe:
                error = "Just the filename, e.g. 'chrome.exe'."
            else:
                if not exe.endswith(".exe"):
                    exe = exe + ".exe"
                # Create the app file if it doesn't exist.
                data = storage.load_app(exe)
                if display_name:
                    data["display_name"] = display_name
                storage.save_app(data)
                return redirect(url_for("view_app", exe=exe))
        return render_template(
            "new_app.html",
            exe=exe,
            display_name=display_name,
            error=error,
            running=_running_apps(),
        )

    @app.route("/running-apps")
    def running_apps_list():
        """JSON list of visible apps for the New-app page's refresh button."""
        return jsonify({"apps": _running_apps()})

    # =========================================================== app view

    @app.route("/app/<exe>")
    def view_app(exe):
        data = storage.load_app(exe)
        macros_by_id = _macros_by_id(data)
        groups_by_id = {g["id"]: g for g in data.get("groups", [])}

        # Which directory's keyboard is on screen: "main" or a group id.
        dir_arg = (request.args.get("dir") or "main").strip()
        if dir_arg != "main" and dir_arg not in groups_by_id:
            dir_arg = "main"
        selected_group = groups_by_id.get(dir_arg)
        slots = (
            data.get("slots", {})
            if dir_arg == "main"
            else (selected_group or {}).get("slots", {})
        )

        keyboard = _resolve_keys(slots, groups_by_id, macros_by_id)
        bindings = [k for k in _flatten_keys(keyboard) if k["target_id"]]
        bindings.sort(key=lambda k: _slot_sort_key(k["slot"]))

        # Breadcrumb: Main › ... › current group (groups can nest).
        breadcrumbs = [{"id": "main", "name": "Main", "color": ""}]
        if selected_group:
            for gid in _group_path(data, dir_arg):
                group = groups_by_id.get(gid)
                if group:
                    breadcrumbs.append(
                        {"id": gid, "name": group["name"], "color": group["color"]}
                    )

        # Sub-groups opened from this directory's keys.
        subgroups = []
        for bound in bindings:
            if bound["kind"] != "group":
                continue
            group = groups_by_id.get(bound["target_id"])
            if group:
                subgroups.append(
                    {
                        "id": group["id"],
                        "name": group["name"],
                        "color": group["color"],
                        "label": bound["label"],
                        "count": len(group.get("slots", {})),
                    }
                )

        action = (
            url_for("assign_slot", exe=exe)
            if dir_arg == "main"
            else url_for("assign_group_slot", exe=exe, group_id=dir_arg)
        )

        # Where every macro is bound, for the cards in the left column.
        macro_bindings: dict[str, list[dict]] = {}

        def add_binding(mid, dir_id, dir_name, color, slot):
            if mid in macros_by_id:
                macro_bindings.setdefault(mid, []).append(
                    {
                        "dir_id": dir_id,
                        "dir_name": dir_name,
                        "color": color,
                        "slot": slot,
                        "label": storage.slot_label(slot),
                    }
                )

        for slot, mid in data.get("slots", {}).items():
            add_binding(mid, "main", "Main", "", slot)
        for g in data.get("groups", []):
            for slot, mid in g.get("slots", {}).items():
                add_binding(mid, g["id"], g["name"], g["color"], slot)
        for bound in macro_bindings.values():
            bound.sort(key=lambda b: _slot_sort_key(b["slot"]))

        # Targets offered by the assign popover for the visible directory.
        # Inside a group, exclude itself and its ancestors: assigning an
        # ancestor would create a cycle. Descendants are fine (a shortcut).
        blocked: set[str] = set()
        if selected_group:
            blocked = _group_ancestors(data, dir_arg) | {dir_arg}
        targets = []
        targets.extend(
            {"id": g["id"], "name": g["name"], "kind": "group", "color": g["color"]}
            for g in data.get("groups", [])
            if g["id"] not in blocked
        )
        targets.extend(
            {"id": m["id"], "name": m["name"], "kind": "macro", "color": ""}
            for m in data.get("macros", [])
        )

        bound_total = len(data.get("slots", {})) + sum(
            len(g.get("slots", {})) for g in data.get("groups", [])
        )

        return render_template(
            "app.html",
            app=data,
            selected_dir=dir_arg,
            selected_group=selected_group,
            breadcrumbs=breadcrumbs,
            subgroups=subgroups,
            keyboard=keyboard,
            bindings=bindings,
            action=action,
            macro_bindings=macro_bindings,
            targets_json=json.dumps(
                {"targets": targets, "dir": dir_arg}, ensure_ascii=False
            ).replace("<", "\\u003c"),
            bound_total=bound_total,
            error=request.args.get("error") or None,
        )

    @app.route("/app/<exe>/rename", methods=["POST"])
    def rename_app(exe):
        display_name = (request.form.get("display_name") or "").strip()
        new_exe = (request.form.get("exe") or "").strip()
        final_exe, error = storage.rename_app(exe, new_exe, display_name)
        if error:
            return redirect(url_for("view_app", exe=exe, error=error))
        return redirect(url_for("view_app", exe=final_exe))

    @app.route("/app/<exe>/delete", methods=["POST"])
    def delete_app(exe):
        storage.delete_app(exe)
        return redirect(url_for("index"))

    # ========================================================== new macro

    @app.route("/app/<exe>/macro/new", methods=["GET", "POST"])
    def new_macro(exe):
        data = storage.load_app(exe)
        error: str | None = None
        name = ""
        events_json = ""
        repeat = 1
        speed = 1.0

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            events_json = request.form.get("events") or ""
            repeat, speed = _parse_playback_opts(request.form)
            if not name:
                error = "Macro name is required."
            else:
                events, err = _coerce_events(events_json)
                if err is not None:
                    error = err
                else:
                    storage.add_macro(
                        exe, name, events, repeat=repeat, speed=speed
                    )
                    return redirect(url_for("view_app", exe=exe))

        return render_template(
            "macro_form.html",
            exe=exe,
            app=data,
            letters=LETTERS,
            qwerty_rows=QWERTY_ROWS,
            mode="new",
            form_title="New macro",
            form_action=url_for("new_macro", exe=exe),
            macro_id="",
            name=name,
            events_json=events_json,
            repeat=repeat,
            speed=speed,
            error=error,
        )

    # ========================================================= edit macro

    @app.route("/app/<exe>/macro/<macro_id>", methods=["GET", "POST"])
    def edit_macro(exe, macro_id):
        data = storage.load_app(exe)
        macro = storage.get_macro(exe, macro_id)
        if macro is None:
            return render_template("404.html"), 404

        error: str | None = None
        name = macro.get("name", "")
        events_json = json.dumps(macro.get("events", []))
        repeat = int(macro.get("repeat", 1) or 1)
        speed = float(macro.get("speed", 1.0) or 1.0)

        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            events_json = request.form.get("events") or ""
            repeat, speed = _parse_playback_opts(request.form)
            if not name:
                error = "Macro name is required."
            else:
                events, err = _coerce_events(events_json)
                if err is not None:
                    error = err
                else:
                    storage.update_macro(
                        exe, macro_id,
                        name=name, events=events, repeat=repeat, speed=speed,
                    )
                    return redirect(url_for("view_app", exe=exe))

        return render_template(
            "macro_form.html",
            exe=exe,
            app=data,
            letters=LETTERS,
            qwerty_rows=QWERTY_ROWS,
            mode="edit",
            form_title=f"Edit macro: {macro.get('name', '')}",
            form_action=url_for("edit_macro", exe=exe, macro_id=macro_id),
            macro_id=macro_id,
            name=name,
            events_json=events_json,
            repeat=repeat,
            speed=speed,
            error=error,
        )

    # ======================================================= delete macro

    @app.route("/app/<exe>/macro/<macro_id>/delete", methods=["POST"])
    def delete_macro(exe, macro_id):
        storage.remove_macro(exe, macro_id)
        return redirect(url_for("view_app", exe=exe))

    # ====================================================== test macro

    @app.route("/app/<exe>/macro/<macro_id>/test", methods=["POST"])
    def test_macro(exe, macro_id):
        posted = runtime.post(("test_macro", {"exe": exe, "macro_id": macro_id}))
        if not posted:
            print("[SoftMacro] test: no app event sink installed")
        return redirect(url_for("view_app", exe=exe))

    # ======================================================= group slots

    @app.route("/app/<exe>/group/new", methods=["POST"])
    def new_group(exe):
        name = (request.form.get("name") or "").strip() or "Group"
        color = request.form.get("color") or "#88c0ff"
        parent = (request.form.get("parent") or "main").strip() or "main"

        data = storage.load_app(exe)
        known = {g["id"] for g in data.get("groups", [])}
        if parent != "main" and parent not in known:
            parent = "main"

        group = storage.add_group(exe, name, color)

        # Bind the new group to the first free key of its parent directory so
        # it's immediately reachable from the overlay and the breadcrumb.
        data = storage.load_app(exe)
        slots = (
            data.get("slots", {})
            if parent == "main"
            else (storage.get_group(exe, parent) or {}).get("slots", {})
        )
        free = next((s for s in storage.SLOT_KEYS if s not in slots), None)
        if free:
            storage.assign_slot(
                exe,
                free,
                group["id"],
                group_id=None if parent == "main" else parent,
            )
        # Land on the new group's keyboard, ready for binding.
        return redirect(url_for("view_app", exe=exe, dir=group["id"]))

    @app.route("/app/<exe>/group/<group_id>/rename", methods=["POST"])
    def rename_group(exe, group_id):
        storage.update_group(
            exe,
            group_id,
            name=request.form.get("name"),
            color=request.form.get("color"),
        )
        return redirect(url_for("view_app", exe=exe, dir=group_id))

    @app.route("/app/<exe>/group/<group_id>/delete", methods=["POST"])
    def delete_group(exe, group_id):
        storage.remove_group(exe, group_id)
        return redirect(url_for("view_app", exe=exe))

    @app.route("/app/<exe>/group/<group_id>/slot", methods=["POST"])
    def assign_group_slot(exe, group_id):
        letter = (request.form.get("letter") or "").strip().upper()
        macro_id = (request.form.get("macro_id") or "").strip()
        if "::" in macro_id:
            macro_id, letter = macro_id.split("::", 1)
            macro_id = macro_id.strip()
            letter = letter.strip().upper()
        if storage.is_valid_slot(letter):
            current = (storage.get_group(exe, group_id) or {}).get("slots", {}).get(letter)
            if macro_id and current == macro_id:
                storage.assign_slot(exe, letter, None, group_id=group_id)
            else:
                storage.assign_slot(exe, letter, macro_id or None, group_id=group_id)
        return redirect(url_for("view_app", exe=exe, dir=group_id))

    # ==================================================== slot assignment

    @app.route("/app/<exe>/slot", methods=["POST"])
    def assign_slot(exe):
        letter = (request.form.get("letter") or "").strip().upper()
        macro_id = (request.form.get("macro_id") or "").strip()
        dir_param = (request.form.get("dir") or "main").strip() or "main"

        # The old macro-card dropdown posted "<macro_id>::<letter>"; still
        # accept it (the current UI posts letter and macro_id separately).
        if "::" in macro_id:
            macro_id, letter = macro_id.split("::", 1)
            macro_id = macro_id.strip()
            letter = letter.strip().upper()

        if storage.is_valid_slot(letter):
            current = storage.load_app(exe).get("slots", {}).get(letter)
            if macro_id and current == macro_id:
                # Clicking an already-assigned key toggles it off.
                storage.assign_slot(exe, letter, None)
            else:
                storage.assign_slot(exe, letter, macro_id or None)
        return redirect(url_for("view_app", exe=exe, dir=dir_param))

    # ============================================================= settings

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        cfg = config.load_config()
        saved = False
        error: str | None = None
        port_changed: int | None = None

        if request.method == "POST":
            raw = {
                name: request.form.get(name, "")
                for name in ("show_overlay", "stop_playback")
            }
            normalized: dict[str, str] = {}
            for name, value in raw.items():
                combo, err = _normalize_combo(value)
                if err:
                    error = f"{name}: {err}"
                    break
                normalized[name] = combo
            else:
                combos = list(normalized.values())
                if len(set(combos)) != len(combos):
                    error = "Hotkeys must all be different."
                else:
                    overlay = _parse_overlay_form(request.form)
                    current_port = config.get_web_port()
                    web_port, web_err = _parse_web_port(request.form, current_port)
                    if web_err:
                        error = web_err
                    elif overlay.get("error"):
                        error = overlay["error"]
                    else:
                        cfg["hotkeys"].update(normalized)
                        cfg["overlay"] = overlay["config"]
                        cfg["web"] = {"port": web_port}
                        config.save_config(cfg)
                        applied = config.reload_hotkeys()
                        # Push live overlay setting change to the App.
                        runtime.post(("apply_overlay_settings", overlay["config"]))
                        if web_port != current_port:
                            restart_in_thread(web_port)
                            port_changed = web_port
                        if applied:
                            saved = True
                        else:
                            error = "Saved to disk, but no hotkey listener is running yet."

        return render_template(
            "settings.html",
            config=cfg,
            saved=saved,
            error=error,
            port_changed=port_changed,
            web_port=config.get_web_port(),
            update=_update_state,
            restore=_restore_state,
            app_version=branding.APP_VERSION,
            autostart_enabled=autostart.is_enabled(),
        )

    # ========================================================= autostart

    @app.route("/settings/autostart", methods=["POST"])
    def toggle_autostart():
        if request.form.get("autostart") == "on":
            autostart.enable()
        else:
            autostart.disable()
        return redirect(url_for("settings"))

    # =========================================================== updates

    @app.route("/settings/update/check", methods=["POST"])
    def check_updates():
        global _update_state
        _update_state = updater.check_for_update()
        return redirect(url_for("settings") + "#updates")

    @app.route("/settings/update/install", methods=["POST"])
    def install_update_route():
        global _update_state
        result = updater.install_update()
        if result.get("ok"):
            _update_state = {
                "status": "installing" if result.get("installer") else "installed",
                "current": branding.APP_VERSION,
                "latest": result.get("version", ""),
                "files": len(result.get("files", [])),
            }
        else:
            _update_state = {
                "status": "error",
                "current": branding.APP_VERSION,
                "error": result.get("error", "Install failed."),
            }
        return redirect(url_for("settings") + "#updates")

    @app.route("/settings/restart-app", methods=["POST"])
    def restart_app():
        runtime.post(("restart_app", None))
        return render_template("restarting.html")

    # ==================================================== backup / restore

    @app.route("/settings/backup")
    def download_backup():
        blob = backup.create_backup()
        return send_file(
            io.BytesIO(blob),
            mimetype="application/zip",
            as_attachment=True,
            download_name=backup.backup_filename(),
        )

    @app.route("/settings/restore", methods=["POST"])
    def restore_backup_route():
        global _restore_state
        upload = request.files.get("backup")
        if upload is None or not upload.filename:
            _restore_state = {
                "status": "error",
                "error": "Choose a backup .zip file first.",
            }
            return redirect(url_for("settings") + "#backup")

        old_port = config.get_web_port()
        result = backup.restore_backup(upload.read())
        if not result.get("ok"):
            _restore_state = {
                "status": "error",
                "error": result.get("error", "Restore failed."),
            }
            return redirect(url_for("settings") + "#backup")

        # Apply the restored settings to the running app.
        config.reload_hotkeys()
        runtime.post(("apply_overlay_settings", config.get_overlay_config()))
        new_port = config.get_web_port()
        port_changed = new_port != old_port
        if port_changed:
            restart_in_thread(new_port)
        _restore_state = {
            "status": "ok",
            "apps": result.get("apps", 0),
            "config": result.get("config", False),
            "port_changed": port_changed,
            "new_port": new_port,
        }
        return redirect(url_for("settings") + "#backup")

    # ============================================================== parse

    @app.route("/parse", methods=["POST"])
    def parse_command():
        """Endpoint used by the Quick Add UI to expand a command."""
        if request.is_json:
            cmd = (request.json or {}).get("cmd", "")
        else:
            cmd = request.form.get("cmd", "")
        events, err = event_parser.parse_command(cmd)
        if err is not None:
            return jsonify({"error": err})
        return jsonify({"events": events or []})

    # ============================================================== help

    @app.route("/help")
    def help_page():
        cfg = config.load_config()
        return render_template(
            "help.html",
            commands=event_parser.COMMANDS,
            app_version=branding.APP_VERSION,
            hotkeys=cfg.get("hotkeys", {}),
            web_port=config.get_web_port(),
        )

    # ============================================================== 404

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("404.html"), 404

    return app


# A module-level app instance so Flask's ``flask run`` and debug tooling work.
flask_app = create_app()


# ---- server lifecycle ------------------------------------------------------

_server = None
_server_thread: threading.Thread | None = None
_current_port: int | None = None
_server_lock = threading.Lock()


def _start_server(port: int) -> None:
    """Bind 127.0.0.1:<port> and serve in a daemon thread."""
    global _server, _server_thread, _current_port
    server = make_server("127.0.0.1", port, flask_app, threaded=True)
    with _server_lock:
        _server = server
        _current_port = port
    _server_thread = threading.Thread(
        target=server.serve_forever, name="softmacro-web", daemon=True
    )
    _server_thread.start()
    print(f"[SoftMacro] Web UI ready: http://127.0.0.1:{port}")


def start_in_thread() -> threading.Thread:
    """Start the web UI on the configured port."""
    _start_server(config.get_web_port())
    return _server_thread


def current_port() -> int:
    """Port the web server is serving on right now."""
    return _current_port if _current_port is not None else config.get_web_port()


def restart_in_thread(port: int | None = None, delay: float = 1.0) -> None:
    """Restart the web server (on ``port``, default: configured port).

    Safe to call from a request handler or the tray thread: the current
    response has ``delay`` seconds to reach the browser before the old
    server shuts down.
    """
    target = config.get_web_port() if port is None else port

    def run() -> None:
        global _server
        with _server_lock:
            old = _server
        if old is not None:
            try:
                old.shutdown()
            except Exception:
                pass
            try:
                old.server_close()
            except Exception:
                pass
        try:
            _start_server(target)
        except OSError as e:
            print(f"[SoftMacro] Could not restart web UI on port {target}: {e}")

    threading.Timer(delay, run).start()


def run_server(host: str = "127.0.0.1", port: int | None = None) -> None:
    flask_app.run(
        host=host,
        port=config.get_web_port() if port is None else port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    run_server()
