"""Identify the foreground executable (Windows, via ctypes).

We deliberately avoid pulling in pywin32 for this -- ctypes is in the stdlib
and a few Win32 calls are all we need.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

user32 = ctypes.WinDLL("user32.dll", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

# ---- prototypes -----------------------------------------------------------

GetForegroundWindow = user32.GetForegroundWindow
GetForegroundWindow.argtypes = []
GetForegroundWindow.restype = wintypes.HWND

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
GetWindowThreadProcessId.restype = wintypes.DWORD

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
QueryFullProcessImageNameW.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


# ---- public API -----------------------------------------------------------

def current_exe() -> str:
    """Lowercase file name of the current Python process (used to ignore
    SoftMacro's own windows)."""
    return os.path.basename(sys.executable).lower()


def foreground_window() -> tuple[int | None, str | None]:
    """Return ``(HWND, exe_name)`` for the foreground window.

    ``HWND`` is the raw integer handle (castable to ``HWND`` / ``isize``).
    ``exe_name`` is the lowercase file name (e.g. ``chrome.exe``). Either
    may be ``None`` if the lookup fails at that step.

    UWP apps (Calculator, Settings, ...) are hosted by
    ``ApplicationFrameHost.exe``; the exe is resolved to the real app
    process so stored macros match the app the user actually sees.
    """
    hwnd = GetForegroundWindow()
    if not hwnd:
        return None, None
    # Depending on the ctypes version, HWND may come back as int or as a
    # ctypes pointer wrapper -- normalise.
    hwnd_int: int = hwnd if isinstance(hwnd, int) else int(getattr(hwnd, "value", 0) or 0)
    if not hwnd_int:
        return None, None

    pid = _hwnd_pid(hwnd_int)
    if not pid:
        return hwnd_int, None

    path = _exe_path_for_pid(pid)
    if not path:
        return hwnd_int, None

    exe = os.path.basename(path).lower()
    if exe == "applicationframehost.exe":
        child_pid = _uwp_child_pid(hwnd_int)
        child_path = _exe_path_for_pid(child_pid) if child_pid else None
        if child_path:
            exe = os.path.basename(child_path).lower()
    return hwnd_int, exe


def foreground_exe() -> str | None:
    """Lowercase file name of the process that owns the foreground window,
    or ``None`` if it can't be determined."""
    _, exe = foreground_window()
    return exe


def set_foreground(hwnd: int) -> bool:
    """Bring the window with the given HWND to the foreground.

    Only un-minimizes when actually minimized (``SW_RESTORE`` would also
    un-maximize a maximized window). Verifies the switch with
    ``GetForegroundWindow`` and falls back to the classic Alt-tap
    workaround only if the first attempt didn't take. Returns ``True`` if
    the target ended up in the foreground.
    """
    try:
        u32 = ctypes.WinDLL("user32.dll", use_last_error=True)

        u32.IsIconic.argtypes = [wintypes.HWND]
        u32.IsIconic.restype = wintypes.BOOL

        # If the target was minimized, SetForegroundWindow alone won't
        # surface it -- restore first (only in that case).
        if u32.IsIconic(hwnd):
            u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            u32.ShowWindow.restype = wintypes.BOOL
            u32.ShowWindow(hwnd, 9)  # SW_RESTORE

        u32.SetForegroundWindow.argtypes = [wintypes.HWND]
        u32.SetForegroundWindow.restype = wintypes.BOOL
        u32.GetForegroundWindow.restype = wintypes.HWND

        u32.SetForegroundWindow(hwnd)
        if u32.GetForegroundWindow() == hwnd:
            return True

        # Fallback: fake Alt tap unlocks Windows' foreground lock, retry.
        u32.keybd_event(0x12, 0, 0, 0)  # VK_MENU down
        u32.keybd_event(0x12, 0, 2, 0)  # VK_MENU up
        u32.SetForegroundWindow(hwnd)
        return u32.GetForegroundWindow() == hwnd
    except Exception:
        return False


# ---- running applications ---------------------------------------------------
#
# Enumerate visible top-level windows and turn them into a friendly list of
# "Display name - exe" entries for the New-app page. The display name comes
# from the executable's version resource (FileDescription), which is what
# Task Manager / the taskbar show (e.g. chrome.exe -> "Google Chrome").
# UWP windows hosted by ApplicationFrameHost.exe are resolved to the real
# app process via their child CoreWindow.

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
_CORE_WINDOW_CLASS = "Windows.UI.Core.CoreWindow"

# Windows shell/UI hosts that are never useful macro targets.
_SHELL_NOISE = {
    "applicationframehost.exe",
    "textinputhost.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "searchhost.exe",
    "searchapp.exe",
    "lockapp.exe",
    "sihost.exe",
}

GetWindowThreadProcessId = user32.GetWindowThreadProcessId
GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
GetWindowThreadProcessId.restype = wintypes.DWORD

EnumWindows = user32.EnumWindows
_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

EnumChildWindows = user32.EnumChildWindows
_EnumChildWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

IsWindowVisible = user32.IsWindowVisible
IsWindowVisible.argtypes = [wintypes.HWND]
IsWindowVisible.restype = wintypes.BOOL

GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowTextLengthW.argtypes = [wintypes.HWND]
GetWindowTextLengthW.restype = ctypes.c_int

GetWindowTextW = user32.GetWindowTextW
GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
GetWindowTextW.restype = ctypes.c_int

GetClassNameW = user32.GetClassNameW
GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
GetClassNameW.restype = ctypes.c_int

try:
    GetWindowLongPtrW = user32.GetWindowLongPtrW
except AttributeError:  # 32-bit Windows
    GetWindowLongPtrW = user32.GetWindowLongW
GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
GetWindowLongPtrW.restype = ctypes.c_longlong

version = ctypes.WinDLL("version.dll", use_last_error=True)

_GetFileVersionInfoSizeW = version.GetFileVersionInfoSizeW
_GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_GetFileVersionInfoSizeW.restype = wintypes.DWORD

_GetFileVersionInfoW = version.GetFileVersionInfoW
_GetFileVersionInfoW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
]
_GetFileVersionInfoW.restype = wintypes.BOOL

