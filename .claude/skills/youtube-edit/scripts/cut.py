"""Render the flat cut: the raw recording minus everything in work/cuts.json.

    python cut.py <slug>

Outputs (all on the new, cut timeline):
  work/flat.mp4              the cut video (still wide for ISO recordings; layout.py frames it)
  work/flat_voice.wav        the cut audio, lossless, for finishing
  work/flat_words.json       word timestamps remapped to the cut
  work/flat_transcript.txt   readable transcript with times on the cut timeline — use this for the edit plan
  work/flat_clicks.json      click/cursor log remapped (if the recording has one)
  work/timeline.json         the source->cut mapping
Cuts land exactly on frame boundaries and get 8 ms audio fades, so sync holds and edits don't click.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from common import Video, ffmpeg, fmt_time, load_json, log, media_info, save_json, snap, video_encoder_args
from plan_cuts import merge
from transcribe import write_transcript

FADE = 0.008


def keep_segments(cuts: dict, words: list[dict], duration: float, fps: float, min_keep: float) -> list[tuple[float, float]]:
    removed = merge([(max(0.0, r["s"]), min(duration, r["e"])) for r in cuts["remove"] if r["e"] > r["s"]])
    keeps, pos = [], 0.0
    for s, e in removed:
        if s > pos:
            keeps.append((pos, s))
        pos = max(pos, e)
    if pos < duration:
        keeps.append((pos, duration))

    last_frame = snap(duration, fps)
    snapped = []
    for s, e in keeps:
        s, e = snap(s, fps), min(snap(e, fps), last_frame)
        if e - s < 1.5 / fps:
            continue
        has_word = any(s <= (w["s"] + w["e"]) / 2 <= e for w in words)
        if e - s < min_keep and not has_word:
            continue
        # Merge with the previous keep when the cut between them is under 2 frames (not worth a jump).
        if snapped and s - snapped[-1][1] < 2 / fps:
            snapped[-1] = (snapped[-1][0], e)
        else:
            snapped.append((s, e))
    return snapped


def remap(t: float, segs: list[dict]) -> float | None:
    for g in segs:
        if g["src_s"] <= t <= g["src_e"]:
            return round(g["dst_s"] + (t - g["src_s"]), 3)
    return None


def stack_filter(v: Video) -> str:
    """Split recordings: put the separate camera file under the screen, in the ISO canvas layout.

    Camera timing comes from new_video's audio sync:  screen_time = cam_time * stretch + offset."""
    cam, iso, fps = v.meta["cam"], v.iso, v.fps
    canvas_w, _ = iso["canvas"]
    sw, sh = iso["screen"][2], iso["screen"][3]
    cw, ch = iso["cam"][2], iso["cam"][3]
    s, b = float(cam["stretch"]), float(cam["offset"])
    chain = f"[1:v]trim=start={-b / s:.6f}," if b < 0 else "[1:v]"     # camera started first: drop its head
    chain += (f"setpts=(PTS-STARTPTS)*{s:.7f},fps={fps:g},"
              f"scale={cw}:{ch}:force_original_aspect_ratio=decrease,pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2,setsar=1,")
    if b > 0:                                                          # camera started later: hold its first frame
        chain += f"tpad=start_duration={b:.6f}:start_mode=clone,"
    chain += f"tpad=stop=-1:stop_mode=clone,pad={canvas_w}:{ch}:0:0,format=yuv420p[camrow]"
    screen = f"[0:v]pad={canvas_w}:{sh}:0:0,format=yuv420p[scrrow]" if sw < canvas_w else "[0:v]format=yuv420p[scrrow]"
    return ";\n".join([screen, chain, "[scrrow][camrow]vstack=shortest=1[wide]"])


