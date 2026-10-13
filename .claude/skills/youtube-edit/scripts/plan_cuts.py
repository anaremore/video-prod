"""Build and edit the cut list (what to remove from the raw recording).

    python plan_cuts.py <slug>                          # auto-detect pauses + filler words (keeps manual cuts)
    python plan_cuts.py <slug> --remove-words 23-41 --reason retake
    python plan_cuts.py <slug> --remove-range 12.4-15.0 --reason "off-topic"
    python plan_cuts.py <slug> --restore 7              # drop removal #7 from the list
    python plan_cuts.py <slug> --list                   # show removals and the resulting transcript

Writes work/cuts.json and work/cut_preview.txt (the transcript as it will sound after cutting).
Word indices come from work/transcript.txt (the (wA-wB) ranges). Removing a retake by word range
also removes the pause before it, so the good take joins the previous sentence naturally.
Pauses that contain on-screen activity (clicks from record.py) are never auto-cut.

The intro (first two sentences) and sign-off (last two) are the user's format and are KEPT: a manual
cut that touches them is refused unless it removes a flubbed retake inside them (--allow-ends).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import Video, brand, fmt_time, load_json, log, run, save_json
from transcribe import sentences

ENDS = 2  # sentences at the start (intro) and end (sign-off) that are protected


def strip_word(w: str) -> str:
    return "".join(ch for ch in w.lower() if ch.isalpha())


def merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def activity_log(v: Video) -> dict:
    if not v.meta.get("clicks") or not Path(v.meta["clicks"]).exists():
        return {}
    return load_json(Path(v.meta["clicks"]))


def desktop_sound(v: Video) -> list[tuple[float, float]]:
    """Spans where track 2 (computer sound) is audible — a demo video playing, an app's sounds."""
    if int(v.meta.get("audio_tracks", 1)) < 2:
        return []
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(v.source), "-map", "0:a:1",
             "-af", "silencedetect=noise=-45dB:d=0.4", "-f", "null", "-"], check=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    duration = float(v.meta["duration"])
    sound, pos = [], 0.0
    for s, e in zip(starts, ends + [duration] * (len(starts) - len(ends))):
        if s - pos > 0.2:
            sound.append((pos, s))
        pos = e
    if duration - pos > 0.2:
        sound.append((pos, duration))
    return sound


def cut_settings(style: str | None) -> dict:
    """brand.json cuts + the chosen style's numbers (gentle / tight / none)."""
    base = brand()["cuts"]
    name = style or base.get("style", "gentle")
    styles = base.get("styles", {})
    if styles and name not in styles:
        raise SystemExit(f"Unknown cut style '{name}' (brand.json cuts.styles: {', '.join(styles)})")
    cfg = {k: val for k, val in base.items() if k not in ("styles", "_note")}
    cfg.update(styles.get(name, {}))
    cfg["style"] = name
    return cfg


def cursor_motion(v: Video) -> list[float]:
    """Times the mouse was moving over the recorded window (the viewer is watching something happen)."""
    cur = activity_log(v).get("cursor", [])
    return [b[0] for a, b in zip(cur, cur[1:]) if abs(b[1] - a[1]) + abs(b[2] - a[2]) > 12 and b[0] - a[0] < 0.5]


def click_times(v: Video, cursor: bool = False) -> list[float]:
    """Moments of on-screen activity: clicks, typing, computer sound (and mouse movement), every 0.5 s."""
    data = activity_log(v)
    times = [c["t"] for c in data.get("clicks", [])] + (cursor_motion(v) if cursor else [])
    for s, e in [*data.get("typing", []), *desktop_sound(v)]:
        t = s
        while t <= e:
            times.append(t)
            t += 0.5
    return sorted(times)


