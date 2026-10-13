"""Render the plan's motion graphics with HyperFrames (local Chrome + FFmpeg, no per-render cost).

    python graphics.py <slug> [--only id1,id2] [--force] [--jobs 3]

For each entry in plan.json "graphics" this fills a template from motion/templates (see
templates.json), applies the theme (plan.json "style" > brand.json "style": motion/themes/<name>.css
plus its palette, with brand.json "colors" overrides), and renders videos/<slug>/gfx/<id>.webm with alpha.
Renders are cached: an unchanged graphic is skipped. Set VP_CHROME to a Chrome path if the
bundled headless shell crashes on Windows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common import MOTION, ROOT, THEMES, Video, load_json, log, media_info, save_json, theme

CLI = MOTION / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
BUILD = MOTION / "build"
ENV = {"HYPERFRAMES_NO_TELEMETRY": "1", "HYPERFRAMES_SKIP_SKILLS": "1", "HYPERFRAMES_NO_UPDATE_CHECK": "1"}
IMAGE_PROPS = {"image"}


def declared_vars(html: str) -> dict:
    m = re.search(r"data-composition-variables='(.*?)'", html, re.S)
    return {d["id"]: d for d in json.loads(m.group(1))} if m else {}


def stage_image(src: str, slug: str) -> tuple[str, Path]:
    """Copy an image into motion/assets/<slug>/ and return its root-absolute URL.

    HyperFrames serves the project from motion/, so "/assets/..." resolves no matter where the
    composition HTML lives."""
    p = Path(src)
    if not p.is_absolute():
        p = (ROOT / p) if (ROOT / p).exists() else (Video(slug).dir / p)
    if not p.exists():
        raise SystemExit(f"Image not found: {src}")
    dest_dir = MOTION / "assets" / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / p.name
    if not dest.exists() or dest.stat().st_mtime < p.stat().st_mtime:
        shutil.copy2(p, dest)
    return f"/assets/{slug}/{p.name}", dest


def theme_css(name: str) -> str:
    """Everything that shapes a theme's look, for the render cache key."""
    return "".join((THEMES / f).read_text(encoding="utf-8") for f in ("base.css", "fx.js", f"{name}.css"))


def prepare(g: dict, slug: str, registry: dict, th: dict) -> tuple[Path, Path, str]:
    name = g["template"]
    if name not in registry or name.startswith("_"):
        raise SystemExit(f"Unknown template '{name}' in graphic '{g.get('id')}'. Options: "
                         + ", ".join(k for k in registry if not k.startswith("_")))
    meta = registry[name]
    dur = float(g.get("duration", meta["default_duration"]))
    html = (MOTION / "templates" / meta["file"]).read_text(encoding="utf-8")
    html = html.replace("<!--THEME-->", f'<link rel="stylesheet" href="../themes/{th["css"]}.css" />')
    colors = th["colors"]

    # Instance duration: rewrite data-duration on every element marked data-fill-duration.
    html = re.sub(r"<[^>]*\bdata-fill-duration\b[^>]*>",
                  lambda m: re.sub(r'data-duration="[^"]*"', f'data-duration="{dur:g}"', m.group(0)), html)

    declared = declared_vars(html)
    values = {f"c_{k}": val for k, val in colors.items() if f"c_{k}" in declared}  # palette, prefixed
    props = dict(g.get("props") or {})
    if "screen" in props and {"x", "y", "w", "h"} <= set(declared):
        # Place it on something in the recording: [x, y, w, h] in screen pixels (e.g. from the click log),
        # converted to the final frame at the moment the graphic appears (view + zoom included).
        from layout import screen_to_output
        vid, rect = Video(slug), props.pop("screen")
        at = float(g["start"]) + min(0.5, dur / 3)
        x, y, w, h = screen_to_output(vid, at, rect)
        props.update(x=x, y=y, w=w, h=h)
        # The graphic is fixed in the frame; if a zoom moves the page while it's up, it slides off its target.
        moved = lambda t: max(abs(a - b) for a, b in zip(screen_to_output(vid, t, rect), (x, y, w, h))) > 12  # noqa: E731
        end = float(g["start"]) + dur - 0.3
        if moved(end):
            t = end
            while t > at and moved(t):
                t -= 0.05
            log(f"  WARNING {g['id']}: a zoom moves the page under this {name} after {t:.2f}s — "
                f"set its duration to {max(t - float(g['start']) + 0.3, 0.8):.1f} (or start it later)")
    for k, val in props.items():
        if k not in declared:
            raise SystemExit(f"Graphic '{g['id']}': template '{name}' has no prop '{k}' (has: {', '.join(declared)})")
        if k == "items" and not isinstance(val, str):
            items = []
            for it in val:  # stage icon images referenced by tool-cards items
                it = dict(it)
                if it.get("icon"):
                    it["icon"], _ = stage_image(it["icon"], slug)
                items.append(it)
            val = json.dumps(items, ensure_ascii=False)
        if k in IMAGE_PROPS and val:
            val, staged = stage_image(val, slug)
            info = media_info(staged)
            html = html.replace(f'data-composition-id="{name}"',
                                f'data-composition-id="{name}" data-img-w="{info["width"]}" data-img-h="{info["height"]}"', 1)
        values[k] = val

    BUILD.mkdir(exist_ok=True)
    html_path = BUILD / f"{slug}--{g['id']}.html"
    vars_path = BUILD / f"{slug}--{g['id']}.vars.json"
    html_path.write_text(html, encoding="utf-8")
    save_json(vars_path, values)
    key = hashlib.sha256((html + json.dumps(values, sort_keys=True) + theme_css(th["css"])).encode()).hexdigest()[:16]
    return html_path, vars_path, key


