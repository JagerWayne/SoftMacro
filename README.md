# SoftMacro

A context-aware soft macro system for Windows. Press a hotkey in any
application and an on-screen macro keyboard pops up with the macros assigned
for that app. Click a letter to play the macro — focus jumps back to the app
first, so the macro lands where you expect. Create and manage macros through
a local web UI at <http://localhost:5000>.

```
+--------------------------+
|  SOFTMACRO               |
|  Shortcuts:              |
|                          |
|  Q = New Tab             |
|  S = Save                |
+--------------------------+
```

The overlay only lists assigned letters. Press the letter on your keyboard
(or click the row): the overlay hides, focus returns to the app you were in,
and the macro plays there.

## Features

- **Context-aware**: macros are stored per foreground executable
  (`chrome.exe`, `photoshop.exe`, ...). Switch apps, get a different set.
- **Playback-only overlay**: the hotkey opens a compact, frameless list of
  assigned shortcuts (`Q = New Tab`). Pressing a letter (or clicking its row)
  hides the overlay, restores focus to the original app, then replays the
  macro there.
- **Submenu groups, nested**: a key can open a *group* instead of playing a
  macro, and a group can contain further groups to any depth. The overlay
  shows the trail (`Tabs › Advanced › Deep`) tinted in the current group's
  colour. Esc steps back one level; Esc at the top closes.
- **Trigger keys**: A-Z plus F1-F12 and numpad keys.
- **Playback options**: per-macro repeat count and speed multiplier, a
  ▶ Test button on each macro (3-2-1 countdown), and a stop-playback hotkey.
- **Configurable hotkeys** (defaults: `Ctrl+Z` show, `Pause` stop playback):
  change them any time at <http://localhost:5000/settings> — they apply
  instantly, no restart.
- **Running-app picker**: the New app page lists your open windows with
  friendly names (UWP apps resolved to their real exe) so you can add one
  with a click instead of typing the executable name.
- **System tray icon** (right-click menu: Open Web UI, Restart web server,
  Show macro keyboard, Exit) — the app's home when running hidden.
- **Autorun** — tick "Start with Windows" on the Settings page; SoftMacro
  then starts silently at login via `pythonw.exe` (no console window).
- **Single instance** — starting a second copy exits immediately, so
  autorun + manual launch never collide.
- **Local web UI** for everything else: create applications (exe + friendly
  name), build macros with the Quick Add command editor, assign them to
  letters, organise them into nested groups, rename, delete.
