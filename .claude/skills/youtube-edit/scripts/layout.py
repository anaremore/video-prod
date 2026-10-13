"""Frame the flat cut into the 16:9 picture: camera / screen / screen + camera bubble, with smooth zooms.

    python layout.py <slug> [--preview]

This is the "screen editor" step (what Tella does): ISO recordings hold the full screen and the
camera in one wide frame (see reference/recording.md), and plan.json "layout" decides what the
viewer sees when. Normal recordings can use it too (mode "screen" only) to add zooms.

plan.json:
  "layout": {
    "segments": [ {"start": 0,   "mode": "cam"},
                  {"start": 6.2, "mode": "screen_cam", "view": "fit"},
                  {"start": 40,  "mode": "screen", "view": [1200, 200, 2240]} ],
    "zooms": "auto"   // from record.py clicks, or a list:
             // [ {"start": 12.0, "end": 15.5, "x": 1800, "y": 600, "scale": 2.0} ]
  }
view "fit" shows the whole screen (an ultrawide gets brand-colored bars); [x, y, w] is a 16:9 window
in screen pixels. Zoom x/y are screen pixels; scale is relative to the segment's view.
Writes work/base.mp4 (video only; finish.py adds audio).
"""
from __future__ import annotations

import argparse
import time

from common import Video, brand, ffmpeg, fmt_time, load_json, log, media_info, snap, theme, video_encoder_args

MODES = {"cam", "screen", "screen_cam"}


def even(n: float) -> int:
    return int(round(n / 2)) * 2


def canvas_geometry(sw: int, sh: int) -> tuple[int, int, int, int]:
    """Smallest 16:9 canvas containing the screen; returns (cw, ch, x0, y0) of the screen inside it."""
    if sw / sh >= 16 / 9:
        cw, ch = sw, even(sw * 9 / 16)
    else:
        cw, ch = even(sh * 16 / 9), sh
    return cw, ch, (cw - sw) // 2, (ch - sh) // 2


def clamp_window(cx: float, cy: float, w: float, cw: int, ch: int,
                 bounds: tuple[float, float, float, float] | None = None) -> tuple[float, float, float]:
    """Top-left x, y and width of a 16:9 window centred on (cx, cy), kept inside `bounds`
    (x, y, w, h — a segment's view, so zooms never reveal what the view framed out) or the canvas."""
    bx, by, bw, bh = bounds or (0.0, 0.0, float(cw), float(ch))
    w = min(max(w, 160.0), bw, bh * 16 / 9)
    h = w * 9 / 16
    x = min(max(cx - w / 2, bx), bx + bw - w)
    y = min(max(cy - h / 2, by), by + bh - h)
    return x, y, w


def auto_zooms(v: Video, scale: float) -> list[dict]:
    """Screen Studio-style zooms: cluster clicks that are close in time and space."""
    path = v.path("flat_clicks.json")
    if not path.exists():
        return []
    end = float(load_json(v.path("timeline.json"), default={}).get("duration", 1e9))
    # Ignore the last second: that click is almost always OBS's Stop button.
    clicks = sorted((c for c in load_json(path).get("clicks", []) if c["t"] < end - 1.0), key=lambda c: c["t"])
    zooms, cur = [], []
    for c in clicks:
        if cur and (c["t"] - cur[-1]["t"] > 2.5 or abs(c["x"] - cur[-1]["x"]) > 700 or abs(c["y"] - cur[-1]["y"]) > 500):
            zooms.append(cur)
            cur = []
        cur.append(c)
    if cur:
        zooms.append(cur)
    out = []
    for g in zooms:
        out.append({"start": max(g[0]["t"] - 0.5, 0), "end": g[-1]["t"] + 1.8,
                    "x": sum(c["x"] for c in g) / len(g), "y": sum(c["y"] for c in g) / len(g), "scale": scale})
    # Merge overlaps so windows never fight.
    merged = []
    for z in out:
        if merged and z["start"] < merged[-1]["end"]:
            m = merged[-1]
            m["end"] = max(m["end"], z["end"])
        else:
            merged.append(z)
    return merged


def smooth(u: str) -> str:
    return f"({u})*({u})*(3-2*({u}))"