def render(html_path: Path, vars_path: Path, out: Path, fps: int | None = None, quality: str = "standard") -> float:
    t0 = time.time()
    env = {**os.environ, **ENV}
    if os.environ.get("VP_CHROME"):
        env["HYPERFRAMES_BROWSER_PATH"] = os.environ["VP_CHROME"]
    cmd = ["node", str(CLI), "render", "--composition", f"build/{html_path.name}", "--format", "webm",
           "--quality", quality, "--variables-file", str(vars_path), "--output", str(out), "--quiet"]
    if fps:
        cmd += ["--fps", str(fps)]
    r = subprocess.run(cmd, cwd=MOTION, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not out.exists():
        tail = "\n".join((r.stderr + r.stdout).strip().splitlines()[-20:])
        raise RuntimeError(f"HyperFrames render failed for {html_path.name}:\n{tail}")
    return time.time() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--only", help="comma-separated graphic ids")
    ap.add_argument("--force", action="store_true", help="re-render even if unchanged")
    ap.add_argument("--jobs", type=int, default=3, help="parallel renders")
    a = ap.parse_args()

    v = Video(a.slug)
    plan = v.plan()
    graphics = plan.get("graphics", [])
    if a.only:
        wanted = set(a.only.split(","))
        graphics = [g for g in graphics if g["id"] in wanted]
    if not graphics:
        log("No graphics in plan.json.")
        return
    ids = [g["id"] for g in plan.get("graphics", [])]
    if len(ids) != len(set(ids)):
        raise SystemExit("Graphic ids in plan.json must be unique")

    registry = load_json(MOTION / "templates" / "templates.json")
    th = theme(plan.get("style"))
    log(f"Theme: {th['name']} — {th['description']}")
    v.gfx.mkdir(exist_ok=True)
    jobs = []
    for g in graphics:
        html_path, vars_path, key = prepare(g, a.slug, registry, th)
        out = v.gfx / f"{g['id']}.webm"
        key_file = v.gfx / f"{g['id']}.key"
        if not a.force and out.exists() and key_file.exists() and key_file.read_text() == key:
            log(f"  {g['id']}: unchanged, skipping")
            continue
        jobs.append((g["id"], html_path, vars_path, out, key_file, key))

    if not jobs:
        log("All graphics up to date.")
        return
    log(f"Rendering {len(jobs)} graphic(s) with HyperFrames ({a.jobs} at a time)...")
    failed = []
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        futs = {pool.submit(render, h, vp, o): (gid, o, kf, k) for gid, h, vp, o, kf, k in jobs}
        for f in as_completed(futs):
            gid, out, key_file, key = futs[f]
            try:
                secs = f.result()
                key_file.write_text(key)
                log(f"  {gid}: rendered in {secs:.0f}s -> gfx/{out.name}")
            except RuntimeError as e:
                failed.append(gid)
                log(f"  {gid}: FAILED\n{e}")
    if failed:
        raise SystemExit(f"{len(failed)} graphic(s) failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
