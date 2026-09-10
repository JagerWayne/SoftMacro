"""Check GitHub for a newer SoftMacro version and install it.

Trust model
-----------
* Only the official repository (``JagerWayne/SoftMacro``) is queried.
* Downloads must be HTTPS from a small allow-list of GitHub hosts, and
  the path must belong to the repository.
* Archive entries are validated: absolute paths, ``..`` traversal and
  unknown file types are refused.
* Only allow-listed source files are copied over the installation
  (``*.py``, templates, static assets, docs, launchers). User data in
  ``%APPDATA%\\SoftMacro`` and the virtual environment are never touched.

Nothing from an archive is ever executed; the new code only runs after
the user restarts SoftMacro. Installed (frozen) builds instead download
the ``SoftMacroSetup.exe`` asset from the latest GitHub release and run it
silently — the same file a user would download by hand.
"""

from __future__ import annotations

import io
import json
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import branding
import runtime

REPO = "JagerWayne/SoftMacro"
BRANCH = "main"

API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RAW_VERSION = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION"
ZIP_MAIN = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"

INSTALLER_ASSET = "SoftMacroSetup.exe"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"

TRUSTED_HOSTS = {
    "github.com",
    "api.github.com",
    "codeload.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
}

TIMEOUT = 15
_APP_DIR = Path(__file__).resolve().parent

# Files (top level) that may be replaced by an update.
ALLOWED_FILES = {
    "app.py",
    "autostart.py",
    "branding.py",
    "config.py",
    "event_parser.py",
    "events.txt",
    "hotkey.py",
    "LICENSE",
    "overlay.py",
    "player.py",
    "README.md",
    "requirements.txt",
    "run.bat",
    "run_silent.vbs",
    "runtime.py",
    "storage.py",
    "tray.py",
    "updater.py",
    "VERSION",
    "web.py",
    "window_info.py",
}
ALLOWED_DIRS = {"templates", "static"}
ALLOWED_SUFFIXES = {".py", ".html", ".css", ".js", ".txt", ".md", ".bat", ".vbs"}


# ---- version handling -------------------------------------------------------

def version_key(text: str) -> tuple[int, ...]:
    """Turn 'v1.2.3' / '1.2' into a comparable tuple, zero-padded to 4."""
    parts = [int(n) for n in re.findall(r"\d+", text or "")]
    parts = (parts + [0, 0, 0, 0])[:4]
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    return version_key(latest) > version_key(current)


def is_frozen() -> bool:
    """True when running from a PyInstaller build (the installed app)."""
    return bool(getattr(sys, "frozen", False))


# ---- networking -------------------------------------------------------------

def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"SoftMacro/{branding.APP_VERSION}",
            "Accept": "application/vnd.github+json, application/octet-stream",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as resp:
        return resp.read()