def zoom_exprs(base: tuple[float, float, float], events: list[dict], fps: float, ease: float) -> dict:
    """perspective-filter corner expressions animating the window from base to each event's target."""
    bx, by, bw = base
    t = f"(in/{fps:g})"
    wx, wy, ww = [f"{bx:.2f}"], [f"{by:.2f}"], [f"{bw:.2f}"]
    for ev in events:
        s, e = ev["s"], ev["e"]
        r = min(ease, (e - s) / 2)
        a = f"clip(({t}-{s:.3f})/{r:.3f},0,1)"
        b = f"clip(({t}-{e - r:.3f})/{r:.3f},0,1)"
        wgt = f"({smooth(a)})*(1-{smooth(b)})"
        tx, ty, tw = ev["win"]
        wx.append(f"{wgt}*({tx - bx:.2f})")
        wy.append(f"{wgt}*({ty - by:.2f})")
        ww.append(f"{wgt}*({tw - bw:.2f})")
    X, Y, Wd = "+".join(wx), "+".join(wy), "+".join(ww)
    Hd = f"({Wd})*0.5625"
    return {"x0": X, "y0": Y, "x1": f"{X}+{Wd}", "y1": Y, "x2": X, "y2": f"{Y}+{Hd}",
            "x3": f"{X}+{Wd}", "y3": f"{Y}+{Hd}"}


def window_at(v: Video, t: float) -> dict:
    """Where the layout's 16:9 window sits at flat-cut time t — the same math as the perspective
    expressions main() renders. Returns {"mode", "x", "y", "w", "x0", "y0"}: window position/width in
    canvas pixels, plus the screen's offset inside the canvas. Used to place graphics on screen things."""
    lay_cfg = brand()["layout"]
    plan = v.plan().get("layout") or {}
    info = media_info(v.path("flat.mp4"))
    fps, total = v.fps, info["duration"]
    sw, sh = (v.iso["screen"][2], v.iso["screen"][3]) if v.iso else (info["width"], info["height"])
    cw, ch, x0, y0 = canvas_geometry(sw, sh)
    segs = sorted(plan.get("segments") or [{"start": 0, "mode": "screen_cam" if v.iso else "screen", "view": "fit"}],
                  key=lambda s: float(s["start"]))
    segs[0] = {**segs[0], "start": 0}
    zooms = plan.get("zooms", "auto")
    if zooms == "auto":
        zooms = auto_zooms(v, float(plan.get("zoom_scale", lay_cfg["default_zoom"])))
    i = max(k for k, sg in enumerate(segs) if float(sg["start"]) <= t + 1e-6)
    s = snap(float(segs[i]["start"]), fps)
    e = snap(float(segs[i + 1]["start"]), fps) if i + 1 < len(segs) else snap(total, fps)
    mode = segs[i].get("mode", "screen")
    if mode == "cam":
        return {"mode": "cam"}
    view = segs[i].get("view", "fit")
    if view == "fit":
        base = (0.0, 0.0, float(cw))
    else:
        vx, vy, vw = view
        base = clamp_window(vx + x0 + vw / 2, vy + y0 + vw * 9 / 32, vw, cw, ch)
    X, Y, W = base
    ease, tt = lay_cfg["zoom_ease_s"], t - s
    sm = lambda u: u * u * (3 - 2 * u)  # noqa: E731 — smoothstep, as in zoom_exprs
    for z in zooms or []:
        zs, ze = max(float(z["start"]), s), min(float(z["end"]), e)
        if ze - zs < 0.8:
            continue
        tx, ty, tw = clamp_window(float(z["x"]) + x0, float(z["y"]) + y0, base[2] / float(z.get("scale", 1.8)), cw, ch,
                                  bounds=(base[0], base[1], base[2], base[2] * 9 / 16))
        evs, eve = zs - s, ze - s
        r = min(ease, (eve - evs) / 2)
        wgt = sm(min(max((tt - evs) / r, 0), 1)) * (1 - sm(min(max((tt - (eve - r)) / r, 0), 1)))
        X, Y, W = X + wgt * (tx - base[0]), Y + wgt * (ty - base[1]), W + wgt * (tw - base[2])
    return {"mode": mode, "x": X, "y": Y, "w": W, "x0": x0, "y0": y0}


def screen_to_output(v: Video, t: float, rect: list[float]) -> list[int]:
    """[x, y, w, h] in recorded-screen pixels (e.g. a click from the click log) -> pixels in the final
    1920x1080 frame at flat time t, accounting for the segment's view and any zoom in progress."""
    win = window_at(v, t)
    if win["mode"] == "cam":
        raise SystemExit(f"At {t:.2f}s the layout shows the camera, so there's no screen to point at.")
    out_w = brand()["layout"]["output"][0]
    k = out_w / win["w"]
    x, y, w, h = rect
    return [round((x + win["x0"] - win["x"]) * k), round((y + win["y0"] - win["y"]) * k), round(w * k), round(h * k)]