def auto_removals(words: list[dict], duration: float, cfg: dict, clicks: list[float]) -> list[dict]:
    rem = []
    fillers = set(cfg["fillers"])
    pb, pa, gap_max = cfg["pad_before"], cfg["pad_after"], cfg["max_gap"]

    def has_activity(s: float, e: float) -> bool:
        return any(s <= t <= e for t in clicks)

    if not words:
        return [{"s": 0.0, "e": duration, "reason": "no speech", "auto": True}]
    # Leading / trailing dead air.
    if words[0]["s"] - pb > 0.3 and not has_activity(0, words[0]["s"]):
        rem.append({"s": 0.0, "e": round(words[0]["s"] - pb, 3), "reason": "silence", "auto": True})
    if duration - (words[-1]["e"] + pa) > 0.3 and not has_activity(words[-1]["e"], duration):
        rem.append({"s": round(words[-1]["e"] + pa, 3), "e": duration, "reason": "silence", "auto": True})
    # Pauses between words.
    for prev, nxt in zip(words, words[1:]):
        gap = nxt["s"] - prev["e"]
        if gap > gap_max:
            if has_activity(prev["e"], nxt["s"]):
                continue
            rem.append({"s": round(prev["e"] + pa, 3), "e": round(nxt["s"] - pb, 3), "reason": "silence", "auto": True})
    # Filler words ("um", "uh", ...), clipped so we never eat into neighbouring words.
    for i, w in enumerate(words):
        if cfg.get("remove_fillers", True) and strip_word(w["w"]) in fillers:
            lo = words[i - 1]["e"] + 0.02 if i else 0.0
            hi = words[i + 1]["s"] - 0.02 if i + 1 < len(words) else duration
            s, e = max(lo, w["s"] - 0.04), min(hi, w["e"] + 0.04)
            if e - s > 0.05:
                rem.append({"s": round(s, 3), "e": round(e, 3), "reason": "filler", "text": w["w"], "auto": True})
    # A cut shorter than min_cut isn't worth a visible jump (dead air at the very start/end always goes).
    min_cut = cfg.get("min_cut", 0.0)
    return [r for r in rem if r["e"] - r["s"] >= min_cut or r["s"] <= 0.0 or r["e"] >= duration]


def word_range_removal(words: list[dict], a: int, b: int, duration: float, cfg: dict) -> tuple[float, float]:
    if not (0 <= a <= b < len(words)):
        raise SystemExit(f"Word range w{a}-w{b} is outside 0..{len(words) - 1}")
    s = words[a - 1]["e"] + cfg["pad_after"] if a > 0 else 0.0
    e = words[b + 1]["s"] - cfg["pad_before"] if b + 1 < len(words) else duration
    s = min(s, words[a]["s"] - 0.02)
    e = max(e, words[b]["e"] + 0.02)
    return round(max(s, 0.0), 3), round(min(e, duration), 3)


def kept_words(words: list[dict], removed: list[tuple[float, float]]) -> list[int]:
    keep = []
    for i, w in enumerate(words):
        mid = (w["s"] + w["e"]) / 2
        if not any(s <= mid <= e for s, e in removed):
            keep.append(i)
    return keep


def protected(words: list[dict]) -> dict[str, list[int]]:
    """Word indices of the intro (first ENDS sentences) and sign-off (last ENDS sentences)."""
    lines = sentences(words) if words else []
    pick = lambda ls: [i for a, b in ls for i in range(a, b + 1)]  # noqa: E731
    return {"intro": pick(lines[:ENDS]), "sign-off": pick(lines[-ENDS:]) if len(lines) > ENDS else []}


