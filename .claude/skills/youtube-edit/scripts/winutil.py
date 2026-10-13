"""Find the window locked for recording (Windows only, ctypes — no dependencies).

A window-locking tool such as FrameLock (https://github.com/anaremore/framelock) pins an app's
*client area* to an exact size, e.g. Chrome at 1920x1080. The recording setup captures that window, so "the recording window" is simply the
visible top-level window of the given executable whose client area is exactly that size.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

try:  # physical pixels everywhere (FrameLock and OBS are per-monitor DPI aware too)
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError, OSError):
    pass

_ENUM = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _exe_of(hwnd: int) -> str:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def title_of(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def class_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def obs_window_id(w: dict) -> str:
    """OBS's "title:class:exe" window string (':' and '#' escaped the way OBS does)."""
    enc = lambda x: x.replace("#", "#22").replace(":", "#3A")  # noqa: E731
    return f"{enc(w['title'])}:{enc(w['class'])}:{enc(w['exe'])}"


def client_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Client area as (x, y, w, h) in screen pixels, or None if the window is gone."""
    if not user32.IsWindow(hwnd):
        return None
    r = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, r.right - r.left, r.bottom - r.top


def windows_of(exe: str) -> list[dict]:
    """Visible, non-minimized top-level windows of an executable, with their client rects."""
    found = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd) and _exe_of(hwnd) == exe.lower():
            rect = client_rect(hwnd)
            title = title_of(hwnd)
            if rect and title:
                found.append({"hwnd": hwnd, "title": title, "client": rect, "class": class_of(hwnd), "exe": exe.lower()})
        return True

    user32.EnumWindows(_ENUM(cb), 0)
    return found


def locked_window(exe: str, size: tuple[int, int]) -> dict | None:
    """The window FrameLock locked: client area exactly `size`. None if there isn't exactly one."""
    hits = [w for w in windows_of(exe) if tuple(w["client"][2:]) == tuple(size)]
    return hits[0] if len(hits) == 1 else None


def describe(exe: str, size: tuple[int, int]) -> str:
    wins = windows_of(exe)
    if not wins:
        return f"no visible {exe} window"
    sizes = ", ".join(f"{w['client'][2]}x{w['client'][3]}" for w in wins[:6])
    hits = sum(1 for w in wins if tuple(w["client"][2:]) == tuple(size))
    if hits > 1:
        return f"{hits} {exe} windows are {size[0]}x{size[1]} — lock only one"
    return f"{len(wins)} {exe} window(s), client sizes: {sizes} — none is {size[0]}x{size[1]}"
