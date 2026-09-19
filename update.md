# update.md — SoftMacro release runbook

Execute this when the user says **"Execute update.md"**.

Goal: bump the version, build the Windows installer, and publish a GitHub
release with the installer attached.

---

## 0. Decide the version

- If the user named a version (e.g. "bump to 1.3.0"), use it.
- Otherwise ask for it and propose the next sensible semver:
  - **MAJOR** — breaking changes
  - **MINOR** — new features (e.g. 1.2.0 -> 1.3.0)
  - **PATCH** — fixes only (e.g. 1.2.0 -> 1.2.1)

Let `V` be the version (e.g. `1.3.0`) and tag it `v{V}`.

## 1. Bump the version (two places, keep them in sync)

- `VERSION` (repo root) -> `{V}`
- `branding.py` -> `APP_VERSION = "{V}"`

## 2. Sanity check

Compile **every** Python file in the repo (a version-bump edit has corrupted a
module string before, so never compile only a hand-picked subset):

```powershell
.\venv\Scripts\python.exe -m compileall -q -x "venv|build|dist|tools" .
```

Any output (other than nothing) means a syntax error — fix it before
continuing.

Verify the version string is well-formed and importable:

```powershell
.\venv\Scripts\python.exe -c "import branding; print(branding.APP_VERSION)"
```

It must print `{V}`.

## 3. Update the help & documentation (whole codebase)

Any user-visible change must be reflected in the docs **before committing**:

- `templates/help.html` — the in-app user guide. Update the Settings reference,
  the Overlay sections, feature descriptions and the "Data & backups" notes
  whenever behaviour, settings, pages or key names change. Keep the TOC anchors
  in sync with the section `id`s.
- `templates/_key_reference.html` / `static/key_reference.js` — only if the set
  of supported keys or the picker behaviour changed.
- `events.txt` — regenerate when Quick Add commands changed (single source of
  truth is `event_parser.py`):
  `.\venv\Scripts\python.exe event_parser.py events.txt`
- `README.md` — features list, usage steps, file-layout tree and
  troubleshooting.
- `AGENTS.md` — architecture / conventions if the change affects them.
- `web.py` module docstring — the endpoint list, if a route was added/removed.

Search for stale references to anything renamed or moved:

```powershell
rg -n "old name|/old/route" --glob "!venv/**" --glob "!dist/**"
```

## 4. Commit and push the source

Inspect first, then commit only intended files (never commit `dist/` or user
data in `%APPDATA%\SoftMacro`):

```powershell
git status --short
git diff --stat
git add -A
git commit -m "<concise summary of the changes>; bump version to {V}"
git push origin main
```

Match the repo's commit style: descriptive sentence, often ending with
`; bump version to X.Y.Z`.

## 5. Build the application bundle (PyInstaller)

`build_installer.bat` ends with `pause`, which blocks automation — run the
steps directly instead:

```powershell
.\venv\Scripts\python.exe -m PyInstaller --noconfirm --clean SoftMacro.spec
```

Output: `dist\SoftMacro\`.

**Fail-safe check** — the bundle must not report invalid modules (a broken
source module produces a frozen app that crashes on launch with
`ModuleNotFoundError`):

```powershell
$warn = Get-Content "build\SoftMacro\warn-SoftMacro.txt" -Raw
if ($warn -match "invalid module named") {
    $warn -split "`n" | Select-String "invalid module named"
    throw "PyInstaller reported invalid modules - fix and rebuild before releasing."
}
"PyInstaller warnings OK"
```

## 6. Build the installer (Inno Setup 6)

Find `ISCC.exe` (first match wins):

- `%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe`
- `%ProgramFiles%\Inno Setup 6\ISCC.exe`
- `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`

If none exist, install Inno Setup 6 (https://jrsoftware.org/isdl.php) and stop.

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" "installer\SoftMacro.iss"
```

Output: `dist\installer\SoftMacroSetup.exe`. The version comes from `VERSION`,
so no `.iss` edit is needed.

Verify the installer carries the new version:

```powershell
$f = Get-Item "dist\installer\SoftMacroSetup.exe"
"size: {0:N0}" -f $f.Length
"version: $($f.VersionInfo.ProductVersion)"
```

`version:` must equal `{V}`. If not, the `VERSION` bump was missed.

## 7. Tag and publish the GitHub release

Annotated tag, matching existing style (`SoftMacro 1.2.0`):

```powershell
git tag -a "v{V}" -m "SoftMacro {V}"
git push origin "v{V}"
```

Create the release with the installer attached. In PowerShell, double the
backticks to get literal Markdown backticks in the notes:

```powershell
gh release create "v{V}" "dist\installer\SoftMacroSetup.exe" `
  --title "SoftMacro {V}" `
  --notes "### Added`n- ...`n`n### Fixed`n- ...`n`nFull setup: ``SoftMacroSetup.exe`` (Windows per-user install)."
```

Use the repo's established release-note shape (`### Added` / `### Fixed`, then
the `Full setup:` line).

Confirm the asset uploaded:

```powershell
gh release view "v{V}" --json name,tagName,assets
```

Report the release URL back to the user.

---

## Checklist

- [ ] Version decided (`{V}`)
- [ ] `VERSION` and `branding.APP_VERSION` set to `{V}`
- [ ] `py_compile` passes
- [ ] Help/docs updated (`templates/help.html`, `README.md`, `events.txt`,
      `AGENTS.md`, `web.py` docstring) — see step 3
- [ ] Committed and pushed to `main`
- [ ] PyInstaller bundle built in `dist\SoftMacro\`
- [ ] `SoftMacroSetup.exe` built and `ProductVersion == {V}`
- [ ] Annotated tag `v{V}` pushed
- [ ] GitHub release created with `SoftMacroSetup.exe` attached

## Reminders

- Bump the version in **both** `VERSION` and `branding.APP_VERSION`.
- Keep the help/documentation in sync as part of every release (step 3) — the
  in-app Help page is the user's manual.
- Never commit `dist/`, `build/`, or `venv/`.
- Never touch `%APPDATA%\SoftMacro\` (user apps, config, backups).
- The updater compares `VERSION`; the release must tag that exact version and
  attach `SoftMacroSetup.exe`.
