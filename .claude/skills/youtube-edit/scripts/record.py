"""Recording companion: logs clicks + cursor while OBS records, for auto-zoom and smarter cuts.

    python record.py            # leave running; start/stop recording in OBS as usual (Ctrl+C to quit)

Needs the OBS WebSocket server on (the password is read from OBS's config). Each time an OBS
recording starts it finds the window being recorded — the size-locked one (brand.json
recording.screen_app at recording.screen_size, e.g. Chrome at 1920x1080) — and logs positions in
that window's content pixels, following it if it moves; clicks outside it (like OBS's Stop button)
are ignored. Without a locked window it logs the whole primary monitor. When the recording stops it
writes <recording>.clicks.json next to the video file:
  screen  {"x", "y", "w", "h", "window"}   the recorded area (window title, or null for the monitor)
  clicks  [{"t", "x", "y", "button"}]      mouse clicks (t = seconds into the recording)
  cursor  [[t, x, y], ...]                 cursor position, 10 per second, while over the area
  typing  [[start, end], ...]              when you were typing (activity only — keys are NOT recorded)
  markers [{"t", "type"}]                  F9 = "retake" (you flubbed; cut back to before this)
new_video.py picks the file up automatically. Pausing in OBS is handled.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import json
import threading
import time
from pathlib import Path

from common import brand, obs_password

LOCK = threading.Lock()


class Session:
    def __init__(self):
        self.reset()

    def reset(self):
        self.active = False
        self.paused = False
        self.t0 = 0.0
        self.pause_started = 0.0
        self.paused_total = 0.0
        self.clicks, self.cursor, self.markers, self.typing = [], [], [], []

    def now(self) -> float | None:
        if not self.active or self.paused:
            return None
        return round(time.perf_counter() - self.t0 - self.paused_total, 3)


class Target:
    """The recorded area: the size-locked window's content (follows moves), else the primary monitor."""

    def __init__(self):
        self.hwnd, self.title = None, None
        self.rect = primary_monitor()

    def find(self) -> None:
        from winutil import locked_window
        rec = brand()["recording"]
        w = locked_window(rec.get("screen_app", "chrome.exe"), tuple(rec.get("screen_size", rec["screen"][2:])))
        if w:
            self.hwnd, self.title, self.rect = w["hwnd"], w["title"], w["client"]
        else:
            self.hwnd, self.title, self.rect = None, None, primary_monitor()

    def refresh(self) -> None:
        if self.hwnd:
            from winutil import client_rect
            r = client_rect(self.hwnd)
            if r:
                self.rect = r

    def local(self, x: int, y: int) -> tuple[int, int] | None:
        rx, ry, rw, rh = self.rect
        lx, ly = x - rx, y - ry
        return (lx, ly) if 0 <= lx < rw and 0 <= ly < rh else None


S = Session()
T = None  # Target, created after DPI awareness is set


def primary_monitor() -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def cursor_pos() -> tuple[int, int]:
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def poll_cursor(stop: threading.Event) -> None:
    while not stop.is_set():
        with LOCK:
            t = S.now()
            if t is not None:
                T.refresh()
                p = T.local(*cursor_pos())
                if p:
                    S.cursor.append([t, *p])
        time.sleep(0.1)


def write_log(output_path: str) -> None:
    if not output_path:
        print("  (OBS didn't report the file path; log not saved)")
        return
    typing = []  # merge key activity into bursts
    for t in sorted(S.typing):
        if typing and t - typing[-1][1] <= 1.5:
            typing[-1][1] = t
        else:
            typing.append([t, t])
    x, y, w, h = T.rect
    data = {"screen": {"x": x, "y": y, "w": w, "h": h, "window": T.title},
            "clicks": S.clicks, "cursor": S.cursor, "typing": typing, "markers": S.markers}
    out = Path(output_path).with_suffix(".clicks.json")
    out.write_text(json.dumps(data), encoding="utf-8")
    print(f"  saved {out.name}: {len(S.clicks)} clicks, {len(S.markers)} markers, {len(typing)} typing bursts")


def main() -> None:
    global T
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=4455)
    a = ap.parse_args()

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # physical pixels, matching what OBS captures
    except OSError:
        pass
    T = Target()

    import logging
    import obsws_python as obs
    logging.getLogger("obsws_python").setLevel(logging.CRITICAL)  # handled errors are expected
    from pynput import keyboard, mouse

    def on_click(x, y, button, pressed):
        if pressed:
            with LOCK:
                t = S.now()
                if t is not None:
                    T.refresh()
                    p = T.local(x, y)
                    if p:  # clicks outside the recorded window (e.g. OBS's Stop button) don't count
                        S.clicks.append({"t": t, "x": p[0], "y": p[1], "button": button.name})

    def on_press(key):
        with LOCK:
            t = S.now()
            if t is None:
                return
            if key == keyboard.Key.f9:
                S.markers.append({"t": t, "type": "retake"})
                print(f"  marker: retake at {t:.1f}s")
            else:
                S.typing.append(t)  # activity time only; which key is never stored

    def on_record_state_changed(data):
        state = data.output_state
        with LOCK:
            if state == "OBS_WEBSOCKET_OUTPUT_STARTED":
                S.reset()
                T.find()
                S.active, S.t0 = True, time.perf_counter()
                where = f"window '{T.title[:50]}' {T.rect[2]}x{T.rect[3]}" if T.title else "whole monitor (no locked window)"
                print(f"● recording — logging clicks in {where} (F9 = mark a retake)")
            elif state == "OBS_WEBSOCKET_OUTPUT_PAUSED":
                S.paused, S.pause_started = True, time.perf_counter()
            elif state == "OBS_WEBSOCKET_OUTPUT_RESUMED":
                S.paused = False
                S.paused_total += time.perf_counter() - S.pause_started
            elif state == "OBS_WEBSOCKET_OUTPUT_STOPPED":
                print("■ stopped")
                write_log(getattr(data, "output_path", None))
                S.reset()

    ev = obs.EventClient(host=a.host, port=a.port, password=obs_password(), subs=obs.Subs.OUTPUTS)
    ev.callback.register(on_record_state_changed)
    stop = threading.Event()
    threading.Thread(target=poll_cursor, args=(stop,), daemon=True).start()
    with mouse.Listener(on_click=on_click), keyboard.Listener(on_press=on_press):
        print("Connected to OBS. Watching for recordings. Ctrl+C to quit.")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop.set()
            ev.disconnect()


if __name__ == "__main__":
    main()