def build_filter(keeps: list[tuple[float, float]], video_in: str = "[0:v]", prefix: str = "",
                 desktop: bool = False) -> str:
    """Trim + concat every keep. Track 1 (voice) -> [a]; with desktop=True track 2 (computer sound) -> [a2]."""
    n = len(keeps)
    tracks = [("a", "[0:a:0]")] + ([("d", "[0:a:1]")] if desktop else [])
    parts = ([prefix] if prefix else []) + [f"{video_in}split={n}" + "".join(f"[v{i}]" for i in range(n))]
    for tag, src in tracks:
        parts.append(f"{src}asplit={n}" + "".join(f"[{tag}{i}]" for i in range(n)))
    for i, (s, e) in enumerate(keeps):
        d = e - s
        parts.append(f"[v{i}]trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS[vt{i}]")
        for tag, _ in tracks:
            parts.append(f"[{tag}{i}]atrim=start={s:.6f}:end={e:.6f},asetpts=PTS-STARTPTS,"
                         f"afade=t=in:d={FADE},afade=t=out:st={max(d - FADE, 0):.6f}:d={FADE}[{tag}t{i}]")
    seg = "".join(f"[vt{i}]" + "".join(f"[{tag}t{i}]" for tag, _ in tracks) for i in range(n))
    outs = "[v][a][a2]" if desktop else "[v][a]"
    parts.append(f"{seg}concat=n={n}:v=1:a={len(tracks)}{outs}")
    return ";\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    a = ap.parse_args()

    v = Video(a.slug)
    words = load_json(v.path("words.json"))["words"]
    cuts = load_json(v.path("cuts.json"))
    fps, duration = v.fps, float(v.meta["duration"])
    keeps = keep_segments(cuts, words, duration, fps, cuts.get("settings", {}).get("min_keep", 0.25))
    if not keeps:
        raise SystemExit("Nothing left to keep — check work/cuts.json")

    segs, pos = [], 0.0
    for s, e in keeps:
        segs.append({"src_s": s, "src_e": e, "dst_s": round(pos, 6)})
        pos += e - s
    total = pos

    script = v.path("cut_filter.txt")
    inputs = ["-i", v.source]
    desktop = int(v.meta.get("audio_tracks", 1)) >= 2
    if v.meta.get("cam"):
        inputs += ["-i", v.meta["cam"]["file"]]
        script.write_text(build_filter(keeps, "[wide]", stack_filter(v), desktop), encoding="utf-8")
        log("Stacking the separate camera under the screen (synced) ...")
    else:
        script.write_text(build_filter(keeps, desktop=desktop), encoding="utf-8")
    out = v.path("flat.mp4")
    log(f"Cutting {fmt_time(duration)} -> {fmt_time(total)} ({len(keeps)} segments) ...")
    t0 = time.time()
    desk_out = (["-map", "[a2]", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s24le", v.path("flat_desktop.wav")]
                if desktop else [])
    ffmpeg([*inputs, "-filter_complex_script", script, "-map", "[v]", "-map", "[a]",
            "-r", f"{fps:g}", *video_encoder_args("intermediate"), "-c:a", "aac", "-b:a", "256k",
            "-movflags", "+faststart", out, *desk_out])
    ffmpeg(["-i", out, "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s24le", v.path("flat_voice.wav")])
    if desktop:
        log("  track 2 (computer sound) -> work/flat_desktop.wav")
    else:
        v.path("flat_desktop.wav").unlink(missing_ok=True)
    got = media_info(out)["duration"]
    log(f"Rendered work/flat.mp4 in {time.time() - t0:.1f}s ({got:.2f}s; expected {total:.2f}s)")

    # Remap words onto the cut timeline.
    flat_words = []
    for w in words:
        mid = (w["s"] + w["e"]) / 2
        for g in segs:
            if g["src_s"] <= mid <= g["src_e"]:
                s = g["dst_s"] + max(w["s"], g["src_s"]) - g["src_s"]
                e = g["dst_s"] + min(w["e"], g["src_e"]) - g["src_s"]
                flat_words.append({"w": w["w"], "s": round(s, 3), "e": round(e, 3)})
                break
    save_json(v.path("flat_words.json"), {"duration": round(total, 3), "words": flat_words})
    write_transcript(flat_words, v.path("flat_transcript.txt"), f"{a.slug} — flat cut (edit-plan timeline)")
    save_json(v.path("timeline.json"), {"fps": fps, "duration": round(total, 3), "segments": segs})

    if v.meta.get("clicks") and Path(v.meta["clicks"]).exists():
        log_data = load_json(Path(v.meta["clicks"]))
        flat = {"screen": log_data.get("screen"), "clicks": [], "cursor": []}
        for c in log_data.get("clicks", []):
            t = remap(c["t"], segs)
            if t is not None:
                flat["clicks"].append({**c, "t": t})
        for c in log_data.get("cursor", []):
            t = remap(c[0], segs)
            if t is not None:
                flat["cursor"].append([t, *c[1:]])
        save_json(v.path("flat_clicks.json"), flat)
        log(f"Remapped {len(flat['clicks'])} clicks -> work/flat_clicks.json")
    log("Next: read work/flat_transcript.txt and write plan.json (see reference/edit-plan.md).")


if __name__ == "__main__":
    main()