def is_trusted_url(url: str) -> bool:
    """True only for HTTPS URLs inside the official repository."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in TRUSTED_HOSTS:
        return False
    path = parts.path or ""
    return f"/{REPO}" in path or f"/{REPO}/" in path


# ---- check ------------------------------------------------------------------

def check_for_update() -> dict:
    """Look for a newer version. Returns a status dict, never raises."""
    current = branding.APP_VERSION
    frozen = is_frozen()
    try:
        # Prefer a published GitHub release...
        try:
            release = json.loads(_fetch(API_LATEST).decode("utf-8", "replace"))
            latest = str(release.get("tag_name") or "").lstrip("vV")
            notes = str(release.get("body") or "")
            html_url = str(release.get("html_url") or RELEASES_URL)
            installer_url = ""
            for asset in release.get("assets") or []:
                if str(asset.get("name", "")).lower() == INSTALLER_ASSET.lower():
                    installer_url = str(asset.get("browser_download_url") or "")
                    break
            # Frozen builds install via the setup exe; source installs
            # update from the repository zip.
            url = installer_url if frozen else str(
                release.get("zipball_url") or ZIP_MAIN
            )
        except urllib.error.HTTPError as e:
            if e.code != 404:            # no releases yet -> use VERSION
                raise
            try:
                latest = _fetch(RAW_VERSION).decode("utf-8", "replace").strip()
            except urllib.error.HTTPError:
                return {"status": "error", "current": current,
                        "error": "No releases or VERSION file found on GitHub yet."}
            notes = ""
            html_url = RELEASES_URL
            url = "" if frozen else ZIP_MAIN

        if not latest:
            return {"status": "error", "current": current,
                    "error": "No version information found on GitHub."}
        if is_newer(latest, current):
            if frozen and not url:
                return {"status": "error", "current": current, "latest": latest,
                        "error": ("A newer version exists, but no installer has "
                                  f"been published yet. Visit {html_url}")}
            return {"status": "update", "current": current, "latest": latest,
                    "notes": notes, "url": url, "html_url": html_url}
        return {"status": "current", "current": current, "latest": latest}
    except Exception as e:
        return {"status": "error", "current": current, "error": str(e)}


# ---- install ----------------------------------------------------------------

def _safe_members(archive: zipfile.ZipFile) -> tuple[str, list[tuple[zipfile.ZipInfo, str]]]:
    """Return (top-level prefix, [(entry, relative path)]).

    Rejects traversal, absolute paths and anything outside the allow-list.
    """
    entries: list[tuple[zipfile.ZipInfo, str]] = []
    prefix = ""
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            continue
        if not prefix and len(path.parts) > 1:
            prefix = path.parts[0]
        rel_parts = path.parts[1:] if prefix and path.parts[0] == prefix else path.parts
        if not rel_parts:
            continue
        rel = PurePosixPath(*rel_parts)
        top = rel.parts[0]
        if len(rel.parts) == 1:
            if top not in ALLOWED_FILES:
                continue
        elif top in ALLOWED_DIRS and rel.suffix.lower() in ALLOWED_SUFFIXES:
            pass
        else:
            continue
        entries.append((info, rel.as_posix()))
    return prefix, entries


def _install_zip(blob: bytes, app_dir: Path | None = None) -> dict:
    """Install an update archive. Returns {ok, files, version, error}."""
    target_dir = Path(app_dir) if app_dir else _APP_DIR
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as e:
        return {"ok": False, "error": f"Downloaded file is not a zip: {e}"}

    prefix, entries = _safe_members(archive)
    if not entries:
        return {"ok": False, "error": "Archive contains no installable files."}

    version = ""
    installed: list[str] = []
    with archive:
        for info, rel in entries:
            data = archive.read(info)
            dest = target_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            installed.append(rel)
            if rel == "VERSION":
                version = data.decode("utf-8", "replace").strip()

    return {"ok": True, "files": installed, "version": version}


def _install_frozen(url: str, info: dict | None) -> dict:
    """Installed build: download the setup exe and run it silently.

    The app quits shortly after so the installer can replace its files;
    Inno Setup closes SoftMacro via the Restart Manager and relaunches it
    when the install completes.
    """
    try:
        blob = _fetch(url)
    except Exception as e:
        return {"ok": False, "error": f"Download failed: {e}"}
    if not blob.startswith(b"MZ"):
        return {"ok": False, "error": "Downloaded file is not a Windows installer."}

    target = Path(tempfile.gettempdir()) / INSTALLER_ASSET
    try:
        target.write_bytes(blob)
    except OSError as e:
        return {"ok": False, "error": f"Could not save the installer: {e}"}

    try:
        subprocess.Popen(
            [str(target), "/SILENT", "/SUPPRESSMSGBOXES",
             "/CLOSEAPPLICATIONS", "/NORESTART"],
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    except Exception as e:
        return {"ok": False, "error": f"Could not start the installer: {e}"}

    threading.Timer(1.5, lambda: runtime.post(("exit", None))).start()
    return {
        "ok": True,
        "files": [],
        "version": (info or {}).get("latest", ""),
        "installer": True,
    }


def install_update(url: str | None = None) -> dict:
    """Download and install the newest version. Returns a status dict."""
    info = check_for_update() if url is None else None
    if url is None:
        if info is None or info.get("status") != "update":
            return {"ok": False, "error": (info or {}).get("error")
                    or "SoftMacro is already up to date."}
        url = info["url"]

    if not is_trusted_url(url):
        return {"ok": False, "error": "Refusing to download from an untrusted address."}

    if is_frozen():
        return _install_frozen(url, info)

    try:
        blob = _fetch(url)
    except Exception as e:
        return {"ok": False, "error": f"Download failed: {e}"}

    try:
        result = _install_zip(blob)
    except Exception as e:
        return {"ok": False, "error": f"Install failed: {e}"}

    if result.get("ok") and not result.get("version"):
        result["version"] = (info or {}).get("latest", "")
    return result
