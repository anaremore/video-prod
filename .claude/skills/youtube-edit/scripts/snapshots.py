"""Grab frames as a contact sheet so Claude (or you) can look at the video without playing it.

    python snapshots.py <slug> [--from flat|base|preview|final|source] [--every 10] [--at 12.5,40] [--graphics]

Writes videos/<slug>/work/snapshots/<from>-sheet.png (a labelled grid) plus the single frames.
Use --from source on an ISO recording to see the screen and decide layout views/zoom targets;
--graphics grabs the middle of every graphic to check them (use --from preview before the final render).
"""
from __future__ import annotations

import argparse

from common import FONTS_TTF, MOTION, Video, ffmpeg, filter_path, fmt_time, load_json, log, media_info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--from", dest="src", default="final", choices=["flat", "base", "preview", "final", "source"])
    ap.add_argument("--every", type=float, default=0, help="one frame every N seconds")
    ap.add_argument("--at", help="comma-separated times in seconds")
    ap.add_argument("--graphics", action="store_true", help="the middle of each graphic in plan.json")
    ap.add_argument("--cols", type=int, default=3)
    a = ap.parse_args()

    v = Video(a.slug)
    path = {"flat": v.path("flat.mp4"), "base": v.path("base.mp4"), "source": v.source,
            "preview": v.final / f"{a.slug}-preview.mp4", "final": v.final / f"{a.slug}.mp4"}[a.src]
    if not path.exists():
        raise SystemExit(f"{path} doesn't exist yet")
    dur = media_info(path)["duration"]
    times: list[float] = []
    if a.at:
        times += [float(x) for x in a.at.split(",")]
    if a.graphics:
        reg = load_json(MOTION / "templates" / "templates.json")
        for g in v.plan().get("graphics", []):
            d = float(g.get("duration", reg.get(g["template"], {}).get("default_duration", 3)))
            times.append(float(g["start"]) + d / 2)
    if a.every or not times:
        step = a.every or max(dur / 12, 1)
        t = step / 2
        while t < dur:
            times.append(t)
            t += step
    times = sorted(t for t in set(times) if 0 <= t < dur)[:48]

    out_dir = v.work / "snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{a.src}-*.png"):
        old.unlink()
    font = filter_path(FONTS_TTF / "inter-latin-700-normal.ttf")
    frames = []
    for i, t in enumerate(times):
        f = out_dir / f"{a.src}-{i:02d}.png"
        label = fmt_time(t).replace(":", "\\:")
        ffmpeg(["-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf",
                f"scale=640:-2,drawtext=fontfile='{font}':text='{label}':x=10:y=10:fontsize=26:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6",
                f])
        frames.append(f)
    cols = min(a.cols, len(frames))
    rows = (len(frames) + cols - 1) // cols
    sheet = out_dir / f"{a.src}-sheet.png"
    ffmpeg(["-framerate", "1", "-i", out_dir / f"{a.src}-%02d.png", "-vf",
            f"tile={cols}x{rows}:padding=6:margin=6:color=0x202020", "-frames:v", "1", "-update", "1", sheet])
    log(f"Wrote {sheet} ({len(frames)} frames)")


if __name__ == "__main__":
    main()
