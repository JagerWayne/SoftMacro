# AGENTS.md

Windows-only Python desktop app (Python 3.10+, tkinter + Flask). Not a library:
it is launched as a process. Requires Windows; `ctypes`/Win32 calls are core.

## Run / verify

- `run.bat` bootstraps `venv\`, installs `requirements.txt`, then runs `python app.py`.
- Direct run: `.\venv\Scripts\python.exe app.py` (activate the venv first if using `python`).
- No test suite, no linter, no typecheck config, no CI. Verification is manual:
  start the app, open http://localhost:5000, and use the per-macro **Test** button
  (3-2-1 countdown) or the overlay hotkey (default `Ctrl+Z`).
- Build installer: `build_installer.bat` (PyInstaller + Inno Setup 6). App bundle in
  `dist\SoftMacro\`, installer in `dist\installer\SoftMacroSetup.exe`.

## Architecture (must-know)

- Tkinter runs on the main thread. Hotkey, web, and playback run on daemon threads and
  communicate only by posting tuples through `runtime.post()` (backed by a `queue.Queue`
  polled via `root.after`). **Never touch tkinter from a non-main thread.**
- Event kinds and their payloads are documented in `runtime.py`.
- Slots may target a macro id (`m_...`) or a nested group id (`g_...`); groups nest via a
  group id in another group's `slots`, with cycles rejected. Macros/groups/slots are
  independent, so a macro can back several keys.
- `window_info.py` captures the foreground HWND when the overlay opens; playback restores
  focus to it before replaying. Keep this contract when changing overlay/playback flow.

## Repo-specific conventions

- Bump the version in **two** places together: `VERSION` and `branding.APP_VERSION`.
  The updater compares `VERSION`; releases must tag that version and attach
  `SoftMacroSetup.exe`.
- Adding a Quick Add command: edit `COMMANDS` and `parse_command()` in `event_parser.py`
  (single source of truth), then regenerate the reference from the repo root:
  `python event_parser.py events.txt`. `templates/help.html` renders `COMMANDS` dynamically,
  so it needs no manual edit.
- Regenerate the icon with `python tools\make_icon.py` (writes `softmacro.ico`).
- Frozen builds: add platform libraries to `hiddenimports` in `SoftMacro.spec`.

## Constraints / gotchas

- User data lives in `%APPDATA%\SoftMacro\` (`apps\<exe>.json`, `config.json`). Updates and
  installs must never touch it.
- The web UI binds to `127.0.0.1` only by design; do not add network binding. Host/Origin/
  Referer checks and CSP headers in `web.py` are intentional security controls — preserve them.
- `config.SINGLE_INSTANCE_PORT` (47777) is reserved for the single-instance lock and is
  rejected as a web port.
- Under `pythonw.exe` (silent launch) stdout is redirected to
  `%APPDATA%\SoftMacro\softmacro.log`; diagnostics use `print`.
- The `keyboard` lib's `add_hotkey(..., suppress=True)` never fires for a single
  non-modifier key; use `keyboard.hook_key` for lone keys (see `_register_action`
  in `hotkey.py`). The overlay Esc watch in `register_overlay_escape` is
  deliberately **unsuppressed** so the focused overlay's own Tk `<Escape>` binding
  still receives the key; `Overlay.handle_escape` debounces the two paths.
