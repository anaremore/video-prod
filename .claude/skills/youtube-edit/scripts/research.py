"""Capture a website screenshot for the video (the "researcher" step).

    python research.py <slug> <url> [--name hyperframes] [--height 2400] [--width 1500]

Saves videos/<slug>/research/<name>.png using headless Chrome (the copy HyperFrames already
downloaded), ready for the browser-frame template. Pages are captured tall so the template can
scroll them. Cookie banners may appear — crop or retake if they cover the content.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

from common import MOTION, Video, log, run

CLI = MOTION / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"


def chrome_path() -> str:
    if os.environ.get("VP_CHROME"):
        return os.environ["VP_CHROME"]
    r = run(["node", str(CLI), "browser", "path"], check=False, env={"HYPERFRAMES_NO_UPDATE_CHECK": "1"})
    for line in (r.stdout + r.stderr).splitlines():
        line = line.strip()
        if line.lower().endswith(".exe") and Path(line).exists():
            return line
    for cand in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if Path(cand).exists():
            return cand
    found = shutil.which("chrome") or shutil.which("msedge")
    if not found:
        raise SystemExit("No Chrome found. Set VP_CHROME to a chrome.exe path.")
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("url")
    ap.add_argument("--name", help="file name (default: from the domain)")
    ap.add_argument("--width", type=int, default=1500)
    ap.add_argument("--height", type=int, default=2400)
    ap.add_argument("--wait", type=float, default=8.0, help="seconds to let the page load before capturing")
    a = ap.parse_args()

    v = Video(a.slug)
    v.research.mkdir(exist_ok=True)
    url = a.url if re.match(r"https?://", a.url) else "https://" + a.url
    name = a.name or re.sub(r"[^a-z0-9]+", "-", re.sub(r"^https?://(www\.)?", "", url).lower()).strip("-")[:60]
    out = v.research / f"{name}.png"
    exe = chrome_path()
    # A fixed --timeout, not --virtual-time-budget: animated pages never go idle and would hang.
    cmd = [exe, "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--mute-audio",
           f"--window-size={a.width},{a.height}", f"--timeout={int(a.wait * 1000)}", f"--screenshot={out}", url]
    if "headless-shell" not in Path(exe).name:
        cmd.insert(1, "--headless=new")  # full Chrome needs the flag; the headless shell is always headless
    out.unlink(missing_ok=True)
    try:
        subprocess.run(cmd, capture_output=True, timeout=a.wait + 45)
    except subprocess.TimeoutExpired:
        pass
    if not out.exists():
        raise SystemExit(f"Screenshot failed for {url}")
    log(f"Saved research/{out.name} ({a.width}x{a.height}) — use it with the browser-frame template: "
        f'"image": "research/{out.name}", "url": "{re.sub(r"^https?://", "", url).rstrip("/")}"')


if __name__ == "__main__":
    main()