def make_bubble_assets(v: Video, d: int, ring: int, ring_color: str) -> tuple:
    from PIL import Image, ImageDraw, ImageFilter
    ss = 4
    mask = Image.new("L", (d * ss, d * ss), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d * ss - 1, d * ss - 1), fill=255)
    mask = mask.resize((d, d), Image.LANCZOS)
    mask_path = v.path("bubble_mask.png")
    mask.save(mask_path)

    pad = ring + 24  # room for the ring and a soft shadow
    size = d + 2 * pad
    big = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    dr = ImageDraw.Draw(big)
    c = (pad - ring) * ss
    dr.ellipse((c, c + 10 * ss, size * ss - c, size * ss - c + 10 * ss), fill=(0, 0, 0, 120))
    big = big.filter(ImageFilter.GaussianBlur(10 * ss))
    dr = ImageDraw.Draw(big)
    rgb = tuple(int(ring_color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    dr.ellipse((c, c, size * ss - c - 1, size * ss - c - 1), outline=(*rgb, 255), width=ring * ss)
    # Punch out the centre so the camera shows through the ring layer.
    hole = Image.new("L", big.size, 0)
    ImageDraw.Draw(hole).ellipse((pad * ss, pad * ss, (pad + d) * ss - 1, (pad + d) * ss - 1), fill=255)
    big.putalpha(Image.composite(Image.new("L", big.size, 0), big.getchannel("A"), hole))
    ring_img = big.resize((size, size), Image.LANCZOS)
    ring_path = v.path("bubble_ring.png")
    ring_img.save(ring_path)
    return mask_path, ring_path, pad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--preview", action="store_true", help="render only the first 20 s, fast")
    a = ap.parse_args()

    v = Video(a.slug)
    b = brand()
    lay_cfg = b["layout"]
    colors = theme(v.plan().get("style"))["colors"]  # bars + bubble ring follow the graphics theme
    out_w, out_h = lay_cfg["output"]
    plan = v.plan().get("layout") or {}
    flat = v.path("flat.mp4")
    info = media_info(flat)
    fps, total = v.fps, info["duration"]
    if a.preview:
        total = min(total, 20.0)

    iso = v.iso
    if iso:
        sx, sy, sw, sh = iso["screen"]
        cx_, cy_, cw_, ch_ = iso["cam"]
    else:
        sx, sy, sw, sh = 0, 0, info["width"], info["height"]
    cw, ch, x0, y0 = canvas_geometry(sw, sh)

    segs = plan.get("segments") or [{"start": 0, "mode": "screen_cam" if iso else "screen", "view": "fit"}]
    segs = sorted(segs, key=lambda s: float(s["start"]))
    segs[0] = {**segs[0], "start": 0}
    zooms = plan.get("zooms", "auto")
    if zooms == "auto":
        zooms = auto_zooms(v, float(plan.get("zoom_scale", lay_cfg["default_zoom"])))
    bubble = lay_cfg["cam_bubble"]
    # Camera framing, in camera-region pixels: cam_crop = [x, y, w] (16:9 window for "cam" mode),
    # bubble_crop = [x, y, size] (square for the bubble). null = whole frame / centre square.
    # A named camera preset from brand.json (e.g. "avatar", "webcam") supplies defaults; the plan can override.
    preset = lay_cfg.get("cameras", {}).get(plan.get("camera", ""), {})
    if plan.get("camera") and not preset:
        raise SystemExit(f"Unknown camera preset '{plan['camera']}' (brand.json layout.cameras: "
                         f"{', '.join(lay_cfg.get('cameras', {}))})")
    cam_crop = plan.get("cam_crop", preset.get("cam_crop"))
    bubble_crop = plan.get("bubble_crop", preset.get("bubble_crop"))

    parts, labels = [], []
    n_segs, n_bub = 0, 0
    windows = []
    d, m = bubble["diameter"], bubble["margin"]
    bub_x = out_w - d - m if "right" in bubble["corner"] else m
    bub_y = out_h - d - m if "bottom" in bubble["corner"] else m
    for i, sg in enumerate(segs):
        s = snap(float(sg["start"]), fps)
        e = snap(float(segs[i + 1]["start"]), fps) if i + 1 < len(segs) else snap(total, fps)
        e = min(e, snap(total, fps))
        if e - s < 1 / fps:
            continue
        mode = sg.get("mode", "screen")
        if mode not in MODES:
            raise SystemExit(f"Unknown layout mode '{mode}' (use {', '.join(sorted(MODES))})")
        if mode != "screen" and not iso:
            raise SystemExit(f"Mode '{mode}' needs an ISO recording (screen + camera); this one is a single view")
        lbl = f"seg{n_segs}"
        parts.append(f"[src{n_segs}]trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS[{lbl}in]")

        if mode == "cam":
            if cam_crop:
                kx, ky, kw = cam_crop
                kw = min(kw, cw_, ch_ * 16 / 9)
                region = f"crop={even(kw)}:{even(kw * 9 / 16)}:{cx_ + int(kx)}:{cy_ + int(ky)}"
            else:
                region = f"crop={cw_}:{ch_}:{cx_}:{cy_}"
            parts.append(f"[{lbl}in]{region},scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
                         f"crop={out_w}:{out_h},setsar=1[{lbl}]")
        else:
            view = sg.get("view", "fit")
            if view == "fit":
                base = (0.0, 0.0, float(cw))
            else:
                vx, vy, vw = view
                base = clamp_window(vx + x0 + vw / 2, vy + y0 + vw * 9 / 32, vw, cw, ch)
            events = []
            for z in zooms or []:
                zs, ze = max(float(z["start"]), s), min(float(z["end"]), e)
                if ze - zs < 0.8:
                    continue
                win = clamp_window(float(z["x"]) + x0, float(z["y"]) + y0, base[2] / float(z.get("scale", 1.8)), cw, ch,
                                   bounds=(base[0], base[1], base[2], base[2] * 9 / 16))
                events.append({"s": zs - s, "e": ze - s, "win": win})
                windows.append((zs, ze))
            # Screen picture: crop the screen out of the canvas, pad to 16:9, then zoom/frame and scale.
            screen = f"crop={sw}:{sh}:{sx}:{sy}"
            if (cw, ch) != (sw, sh):
                screen += f",pad={cw}:{ch}:{x0}:{y0}:color={colors['bg']}"
            if events:
                ex = zoom_exprs(base, events, fps, lay_cfg["zoom_ease_s"])
                screen += ",perspective=" + ":".join(f"{k}='{val}'" for k, val in ex.items()) + ":interpolation=linear:eval=frame"
            elif base != (0.0, 0.0, float(cw)):
                bx, by, bw = base
                screen += f",crop={even(bw)}:{even(bw * 9 / 16)}:{int(bx)}:{int(by)}"
            screen += f",scale={out_w}:{out_h}:flags=lanczos,setsar=1"

            if mode == "screen":
                parts.append(f"[{lbl}in]{screen}[{lbl}]")
            else:  # screen_cam: screen plus a round camera bubble with a ring
                if bubble_crop:
                    bx_, by_, side = (int(n) for n in bubble_crop)
                    bx_, by_ = cx_ + bx_, cy_ + by_
                else:
                    side = min(cw_, ch_)
                    bx_, by_ = cx_ + (cw_ - side) // 2, cy_ + (ch_ - side) // 2
                parts.append(f"[{lbl}in]split=2[{lbl}a][{lbl}b]")
                parts.append(f"[{lbl}a]{screen}[{lbl}scr]")
                parts.append(f"[{lbl}b]crop={side}:{side}:{bx_}:{by_},"
                             f"scale={d}:{d},format=yuva420p[{lbl}cam0]")
                parts.append(f"[{lbl}cam0][mask{n_bub}]alphamerge=shortest=1[{lbl}cam]")
                parts.append(f"[{lbl}scr][{lbl}cam]overlay={bub_x}:{bub_y}:shortest=1[{lbl}o1]")
                parts.append(f"[{lbl}o1][ring{n_bub}]overlay={bub_x}-RINGPAD:{bub_y}-RINGPAD:shortest=1,format=yuv420p[{lbl}]")
                n_bub += 1
        labels.append(f"[{lbl}]")
        n_segs += 1

    head = [f"[0:v]split={n_segs}" + "".join(f"[src{i}]" for i in range(n_segs))]
    inputs = ["-i", flat]
    if n_bub:
        ring = bubble.get("ring_color") or "accent"
        ring = colors["accent"] if ring == "accent" else ring
        mask_path, ring_path, ringpad = make_bubble_assets(v, d, bubble["ring_px"], ring)
        still = ["-loop", "1", "-framerate", f"{fps:g}", "-t", f"{total:.3f}"]
        inputs += [*still, "-i", mask_path, *still, "-i", ring_path]
        head.append(f"[1:v]format=gray,split={n_bub}" + "".join(f"[mask{i}]" for i in range(n_bub)))
        head.append(f"[2:v]format=rgba,split={n_bub}" + "".join(f"[ring{i}]" for i in range(n_bub)))
        parts = [p.replace("RINGPAD", str(ringpad)) for p in parts]
    graph = head + parts + ["".join(labels) + f"concat=n={n_segs}:v=1:a=0,format=yuv420p[vout]"]

    script = v.path("layout_filter.txt")
    script.write_text(";\n".join(graph), encoding="utf-8")
    out = v.path("base-preview.mp4" if a.preview else "base.mp4")
    t0 = time.time()
    log(f"Laying out {fmt_time(total)}: {n_segs} segment(s), {len(windows)} zoom(s) ...")
    ffmpeg([*inputs, "-filter_complex_script", script, "-map", "[vout]", "-r", f"{fps:g}", "-t", f"{total:.3f}",
            *video_encoder_args("intermediate"), "-an", out])
    got = media_info(out)["duration"]
    log(f"Wrote work/{out.name} ({got:.2f}s) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
