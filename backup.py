"""Backup and restore SoftMacro data as a zip file.

The zip contains the per-application JSON files (macros, groups and key
assignments), ``config.json`` and a small ``manifest.json``::

    manifest.json
    config.json
    apps/chrome.exe.json
    apps/notepad.exe.json

Restoring merges the archive into the data directory (same-name apps are
replaced, others are left alone) and writes a safety copy of the current
data to ``%APPDATA%\\SoftMacro\\backups`` first.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path, PurePosixPath

import branding
import storage

MAX_ENTRIES = 2000
MAX_TOTAL_BYTES = 50 * 1024 * 1024


def data_root() -> Path:
    """The ``%APPDATA%\\SoftMacro`` directory."""
    return storage.data_dir().parent


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backup_filename() -> str:
    return f"SoftMacro-backup-{_timestamp()}.zip"


def create_backup() -> bytes:
    """Zip the current apps and config. Returns the archive bytes."""
    root = data_root()
    apps_dir = root / "apps"
    app_files = sorted(apps_dir.glob("*.json")) if apps_dir.is_dir() else []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = {
            "app": branding.APP_NAME,
            "version": branding.APP_VERSION,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "apps": len(app_files),
        }
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        for f in app_files:
            z.write(f, f"apps/{f.name}")
        cfg = root / "config.json"
        if cfg.is_file():
            z.write(cfg, "config.json")
    return buf.getvalue()


def _parse_archive(blob: bytes) -> dict:
    """Validate and read a backup zip. Returns {ok, apps, config, error}."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "That file is not a zip archive."}

    apps: dict[str, dict] = {}
    config: dict | None = None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            return {"ok": False, "error": "Archive contains too many files."}
        if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            return {"ok": False, "error": "Archive is too large to restore."}

        for info in infos:
            name = info.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                continue  # never trust traversal entries
            if name == "config.json":
                try:
                    config = json.loads(zf.read(info).decode("utf-8"))
                except Exception:
                    return {"ok": False, "error": "config.json is not valid JSON."}
                if not isinstance(config, dict):
                    return {"ok": False, "error": "config.json has an unexpected format."}
                continue
            if (
                len(path.parts) == 2
                and path.parts[0] == "apps"
                and path.suffix.lower() == ".json"
            ):
                try:
                    parsed = json.loads(zf.read(info).decode("utf-8"))
                except Exception:
                    return {"ok": False, "error": f"{name} is not valid JSON."}
                if not isinstance(parsed, dict):
                    return {"ok": False, "error": f"{name} has an unexpected format."}
                apps[path.parts[1]] = parsed

    if not apps and config is None:
        return {"ok": False, "error": "No SoftMacro data found in that zip."}
    return {"ok": True, "apps": apps, "config": config}


def restore_backup(blob: bytes) -> dict:
    """Restore a backup zip. Returns a status dict, never raises."""
    parsed = _parse_archive(blob)
    if not parsed.get("ok"):
        return parsed

    root = data_root()
    apps_dir = root / "apps"
    apps_dir.mkdir(parents=True, exist_ok=True)

    # Safety copy of the current data before anything is overwritten.
    try:
        backups_dir = root / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        (backups_dir / f"pre-restore-{_timestamp()}.zip").write_bytes(create_backup())
    except OSError:
        pass

    written = 0
    for filename, data in parsed["apps"].items():
        data["exe"] = filename[:-5].lower()
        (apps_dir / filename).write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written += 1

    if parsed["config"] is not None:
        (root / "config.json").write_text(
            json.dumps(parsed["config"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return {
        "ok": True,
        "apps": written,
        "config": parsed["config"] is not None,
    }
