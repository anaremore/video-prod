"""Render a style gallery: every graphic template in every theme, as labelled contact sheets.

    python gallery.py [--themes glass,bold] [--templates title-card,callout] [--bg frame.png|video.mp4|plain] [--jobs 3]

Writes motion/gallery/<theme>.png (one sheet per theme, graphics + a captions sample) and motion/gallery/all.png (overview). Overlays
are shown on top of a real frame (--bg, or the newest videos/*/work/base.mp4) so they're judged in
context. Renders are cached in motion/gallery/cache; re-runs only render what changed. Use it to pick
brand.json "style", and after editing a theme or template to check every combination at once.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common import FONTS_TTF, MOTION, VIDEOS, ffmpeg, filter_path, load_json, log, media_info, themes, theme
from graphics import prepare, render

OUT = MOTION / "gallery"
SAMPLES = {  # template -> (props, frame time to show, seconds rendered)
    "title-card": ({"kicker": "Product walkthrough", "title": "Acme Studio", "subtitle": "From signup to first project"}, 1.7, 3.0),
    "lower-third": ({"title": "Jane Doe", "subtitle": "Founder, Acme Studio"}, 1.5, 3.0),
    "callout": ({"text": "Free plan available", "label": "Heads up", "position": "top-left"}, 1.3, 3.0),
    "highlight": ({"x": 700, "y": 600, "w": 520, "h": 84, "shape": "box", "label": "Click here", "dim": True}, 1.6, 3.0),
    "steps": ({"steps": "Sign up, Configure, Launch, Done", "current": 1}, 1.6, 3.0),
    "kinetic": ({"text": "Ship it faster", "emphasis": "faster"}, 1.6, 3.0),
    "tool-cards": ({"heading": "How it works", "highlight": 1, "items": [
        {"role": "Plan", "name": "Write the outline"}, {"role": "Build", "name": "Record the demo"},
        {"role": "Ship", "name": "Publish the edit"}]}, 2.0, 3.2),
    "end-card": ({"title": "Thanks for watching", "subtitle": "New videos every week", "cta": "Subscribe"}, 1.9, 3.2),
}


def background(arg: str | None) -> Path:
    """A 1920x1080 still to put overlays on: an image, a video frame, the newest edited video, or "plain"."""
    bg = OUT / "cache" / "background.png"
    src = Path(arg) if arg and arg != "plain" else None
    if src is None and arg != "plain":
        bases = sorted(VIDEOS.glob("*/work/base.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        src = bases[0] if bases else None
    if src is None:
        ffmpeg(["-f", "lavfi", "-i", "gradients=s=1920x1080:c0=0x3a4a5a:c1=0x1a2028:d=1", "-frames:v", "1", bg])
    elif src.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
        t = media_info(src)["duration"] * 0.45
        ffmpeg(["-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", "-vf", "scale=1920:1080", bg])
    else:
        ffmpeg(["-i", src, "-frames:v", "1", "-vf", "scale=1920:1080", bg])
    return bg


def caption_tile(name: str, bg: Path, out: Path, draw: str) -> None:
    """The theme's caption look: one line over the background with the spoken word highlighted."""
    from captions import ass_color
    c = theme(name)["captions"]
    border, edge = (3, c.get("box_color", "#ffffff")) if c.get("box") else (1, c["outline"])
    lead = r"{\blur4}" if c.get("glow") else ""
    on, off = (r"{\fscx114\fscy114}", r"{\fscx100\fscy100}") if c.get("pop") else ("", "")
    words = ["This", "is", "how", "captions", "look"]
    words = [w.upper() for w in words] if c.get("uppercase") else words
    hi, base = ass_color(c["highlight"]), ass_color(c["color"])
    words[3] = "{\\c" + hi + "}" + on + words[3] + off + "{\\c" + base + "}"
    ass = OUT / "cache" / f"{name}--captions.ass"
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{c['font']},{c['size']},{base},{base},{ass_color(edge)},{ass_color('#000000', 0x60)},0,0,0,0,100,100,0,0,{border},{c['outline_px']},{c['shadow_px']},2,120,120,{c['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Cap,,0,0,0,,{lead}{' '.join(words)}
""", encoding="utf-8-sig")
    ffmpeg(["-i", bg, "-vf", f"subtitles=filename='{filter_path(ass)}':fontsdir='{filter_path(FONTS_TTF)}',{draw}",
            "-frames:v", "1", out])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--themes", help="comma-separated (default: all)")
    ap.add_argument("--templates", help="comma-separated (default: all with samples)")
    ap.add_argument("--bg", help='background image or video for overlays, or "plain" for a neutral gradient')
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args()

    names = a.themes.split(",") if a.themes else list(themes())
    tpls = a.templates.split(",") if a.templates else list(SAMPLES)
    registry = load_json(MOTION / "templates" / "templates.json")
    (OUT / "cache").mkdir(parents=True, exist_ok=True)
    bg = background(a.bg)

    jobs, tiles = [], {}
    for name in names:
        th = theme(name)
        for tpl in tpls:
            props, at, dur = SAMPLES[tpl]
            gid = f"{name}--{tpl}"
            html, vars_, key = prepare({"id": gid, "template": tpl, "duration": dur, "props": props}, "_gallery", registry, th)
            clip, key_file = OUT / "cache" / f"{gid}.webm", OUT / "cache" / f"{gid}.key"
            tiles[gid] = (clip, at, registry[tpl].get("fullscreen", False))
            if not (clip.exists() and key_file.exists() and key_file.read_text() == key):
                jobs.append((gid, html, vars_, clip, key_file, key))
    if jobs:
        log(f"Rendering {len(jobs)} gallery sample(s) ({a.jobs} at a time)...")
        with ThreadPoolExecutor(max_workers=a.jobs) as pool:
            futs = {pool.submit(render, h, vp, c, 10, "draft"): (gid, kf, k) for gid, h, vp, c, kf, k in jobs}
            for f in as_completed(futs):
                gid, kf, k = futs[f]
                try:
                    f.result()
                    kf.write_text(k)
                    log(f"  {gid}")
                except RuntimeError as e:
                    log(f"  {gid}: FAILED\n{e}")

    font = filter_path(FONTS_TTF / "inter-latin-700-normal.ttf")
    for name in names:
        frames = []
        for i, tpl in enumerate(tpls):
            clip, at, full = tiles[f"{name}--{tpl}"]
            frame = OUT / "cache" / f"{name}--{tpl}.png"
            label = f"{name} · {tpl}"
            draw = (f"scale=640:360,drawtext=fontfile='{font}':text='{label}':x=12:y=h-38:fontsize=22:"
                    "fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=7")
            if full:
                ffmpeg(["-c:v", "libvpx-vp9", "-ss", f"{at}", "-i", clip, "-frames:v", "1", "-vf", draw, frame])
            else:
                ffmpeg(["-i", bg, "-c:v", "libvpx-vp9", "-ss", f"{at}", "-i", clip, "-filter_complex",
                        f"[0][1]overlay,{draw}", "-frames:v", "1", frame])
            frames.append(frame)
        cap = OUT / "cache" / f"{name}--captions.png"
        caption_tile(name, bg, cap, (f"scale=640:360,drawtext=fontfile='{font}':text='{name} · captions':x=12:y=h-38:"
                                     "fontsize=22:fontcolor=white:box=1:boxcolor=black@0.65:boxborderw=7"))
        frames.append(cap)
        cols = 3 if len(frames) == 9 else min(4, len(frames))
        rows = (len(frames) + cols - 1) // cols
        seq = OUT / "cache" / f"seq-{name}-%02d.png"
        for i, f in enumerate(frames):
            (OUT / "cache" / f"seq-{name}-{i:02d}.png").write_bytes(f.read_bytes())
        sheet = OUT / f"{name}.png"
        ffmpeg(["-framerate", "1", "-i", seq, "-vf", f"tile={cols}x{rows}:padding=8:margin=8:color=0x1a1a1a",
                "-frames:v", "1", "-update", "1", sheet])
        log(f"Wrote {sheet}")
    if len(names) > 1:
        ins = []
        for n in names:
            ins += ["-i", OUT / f"{n}.png"]
        ffmpeg([*ins, "-filter_complex", "".join(f"[{i}]" for i in range(len(names))) + f"vstack=inputs={len(names)},scale=iw/2:-2",
                "-frames:v", "1", OUT / "all.png"])
        log(f"Wrote {OUT / 'all.png'}")


if __name__ == "__main__":
    main()