def write_preview(v: Video, words: list[dict], cuts: dict, duration: float) -> str:
    removed = merge([(r["s"], r["e"]) for r in cuts["remove"]])
    cut_total = sum(e - s for s, e in removed)
    keep_idx = set(kept_words(words, removed))
    lines = [f"# Cut preview for {v.slug}: {fmt_time(duration)} -> {fmt_time(duration - cut_total)} "
             f"({cut_total:.1f}s removed in {len(removed)} cuts)", "", "## Removals"]
    for n, r in enumerate(cuts["remove"]):
        extra = f'  "{r["text"]}"' if r.get("text") else ""
        extra += f'  [{r["words"]}]' if r.get("words") else ""
        lines.append(f"#{n:<3} {fmt_time(r['s'])}-{fmt_time(r['e'])}  {r['e'] - r['s']:5.2f}s  {r['reason']}{extra}")
    markers = activity_log(v).get("markers", [])
    if markers:
        lines += ["", "## F9 retake markers from the recording (cut the flubbed take just before each)"]
        for mk in markers:
            before = [i for i, w in enumerate(words) if w["e"] <= mk["t"]]
            near = f"after w{before[-1]} \"{words[before[-1]]['w']}\"" if before else "before the first word"
            lines.append(f"  {fmt_time(mk['t'])}  {mk['type']}  ({near})")
    lines += ["", "## Intro and sign-off (kept by rule; only flubbed retakes inside them may go)"]
    for part, idx in protected(words).items():
        if idx:
            gone = [i for i in idx if i not in keep_idx]
            flag = f"  <-- {len(gone)} word(s) removed" if gone else ""
            lines.append(f"  {part}: w{idx[0]}-w{idx[-1]} \"{' '.join(words[i]['w'] for i in idx)[:90]}\"{flag}")
    lines += ["", "## Transcript after cuts ([removed words] in brackets)"]
    line, out = [], []
    for i, w in enumerate(words):
        line.append(w["w"] if i in keep_idx else f"[{w['w']}]")
        if w["w"].endswith((".", "?", "!")) or len(line) >= 24:
            out.append(" ".join(line))
            line = []
    if line:
        out.append(" ".join(line))
    lines += out
    text = "\n".join(lines) + "\n"
    v.path("cut_preview.txt").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--remove-words", metavar="A-B", help="remove words wA..wB (inclusive), e.g. a flubbed take")
    ap.add_argument("--remove-range", metavar="S-E", help="remove a time range in seconds, e.g. 12.4-15.0")
    ap.add_argument("--reason", default="manual")
    ap.add_argument("--restore", type=int, metavar="N", help="delete removal #N (see --list)")
    ap.add_argument("--list", action="store_true", help="just print the current removals and preview")
    ap.add_argument("--reset", action="store_true", help="discard manual removals and start over")
    ap.add_argument("--style", help="auto-cut style: gentle (default, few invisible cuts) | tight (jump cuts) | none")
    ap.add_argument("--allow-ends", action="store_true",
                    help="allow a manual cut inside the intro/sign-off — ONLY to remove a flubbed retake there")
    a = ap.parse_args()

    v = Video(a.slug)
    data = load_json(v.path("words.json"))
    words, duration = data["words"], float(data["duration"])
    path = v.path("cuts.json")
    prev = load_json(path, default={}) if path.exists() else {}
    cfg = cut_settings(a.style or prev.get("settings", {}).get("style"))
    cuts = load_json(path, default={"remove": []}) if path.exists() and not a.reset else {"remove": []}

    edited = a.remove_words or a.remove_range or a.restore is not None

    def guard(s: float, e: float) -> None:
        hit = {part: [i for i in idx if s <= (words[i]["s"] + words[i]["e"]) / 2 <= e]
               for part, idx in protected(words).items()}
        hit = {part: idx for part, idx in hit.items() if idx}
        if hit and not a.allow_ends:
            where = "; ".join(f"{part} w{idx[0]}-w{idx[-1]}" for part, idx in hit.items())
            raise SystemExit(f"Refused: this cut removes part of the {where}. The user keeps their intro and "
                             "sign-off. If it's a flubbed retake inside them, re-run with --allow-ends --reason retake.")

    if a.remove_words:
        lo, hi = (int(x.strip().lstrip("w")) for x in a.remove_words.split("-"))
        s, e = word_range_removal(words, lo, hi, duration, cfg)
        guard(s, e)
        cuts["remove"].append({"s": s, "e": e, "reason": a.reason, "words": f"w{lo}-w{hi}",
                               "text": " ".join(w["w"] for w in words[lo:hi + 1])[:80], "auto": False})
    if a.remove_range:
        s, e = (float(x) for x in a.remove_range.split("-"))
        guard(s, e)
        cuts["remove"].append({"s": round(s, 3), "e": round(e, 3), "reason": a.reason, "auto": False})
    if a.restore is not None:
        if not 0 <= a.restore < len(cuts["remove"]):
            raise SystemExit(f"No removal #{a.restore}")
        dropped = cuts["remove"].pop(a.restore)
        log(f"Restored #{a.restore}: {dropped['reason']} {fmt_time(dropped['s'])}-{fmt_time(dropped['e'])}")
    if not edited and not a.list:
        manual = [r for r in cuts["remove"] if not r.get("auto")]
        cuts["remove"] = auto_removals(words, duration, cfg, click_times(v, cfg.get("keep_cursor_motion", False))) + manual

    cuts["remove"].sort(key=lambda r: r["s"])
    cuts["settings"] = cfg
    cuts["duration"] = duration
    save_json(path, cuts)
    preview = write_preview(v, words, cuts, duration)
    log(preview.split("\n## Removals")[0].strip())
    auto_n = sum(1 for r in cuts["remove"] if r.get("auto"))
    log(f"Cut style '{cfg['style']}': {auto_n} automatic + {len(cuts['remove']) - auto_n} manual removals. "
        f"Review work/cut_preview.txt, then run cut.py.")


if __name__ == "__main__":
    main()
