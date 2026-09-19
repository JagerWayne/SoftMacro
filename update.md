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

```powershell
.\venv\Scripts\python.exe -m py_compile anim.py overlay.py app.py web.py config.py storage.py hotkey.py player.py
```

Fix anything broken before continuing.

## 3. Commit and push the source

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

## 4. Build the application bundle (PyInstaller)

`build_installer.bat` ends with `pause`, which blocks automation — run the
steps directly instead:

```powershell
.\venv\Scripts\python.exe -m PyInstaller --noconfirm --clean SoftMacro.spec
```

Output: `dist\SoftMacro\`.

## 5. Build the installer (Inno Setup 6)

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

## 6. Tag and publish the GitHub release

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
- [ ] Committed and pushed to `main`
- [ ] PyInstaller bundle built in `dist\SoftMacro\`
- [ ] `SoftMacroSetup.exe` built and `ProductVersion == {V}`
- [ ] Annotated tag `v{V}` pushed
- [ ] GitHub release created with `SoftMacroSetup.exe` attached

## Reminders

- Bump the version in **both** `VERSION` and `branding.APP_VERSION`.
- Never commit `dist/`, `build/`, or `venv/`.
- Never touch `%APPDATA%\SoftMacro\` (user apps, config, backups).
- The updater compares `VERSION`; the release must tag that exact version and
  attach `SoftMacroSetup.exe`.
