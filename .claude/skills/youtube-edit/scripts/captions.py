"""Build burned-in captions (ASS) from the flat-cut word timestamps.

    python captions.py <slug>

Writes work/captions.ass. Short chunks (a few words), the spoken word highlighted. The look comes from
the theme (plan.json "style" > brand.json "style"; motion/themes/themes.json "captions": font, colors,
outline or box, pop = the spoken word grows, glow = soft neon edge), and brand.json "captions" keys
override it. Captions are hidden under full-screen graphics and kinetic text and lifted above
lower thirds, using the graphics list in plan.json.
"""
from __future__ import annotations

import argparse
import re

from common import MOTION, Video, load_json, log, theme


def ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(t, 0.0)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def clean(word: str, upper: bool) -> str:
    w = re.sub(r"[.,;:]+$", "", word)  # keep ? and ! — they carry tone
    w = w.replace("{", "(").replace("}", ")")
    return w.upper() if upper else w


def chunk_words(words: list[dict], max_words: int, max_chars: int) -> list[list[dict]]:
    chunks, cur = [], []
    for i, w in enumerate(words):
        if cur:
            prev = cur[-1]
            text_len = len(" ".join(x["w"] for x in cur + [w]))
            if (len(cur) >= max_words or text_len > max_chars or w["s"] - prev["e"] > 0.6
                    or prev["w"].endswith((".", "?", "!")) or (prev["w"].endswith(",") and len(cur) >= 2)):
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def graphic_spans(plan: dict) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """(hidden spans under full-screen graphics, raised spans under bottom overlays)."""
    registry = load_json(MOTION / "templates" / "templates.json")
    hidden, raised = [], []
    for g in plan.get("graphics", []):
        meta = registry.get(g.get("template"), {})
        s = float(g["start"])
        e = s + float(g.get("duration", meta.get("default_duration", 3)))
        if meta.get("fullscreen") or meta.get("hide_captions"):
            hidden.append((s, e))
        elif meta.get("zone", "").startswith("bottom") or g.get("props", {}).get("position", "").startswith("bottom"):
            raised.append((s - 0.2, e + 0.2))
    return hidden, raised


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    a = ap.parse_args()

    v = Video(a.slug)
    cfg = theme(v.plan().get("style"))["captions"]
    words = load_json(v.path("flat_words.json"))["words"]
    hidden, raised = graphic_spans(v.plan())

    def in_any(t: float, spans) -> bool:
        return any(s <= t <= e for s, e in spans)

    # plan.json "corrections": {"FVig": "FFmpeg"} fixes misheard names (matched without punctuation/case).
    fixes = {k.lower(): val for k, val in v.plan().get("corrections", {}).items()}
    if fixes:
        for w in words:
            m = re.fullmatch(r"(\W*)(.*?)(\W*)", w["w"])
            if m and m.group(2).lower() in fixes:
                w["w"] = m.group(1) + fixes[m.group(2).lower()] + m.group(3)

    words = [w for w in words if not in_any((w["s"] + w["e"]) / 2, hidden)]
    chunks = chunk_words(words, cfg["max_words"], cfg["max_chars"])

    base, hi = ass_color(cfg["color"]), ass_color(cfg["highlight"])
    font = cfg["font"]
    # box: opaque box behind the text (BorderStyle 3; the box uses OutlineColour, Outline = padding)
    border_style, edge = (3, cfg.get("box_color", "#ffffff")) if cfg.get("box") else (1, cfg["outline"])
    lead = r"{\blur4}" if cfg.get("glow") else ""          # glow: soft blurred colored edge
    on, off = (r"{\fscx114\fscy114}", r"{\fscx100\fscy100}") if cfg.get("pop") else ("", "")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{cfg['size']},{base},{base},{ass_color(edge)},{ass_color('#000000', 0x60)},0,0,0,0,100,100,0,0,{border_style},{cfg['outline_px']},{cfg['shadow_px']},2,120,120,{cfg['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for n, ch in enumerate(chunks):
        start = ch[0]["s"]
        end = ch[-1]["e"] + 0.15
        if n + 1 < len(chunks):
            nxt = chunks[n + 1][0]["s"]
            end = nxt if nxt - end < 0.35 else min(end, nxt)
        margin = cfg["margin_v_raised"] if in_any(start, raised) else 0
        tokens = [clean(w["w"], cfg["uppercase"]) for w in ch]
        for k, w in enumerate(ch):
            ws = start if k == 0 else w["s"]
            we = end if k == len(ch) - 1 else ch[k + 1]["s"]
            if we - ws < 0.01:
                continue
            text = lead + " ".join(f"{{\\c{hi}}}{on}{t}{off}{{\\c{base}}}" if j == k else t for j, t in enumerate(tokens))
            events.append(f"Dialogue: 0,{ass_time(ws)},{ass_time(we)},Cap,,0,0,{margin},,{text}")

    v.path("captions.ass").write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    log(f"Wrote work/captions.ass ({cfg['font']}{', box' if cfg.get('box') else ''}{', pop' if cfg.get('pop') else ''}): "
        f"{len(chunks)} caption chunks, {len(events)} events "
        f"({len(hidden)} full-screen spans hidden, {len(raised)} lifted)")


if __name__ == "__main__":
    main()