_VerQueryValueW = version.VerQueryValueW
_VerQueryValueW.argtypes = [
    ctypes.c_void_p,
    wintypes.LPCWSTR,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wintypes.UINT),
]
_VerQueryValueW.restype = wintypes.BOOL

_description_cache: dict[str, str | None] = {}


def _exe_path_for_pid(pid: int) -> str | None:
    """Full image path of a process id, or None if it can't be read."""
    try:
        handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except OSError:
        return None
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if not QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        CloseHandle(handle)


def _hwnd_pid(hwnd) -> int:
    pid = wintypes.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _window_title(hwnd) -> str:
    length = GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _uwp_child_pid(frame_hwnd) -> int | None:
    """Real app pid behind an ApplicationFrameHost window, if findable."""
    frame_pid = _hwnd_pid(frame_hwnd)
    found: list[int] = []

    def visit(child, _lparam):
        pid = _hwnd_pid(child)
        if pid and pid != frame_pid:
            cls = ctypes.create_unicode_buffer(256)
            GetClassNameW(child, cls, 256)
            if cls.value == _CORE_WINDOW_CLASS:
                found.append(pid)
                return False  # stop enumerating
        return True

    EnumChildWindows(frame_hwnd, _EnumChildWindowsProc(visit), 0)
    return found[0] if found else None


def _file_description(path: str) -> str | None:
    """Friendly name from the exe's version resource (e.g. 'Google Chrome')."""
    if path in _description_cache:
        return _description_cache[path]
    desc: str | None = None
    try:
        size = _GetFileVersionInfoSizeW(path, None)
        if size:
            data = ctypes.create_string_buffer(size)
            if _GetFileVersionInfoW(path, 0, size, data):
                ptr = ctypes.c_void_p()
                length = wintypes.UINT()
                if _VerQueryValueW(
                    data, "\\VarFileInfo\\Translation",
                    ctypes.byref(ptr), ctypes.byref(length),
                ):
                    words = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD))
                    lang, codepage = words[0], words[1]
                    key = (
                        "\\StringFileInfo\\%04x%04x\\FileDescription"
                        % (lang, codepage)
                    )
                    sptr = ctypes.c_void_p()
                    slen = wintypes.UINT()
                    if _VerQueryValueW(
                        data, key, ctypes.byref(sptr), ctypes.byref(slen)
                    ) and sptr.value:
                        text = ctypes.wstring_at(sptr.value).strip()
                        if text:
                            desc = text
    except Exception:
        desc = None
    _description_cache[path] = desc
    return desc


def _title_to_name(title: str) -> str:
    """'Untitled - Notepad' -> 'Notepad' (fallback when no version info)."""
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return title.strip()


def _humanize(exe: str) -> str:
    stem = exe[:-4] if exe.lower().endswith(".exe") else exe
    return " ".join(
        w.capitalize() for w in stem.replace("_", " ").replace("-", " ").split()
    )


def running_apps() -> list[dict]:
    """Visible applications as ``[{exe, name, title}, ...]`` sorted by name.

    One entry per exe (deduped); apps with no visible window are skipped.
    Best effort: entries we can't inspect are simply omitted.
    """
    apps: dict[str, dict] = {}
    own_pid = os.getpid()

    def visit(hwnd, _lparam):
        if not IsWindowVisible(hwnd):
            return True
        if GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        title = _window_title(hwnd)
        if not title:
            return True
        pid = _hwnd_pid(hwnd)
        if not pid or pid == own_pid:
            return True
        path = _exe_path_for_pid(pid)
        if not path:
            return True
        exe = os.path.basename(path).lower()
        if exe == "applicationframehost.exe":
            child_pid = _uwp_child_pid(hwnd)
            child_path = _exe_path_for_pid(child_pid) if child_pid else None
            if child_path:
                path = child_path
                exe = os.path.basename(path).lower()
        if exe in _SHELL_NOISE:
            return True
        entry = apps.get(exe)
        if entry is None:
            apps[exe] = {
                "exe": exe,
                "name": (
                    _file_description(path)
                    or _title_to_name(title)
                    or _humanize(exe)
                ),
                "title": title,
            }
        return True

    EnumWindows(_EnumWindowsProc(visit), 0)
    return sorted(apps.values(), key=lambda a: (a["name"] or a["exe"]).lower())
