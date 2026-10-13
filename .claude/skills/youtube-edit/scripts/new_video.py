"""Create a working folder for one video.

    python new_video.py <slug> <recording.mp4> [--iso | --no-iso] [--clicks file.json]
    python new_video.py <slug> <screen.mp4> --cam <cam.mp4> [--cam-offset 1.25]   # split recording

Makes videos/<slug>/ with source/, work/, gfx/, research/, final/ and a video.json describing the
recording. The recording is hard-linked into source/ when it's on the same drive (no extra disk
space), otherwise referenced in place. ISO wide-canvas recordings (screen + camera in one frame,
see reference/recording.md) are detected by their canvas size from brand.json.

A separate camera file (e.g. filmed on a phone or camera while OBS recorded the screen) is passed
with --cam, or found automatically: a "* cam*" file next to the screen recording that finished
within 20 s of it. It is lined up with the screen by matching the audio in both files (offset +
clock drift); cut.py then stacks them into the same screen-over-camera layout as an ISO recording,
so every later step works the same.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
from pathlib import Path

from common import VIDEOS, brand, log, media_info, probe, save_json

CAM_CONFIDENCE_MIN = 8.0


def find_cam_file(screen: Path) -> Path | None:
    """A "* cam*" camera file next to the screen recording that finished within ~20 s of it."""
    best, best_gap = None, 20.0
    for p in screen.parent.iterdir():
        if p == screen or "cam" not in p.stem.lower() or p.suffix.lower() not in (".mp4", ".mov", ".mkv"):
            continue
        gap = abs(p.stat().st_mtime - screen.stat().st_mtime)
        if gap < best_gap:
            best, best_gap = p, gap
    return best


def link_into(src: Path, folder: Path) -> Path:
    dest = folder / src.name
    if not dest.exists():
        try:
            os.link(src, dest)
        except OSError:
            return src
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug", help="short folder name, e.g. 2026-10-claude-editing")
    ap.add_argument("source", type=Path, help="the recording")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--iso", action="store_true", help="force ISO wide-canvas mode")
    g.add_argument("--no-iso", action="store_true", help="treat as a normal single-view recording")
    ap.add_argument("--clicks", type=Path, help="cursor/click log from record.py (auto-detected next to the recording)")
    ap.add_argument("--cam", type=Path, help="separate camera recording (phone / camera), synced by audio")
    ap.add_argument("--no-cam", action="store_true", help="don't look for a separate camera file")
    ap.add_argument("--cam-offset", type=float, help="skip audio sync: camera starts this many seconds after the screen")
    ap.add_argument("--force", action="store_true", help="overwrite an existing video.json")
    a = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9._-]+", a.slug):
        raise SystemExit("slug may only contain letters, digits, '.', '_' and '-'")
    src = a.source.resolve()
    if not src.exists():
        raise SystemExit(f"Recording not found: {src}")

    d = VIDEOS / a.slug
    if (d / "video.json").exists() and not a.force:
        raise SystemExit(f"{d} already exists (use --force to re-create video.json)")
    for sub in ("source", "work", "gfx", "research", "final"):
        (d / sub).mkdir(parents=True, exist_ok=True)

    # Hard-link the recording into source/ when possible so the folder is self-contained.
    linked = link_into(src, d / "source")
    info = media_info(linked)
    audio_tracks = sum(1 for st in probe(linked)["streams"] if st["codec_type"] == "audio")
    if not info.get("has_video"):
        raise SystemExit("The recording has no video stream")

    rec = brand()["recording"]
    canvas = [info["width"], info["height"]]
    is_iso = a.iso or (not a.no_iso and canvas == list(rec["iso_canvas"]))
    iso = {"screen": rec["screen"], "cam": rec["cam"]} if is_iso else None

    cam_meta = None
    cam_file = None if (a.no_cam or is_iso) else (a.cam.resolve() if a.cam else find_cam_file(src))
    if cam_file:
        if not cam_file.exists():
            raise SystemExit(f"Camera file not found: {cam_file}")
        cam_linked = link_into(cam_file, d / "source")
        ci = media_info(cam_linked)
        if a.cam_offset is not None:
            sync = {"offset": a.cam_offset, "stretch": 1.0, "confidence": None, "manual": True}
        else:
            if not ci["has_audio"]:
                raise SystemExit("The camera file has no audio to sync with. Record sound on the camera too, "
                                 "or pass --cam-offset <seconds>.")
            from sync import measure
            log(f"Syncing camera {cam_file.name} to the screen recording by audio...")
            sync = measure(str(linked), str(cam_linked), info["duration"], ci["duration"])
            if sync["confidence"] < CAM_CONFIDENCE_MIN:
                raise SystemExit(f"Couldn't line up the camera by audio (confidence {sync['confidence']}). Check both "
                                 "files have the mic, or pass --cam-offset <seconds> (camera start minus screen start).")
        cam_w, cam_h = rec["cam"][2], rec["cam"][3]
        cam_meta = {"file": str(cam_linked), "width": ci["width"], "height": ci["height"], "fps": ci["fps"],
                    "duration": ci["duration"], **sync}
        # Same regions as an ISO recording: cut.py stacks screen over camera into this canvas.
        canvas_w = max(info["width"], cam_w)
        iso = {"screen": [0, 0, info["width"], info["height"]], "cam": [0, info["height"], cam_w, cam_h],
               "canvas": [canvas_w, info["height"] + cam_h], "split": True}

    clicks = a.clicks or next((p for p in (src.with_suffix(".clicks.json"), src.with_name(src.stem + "_clicks.json"))
                               if p.exists()), None)
    if clicks:
        shutil.copy2(clicks, d / "source" / "clicks.json")

    meta = {
        "slug": a.slug,
        "source": str(linked),
        "original": str(src),
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "duration": info["duration"],
        "width": info["width"],
        "height": info["height"],
        "fps": info["fps"],
        "has_audio": info["has_audio"],
        "audio_tracks": audio_tracks,  # OBS YouTube profile: 1 = your voice, 2 = computer sound
        "iso": iso,
        "cam": cam_meta,
        "clicks": str(d / "source" / "clicks.json") if clicks else None,
    }
    save_json(d / "video.json", meta)
    log(f"Created {d}")
    log(f"  {info['width']}x{info['height']} @ {info['fps']} fps, {info['duration']:.1f}s"
        + ("  [ISO wide canvas: screen + cam]" if iso and not cam_meta else ""))
    if audio_tracks > 1:
        log(f"  {audio_tracks} audio tracks: track 1 = voice (transcribed), track 2 = computer sound (mixed in finish)")
    if cam_meta:
        drift = (cam_meta["stretch"] - 1.0) * cam_meta["duration"] * 1000
        how = "manual offset" if cam_meta.get("manual") else f"audio sync, confidence {cam_meta['confidence']}"
        log(f"  + camera {Path(cam_meta['file']).name}: {cam_meta['width']}x{cam_meta['height']}, starts "
            f"{cam_meta['offset']:+.3f}s vs screen, drift {drift:+.0f} ms ({how})")
    if clicks:
        log(f"  click log: {clicks.name}")


if __name__ == "__main__":
    main()