- **Per-app JSON storage** in `%APPDATA%\SoftMacro\apps\<exe>.json`.
- **Configurable web port**: the management UI defaults to
  <http://localhost:5000>; change it on the Settings page. It always binds
  to `127.0.0.1`, so it is never exposed to the network (see
  [Security](#security)).
- **Command builder**: on the macro page, a clickable key picker (with
  search) plus input boxes for **Type**, **Wait**, **Click**, **Move**,
  **Scroll** and **Hold/Release** build Quick Add commands for you.
- **Update checker**: Settings → Updates (or the tray menu) checks GitHub
  for a newer version, installs it over HTTPS and can restart SoftMacro
  for you. Installed builds download and run the setup silently; source
  checkouts update in place. Your macros are never touched.
- **Built-in help**: the <http://localhost:5000/help> page documents
  everything — overlay behaviour, every hotkey and key name, all Quick Add
  commands, groups, settings, backups and troubleshooting.
- **Backup & restore**: download all apps, macros and settings as one zip
  (or restore a previous backup) from the Settings page. Apps can also be
  renamed (display name and `.exe`) or deleted, which removes their macros
  with them.

## Install (step by step)

SoftMacro runs on **Windows 10 / 11**. This takes about five minutes and you
only do it once. Everything it needs lives in its own folder — your system
Python installation is left untouched.

### Step 1 — Install Python (skip if you already have 3.10 or newer)

1. Go to <https://www.python.org/downloads/> and download the latest
   **Python 3** installer for Windows.
2. Run the installer. On the first screen, **tick "Add python.exe to
   PATH"** at the bottom — this is easy to miss and SoftMacro needs it.
3. Click **Install Now**, wait for it to finish, then close the installer.

### Step 2 — Download SoftMacro

Pick whichever you prefer:

- **Easiest (ZIP):** open
  <https://github.com/JagerWayne/SoftMacro>, click the green **Code**
  button and choose **Download ZIP**. Right-click the downloaded file →
  **Extract All...** and choose a folder you will remember, e.g.
  `C:\SoftMacro`.
- **With Git:** `git clone https://github.com/JagerWayne/SoftMacro.git`

### Step 3 — Start it

1. Open the folder that contains `run.bat`.
2. Double-click **`run.bat`**.
3. A black console window opens. **The first start takes a minute**: it
   creates a private environment in `venv\` and downloads the packages it
   needs, so it requires an internet connection. Later starts are fast.
4. Wait until you see:

   ```
   [SoftMacro] Ready. Press your hotkey in any application.
   ```

   The SoftMacro icon also appears in the system tray, next to the clock.
5. Leave this window open while you use SoftMacro. Closing it (or pressing
   Ctrl+C in it) quits the app.

### Step 4 — Open the web UI

Go to <http://localhost:5000> in your browser (the startup log prints the
exact address). This is where you create apps, build macros and assign
them to keys — see **Usage** below. You can change the port later on the
Settings page (Settings → Web UI).

### Step 5 — Try it

1. Open and focus any app, for example Notepad.
2. Press **Ctrl + Z** (the default hotkey). The macro keyboard pops up. It
   will be empty at first — that is normal, no macros exist yet.
3. Press **Esc** to close it. Add a macro in the web UI (see **Usage**),
   then press Ctrl + Z again to see it listed.

### Everyday use

- **With a console window:** double-click `run.bat`.
- **Silent, in the tray:** double-click **`run_silent.vbs`** — no console
  window; log output goes to `%APPDATA%\SoftMacro\softmacro.log`.
- **Start with Windows:** open <http://localhost:5000/settings> and tick
  **"Start SoftMacro automatically when Windows starts"**. It then waits in
  the tray every time you log in.
- **Updates:** Settings → Updates checks GitHub and installs a newer
  version in place, then restarts SoftMacro for you (also reachable from
  the tray menu).
- Only one copy can run at a time, so launching it again is harmless.

### Troubleshooting

| Problem | Fix |
| --- | --- |
| `python` is not recognized, or the window closes instantly | Python is not on PATH. Re-run the Python installer, choose **Modify**, and tick **"Add python.exe to PATH"**. |
| `Failed to create venv` | Same as above — install Python with the PATH option. |
| Windows shows "Windows protected your PC" | Click **More info → Run anyway**. This is the standard warning for downloaded scripts. |
| Ctrl + Z does nothing | Some apps swallow the hotkey. Change it at <http://localhost:5000/settings>, and/or run SoftMacro as administrator. |
| Antivirus complains | SoftMacro uses a keyboard hook to register its hotkey and to replay macros — exactly what a macro tool must do. Allow it if you trust the source. |
| The overlay is empty | No macros are assigned to the app that has focus. Create them in the web UI (see **Usage**). |

Hotkey defaults: **Ctrl + Z** opens the overlay, **Pause** cancels a macro
that is playing. Both are configurable at
<http://localhost:5000/settings> and apply instantly.

## Usage

### Create macros (web UI)

1. Open <http://localhost:5000>.
2. **+ New app** — pick one of the running apps from the list (the exe is
   resolved for you) or type the `.exe` file name (e.g. `chrome.exe`) and a
   friendly display name ("Chrome"). The exe is the real identifier; the
   name is just for you.
3. Open the app page, click **+ New macro**, give it a name and add events
   with the Quick Add bar (`Ctrl+T`, `Type "hello"`, `Wait 500`,
   `Click 500 300`, ...). See `events.txt` for the full command list, or
   use the **Command builder** panel: click keys to build a combination,
   or fill the Type / Wait / Click / Move / Scroll / Hold boxes and click
   **Add**.
4. On the app page, use **Assign to letter** on a macro card to bind it to
   a key. Macros left unassigned stay saved — assign them later.
5. To organise keys, click **+ Group** to create a group inside the current
   directory (it is auto-bound to the first free key) and **Open ›** to
   descend into it. The breadcrumb (`Main › Tabs › Advanced`) navigates back
   up, and inside a group you can assign macros or further sub-groups.

### Play macros (hotkey)

1. Focus any application, press your hotkey (default **Ctrl + Z**).
   A compact, 50%-transparent grey list pops up (white text, left-aligned)
   showing only the assigned shortcuts, e.g. `Q = New Tab`.
2. Press a listed letter on the keyboard (or click its row). If the key
   opens a **group**, the overlay switches to that group's list (and the
   breadcrumb in the subtitle grows, e.g. `Tabs › Advanced`). Esc steps
   back one level; Esc on the main list closes the overlay.
3. For a macro key: the overlay hides, focus returns to the application you
   were in, and the macro plays there with original timing.
4. Press the hotkey **again** (or `Esc`) to dismiss the overlay without
   playing.

## File layout

```
SoftMacro/
├── run.bat                # venv bootstrap + launcher (source checkout)
├── run_silent.vbs         # silent launcher (source checkout)
├── build_installer.bat    # PyInstaller + Inno Setup build
├── SoftMacro.spec         # PyInstaller one-folder spec
├── softmacro.ico          # app / installer icon
├── requirements.txt       # pynput, keyboard, flask, pystray, Pillow
├── VERSION                # current version (checked by the updater)
├── app.py                 # entry point (threads: tk / hotkey / web / tray)
├── storage.py             # JSON per app (macros[], nested groups{}, slots{})
├── config.py              # hotkey, overlay + web settings (config.json)
├── branding.py            # app name / version / author
├── runtime.py             # thread-safe event queue bridge to the tk loop
├── updater.py             # GitHub update check + safe installer
├── backup.py              # zip backup / restore of apps + settings
├── autostart.py           # Windows autorun (HKCU Run key)
├── tray.py                # pystray system-tray icon + menu
├── window_info.py         # foreground window / exe / running apps via ctypes
├── player.py              # pynput playback with timing
├── hotkey.py              # keyboard global hotkey
├── overlay.py             # tkinter floating playback window (nested groups)
├── web.py                 # Flask management UI
├── event_parser.py        # Quick Add command language (source of truth)
├── events.txt             # Quick Add command reference (generated from event_parser.py)
├── installer/
│   └── SoftMacro.iss      # Inno Setup script
├── tools/
│   └── make_icon.py       # regenerates softmacro.ico
├── templates/
│   ├── base.html
│   ├── index.html         # list of applications
│   ├── new_app.html       # create application (running-app picker + form)
│   ├── app.html           # per-app macros, breadcrumb, groups + assignments
│   ├── macro_form.html    # create / edit macro with Quick Add + command builder
│   ├── _key_reference.html# shared key picker (chips + search)
│   ├── settings.html      # hotkeys, overlay, web port, updates, autostart
│   ├── help.html          # full user guide + key/command reference
│   ├── restarting.html    # shown while SoftMacro restarts after an update
│   └── 404.html
└── static/
    ├── style.css
    ├── event_editor.js    # Quick Add, events table + command builder
    └── key_reference.js   # shared key picker behaviour
```

## How the threads fit together

```
hotkey  --(queue.Queue)-->   main (tk)   --> Overlay UI
        show_overlay event                --> click letter: hide overlay
                                             -> SetForegroundWindow(target)
                                             -> play (pynput simulate)
web    --(Flask)-->           http://localhost:5000
```

Tkinter must run on the main thread, so all other components post events
into a `queue.Queue` that the tk main loop polls via `root.after(50, ...)`.
When the overlay opens it captures the foreground window's HWND; when a
letter is clicked it hides itself, restores focus to that HWND (with the
classic Alt-tap workaround for Windows' foreground lock), waits ~300 ms for
the target to settle, then replays the events.

## Storage format

`%APPDATA%\SoftMacro\apps\<exe>.json`:

```json
{
  "exe": "chrome.exe",
  "display_name": "Chrome",
  "title_patterns": ["- Google Chrome"],
  "macros": [
    {
      "id": "m_a1b2c3d4",
      "name": "New tab",
      "repeat": 1,
      "speed": 1.0,
      "plays": 12,
      "last_played": 1725800000.0,
      "events": [
        [0,  ["key_down", "Key.ctrl_l"]],
        [12, ["key_down", "t"]],
        [28, ["key_up",   "t"]],
        [40, ["key_up",   "Key.ctrl_l"]]
      ]
    }
  ],
  "groups": [
    {
      "id": "g_abcd1234",
      "name": "Tabs",
      "color": "#ff00ff",
      "slots": {
        "A": "m_a1b2c3d4",
        "S": "g_ef567890"
      }
    },
    {
      "id": "g_ef567890",
      "name": "Advanced",
      "color": "#10b981",
      "slots": { "D": "m_a1b2c3d4" }
    }
  ],
  "slots": {
    "Q": "m_a1b2c3d4",
    "B": "g_abcd1234"
  }
}
```

Macros, groups and slot assignments are separate: a macro can exist
unassigned, one macro can back several letters (in the main view or inside
groups), and a key can open a group instead of playing a macro. A group's
`slots` may point at another group id, so groups nest to any depth — self
references and cycles are rejected. Deleting a macro or group clears every
slot that referenced it.

## Building a Windows installer

The repo ships a PyInstaller spec and an Inno Setup script, so you can build
a normal installer that needs no Python on the target machine:

1. Install [Inno Setup 6](https://jrsoftware.org/isdl.php) (free).
2. Run **`build_installer.bat`**.

It produces:

- `dist\SoftMacro\` — the frozen application (one folder)
- `dist\installer\SoftMacroSetup.exe` — the installer

The installer is per-user (`%LOCALAPPDATA%\Programs\SoftMacro`, no admin
prompt) and adds Start Menu shortcuts, an optional "start with Windows"
task and an uninstaller. Macros in `%APPDATA%\SoftMacro` are never touched,
so installs and upgrades keep your data.

To offer an update to installed copies, publish a GitHub release whose tag
is the new version and attach `SoftMacroSetup.exe` as a release asset
(bump `VERSION` and `branding.APP_VERSION` in the same commit). Installed
builds download that asset and run it silently; source checkouts keep
updating from the repository zip.

## Security

The web UI can inject keystrokes, so it is locked down:

- It binds to **127.0.0.1 only** — other devices on your network cannot
  reach it. The port is configurable on the Settings page (1024–65535).
- Requests with a non-loopback **Host** header are rejected, which blocks
  DNS-rebinding attacks.
- State-changing requests (POST) from a non-loopback **Origin/Referer**
  are rejected, which blocks CSRF from websites open in other tabs.
- Responses carry a restrictive Content-Security-Policy plus
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and
  `Referrer-Policy: same-origin`.
- Flask's debug mode and auto-reloader are off.

Updates are also locked down:

- Only the official repository (`JagerWayne/SoftMacro`) is queried.
- Downloads must be **HTTPS** from GitHub hosts and inside the repository.
- Archive entries with absolute paths, `..` traversal or unknown file
  types are refused.
- Only source files (`*.py`, templates, static assets, docs, launchers)
  are replaced — `%APPDATA%\SoftMacro` and `venv\` are never touched.
- Nothing from an update runs until you restart SoftMacro.

There is no login because there is nothing to log into remotely: the
server only listens on the machine it runs on.

## Notes / known limitations

- The `keyboard` library hooks the keyboard at a low level. On some setups
  it needs to be run as Administrator (right-click `run.bat` -> *Run as
  administrator*) to capture keys sent to elevated apps.
- `pynput`'s `Controller` uses `SendInput` under the hood. Elevated target
  apps and some games with anti-cheat will ignore injected input.
- Closing the hidden root window (`tk`) quits the app. Closing the visible
  overlay window only hides it.

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)
— see [LICENSE](LICENSE). Copyright (c) 2026 Wayne Scicluna.

- **Noncommercial only**: you may not use SoftMacro for commercial purposes,
  including selling it or bundling it into a paid product or service.
- **Notices required**: every copy must include the license terms and the
  `Required Notice:` line naming
  <https://github.com/JagerWayne/SoftMacro>.
