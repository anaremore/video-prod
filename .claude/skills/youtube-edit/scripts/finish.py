"""Assemble the finished video: base picture + graphics + captions + mixed, loudness-normalized audio.

    python finish.py <slug> [--no-captions] [--preview]

Base picture is work/base.mp4 (ISO recordings, from layout.py) or work/flat.mp4. Audio is the cut
voice, cleaned up, with plan.json "music" ducked under speech and "sfx" hits, normalized to the
brand loudness target (YouTube plays at -14 LUFS). Writes final/<slug>.mp4 and, when plan.json
has chapters, final/chapters.txt ready to paste into the YouTube description.
--preview renders a fast low-res draft to final/<slug>-preview.mp4.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from common import (ASSETS, FONTS_TTF, MOTION, ROOT, Video, brand, ffmpeg, filter_path, fmt_time, load_json, log,
                    media_info, run, video_encoder_args, yt_time)


def resolve(p: str, v: Video) -> Path:
    path = Path(p)
    for cand in (path, ROOT / path, v.dir / path, ASSETS / "sfx" / path, ASSETS / "music" / path):
        if cand.exists():
            return cand.resolve()
    raise SystemExit(f"File not found: {p}")


def sfx_events(plan: dict, registry: dict) -> list[dict]:
    """Explicit plan["sfx"] plus graphics that ask for one with "sfx": "whoosh"."""
    events = [dict(e) for e in plan.get("sfx", [])]
    for g in plan.get("graphics", []):
        if g.get("sfx"):
            name = g["sfx"]
            events.append({"file": name if "." in name else f"{name}.wav", "at": float(g["start"]),
                           "volume_db": g.get("sfx_db")})
    return events


def mix_audio(v: Video, plan: dict, duration: float, registry: dict) -> Path:
    cfg = brand()["audio"]
    inputs = ["-i", v.path("flat_voice.wav")]
    parts = ["[0:a]highpass=f=70,acompressor=threshold=-21dB:ratio=3:attack=8:release=150:makeup=2,"
             f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f}[vox]"]
    n = 1

    music = plan.get("music", [])
    desk_file = v.path("flat_desktop.wav")
    desktop = desk_file.exists() and plan.get("desktop_audio", True) is not False
    # The voice keys the ducking of music and computer sound: one sidechain copy per bus that needs it.
    keys = (["[keym]"] if music else []) + (["[keyd]"] if desktop else [])
    if keys:
        parts.append(f"[vox]asplit={len(keys) + 1}[voxm]" + "".join(keys))
        buses = ["[voxm]"]
    else:
        buses = ["[vox]"]

    if desktop:  # track 2: computer sound, at its own level, dipping a little under speech
        db = plan.get("desktop_audio_db", cfg.get("desktop_db", -6))
        inputs += ["-i", desk_file]
        parts.append(f"[{n}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={db}dB,"
                     f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f}[desk]")
        parts.append("[desk][keyd]sidechaincompress=threshold=0.05:ratio=4:attack=20:release=300:makeup=1[deskd]")
        buses.append("[deskd]")
        n += 1

    if music:
        mus_labels = []
        for m in music:
            s = float(m.get("start", 0))
            e = float(m["end"]) if m.get("end") is not None else duration
            length = max(e - s, 0.5)
            fade_out = min(2.5, length / 3)
            db = m.get("volume_db", cfg["music_db"])
            inputs += ["-stream_loop", "-1", "-i", resolve(m["file"], v)]
            parts.append(f"[{n}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{length:.3f},"
                         f"afade=t=in:d={min(1.5, length / 3):.2f},afade=t=out:st={length - fade_out:.3f}:d={fade_out:.2f},"
                         f"volume={db}dB,adelay={int(s * 1000)}:all=1[m{n}]")
            mus_labels.append(f"[m{n}]")
            n += 1
        mixed = "".join(mus_labels)
        mbus = f"{mixed}amix=inputs={len(mus_labels)}:normalize=0," if len(mus_labels) > 1 else f"{mixed}"
        parts.append(f"{mbus}apad=whole_dur={duration:.3f},atrim=0:{duration:.3f}[mus]")
        parts.append(f"[mus][keym]sidechaincompress=threshold={cfg['music_duck_threshold']}:ratio={cfg['music_duck_ratio']}"
                     f":attack=25:release=450:makeup=1[ducked]")
        buses.append("[ducked]")

    for ev in sfx_events(plan, registry):
        db = ev.get("volume_db") if ev.get("volume_db") is not None else cfg["sfx_db"]
        inputs += ["-i", resolve(ev["file"], v)]
        parts.append(f"[{n}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={db}dB,"
                     f"adelay={int(float(ev['at']) * 1000)}:all=1[s{n}]")
        buses.append(f"[s{n}]")
        n += 1

    if len(buses) > 1:
        parts.append("".join(buses) + f"amix=inputs={len(buses)}:normalize=0:duration=first[mix]")
    else:
        parts.append(f"{buses[0]}anull[mix]")

    premix = v.path("premix.wav")
    script = v.path("mix_filter.txt")
    script.write_text(";\n".join(parts), encoding="utf-8")
    ffmpeg([*inputs, "-filter_complex_script", script, "-map", "[mix]", "-ar", "48000", "-c:a", "pcm_s24le", premix])

    # Two-pass loudness normalization (measure, then apply linearly).
    target = f"I={cfg['target_lufs']}:TP={cfg['true_peak']}:LRA=11"
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", premix, "-af", f"loudnorm={target}:print_format=json",
             "-f", "null", "-"])
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S).group(0))
    out = v.path("mix.wav")
    ffmpeg(["-i", premix, "-af",
            f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
            f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true",
            "-ar", "48000", "-c:a", "pcm_s24le", out])
    log(f"  audio: {m['input_i']} LUFS -> {cfg['target_lufs']} LUFS"
        + (f", {len(music)} music bed(s)" if music else "") + (", computer sound (track 2)" if desktop else "")
        + f", {len(buses) - 1 - bool(music) - bool(desktop)} sfx")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--preview", action="store_true", help="fast 960x540 draft")
    a = ap.parse_args()

    v = Video(a.slug)
    plan = v.plan()
    registry = load_json(MOTION / "templates" / "templates.json")
    flat, laid = v.path("flat.mp4"), v.path("base.mp4")
    if not flat.exists():
        raise SystemExit("Missing work/flat.mp4 — run cut.py first")
    if laid.exists() and laid.stat().st_mtime >= flat.stat().st_mtime:
        base = laid  # layout.py output (ISO framing and/or zooms)
    elif v.iso:
        raise SystemExit("ISO recording: run layout.py first (work/base.mp4 is missing or older than flat.mp4)")
    else:
        base = flat
    duration = media_info(base)["duration"]
    t0 = time.time()
    log(f"Finishing {a.slug} ({fmt_time(duration)}) ...")
    mix = mix_audio(v, plan, duration, registry)

    inputs = ["-i", base]
    parts, cur, n = [], "[0:v]", 1
    out_w, out_h = brand()["layout"]["output"]
    parts.append(f"{cur}scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                 f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[b0]")
    cur = "[b0]"
    for g in plan.get("graphics", []):
        clip = v.gfx / f"{g['id']}.webm"
        if not clip.exists():
            raise SystemExit(f"Missing graphic gfx/{clip.name} — run graphics.py")
        s = float(g["start"])
        d = media_info(clip)["duration"]
        inputs += ["-c:v", "libvpx-vp9", "-i", clip]
        parts.append(f"[{n}:v]setpts=PTS-STARTPTS+{s:.3f}/TB[g{n}]")
        parts.append(f"{cur}[g{n}]overlay=eof_action=pass:enable='between(t,{s:.3f},{s + d:.3f})'[b{n}]")
        cur = f"[b{n}]"
        n += 1

    want_caps = brand()["captions"]["enabled"] and plan.get("captions", True) and not a.no_captions
    if want_caps:
        caps = v.path("captions.ass")
        if not caps.exists():
            raise SystemExit("Missing work/captions.ass — run captions.py (or pass --no-captions)")
        parts.append(f"{cur}subtitles=filename='{filter_path(caps)}':fontsdir='{filter_path(FONTS_TTF)}'[cap]")
        cur = "[cap]"
    if a.preview:
        parts.append(f"{cur}scale=960:540[vout]")
    else:
        parts.append(f"{cur}null[vout]")

    script = v.path("finish_filter.txt")
    script.write_text(";\n".join(parts), encoding="utf-8")
    v.final.mkdir(exist_ok=True)
    out = v.final / (f"{a.slug}-preview.mp4" if a.preview else f"{a.slug}.mp4")
    enc = (["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p"] if a.preview
           else video_encoder_args("final"))
    ffmpeg([*inputs, "-i", mix, "-filter_complex_script", script, "-map", "[vout]", "-map", f"{n}:a",
            *enc, "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-t", f"{duration:.3f}", out])

    chapters = plan.get("chapters", [])
    if chapters and not a.preview:
        chapters = sorted(chapters, key=lambda c: float(c["start"]))
        lines = [f"{yt_time(float(c['start']))} {c['title']}" for c in chapters]
        problems = []
        if float(chapters[0]["start"]) != 0:
            problems.append("first chapter must start at 0:00")
        if len(chapters) < 3:
            problems.append("YouTube needs at least 3 chapters")
        for c1, c2 in zip(chapters, chapters[1:] + [{"start": duration}]):
            if float(c2["start"]) - float(c1["start"]) < 10:
                problems.append(f"'{c1['title']}' is shorter than 10 s")
        (v.final / "chapters.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log("  chapters -> final/chapters.txt" + (f"  (warning: {'; '.join(problems)})" if problems else ""))

    log(f"Done in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
