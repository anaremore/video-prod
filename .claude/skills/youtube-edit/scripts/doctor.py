"""Check (and where possible fix) everything the youtube-edit pipeline needs.

    python doctor.py [--obs]

Fixes it can make itself: converts the brand fonts to TTF for captions, generates starter SFX.
--obs also checks that the OBS WebSocket server is reachable.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from common import ASSETS, FONTS_TTF, MOTION, ROOT, brand, obs_password, run

OK, WARN, BAD = "  ok ", " warn", " FAIL"
problems = 0


def report(level: str, what: str, detail: str = "") -> None:
    global problems
    if level == BAD:
        problems += 1
    print(f"[{level}] {what}" + (f" — {detail}" if detail else ""))


def check_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        return report(BAD, "ffmpeg", "not on PATH")
    filters = run(["ffmpeg", "-hide_banner", "-filters"]).stdout
    missing = [f for f in ("subtitles", "sidechaincompress", "loudnorm", "perspective", "alphamerge") if f" {f} " not in filters]
    decoders = run(["ffmpeg", "-hide_banner", "-decoders"]).stdout
    if "libvpx-vp9" not in decoders:
        missing.append("libvpx-vp9 decoder")
    report(BAD if missing else OK, "ffmpeg", ("missing: " + ", ".join(missing)) if missing else "all filters present")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1",
                        "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True)
    report(OK if r.returncode == 0 else WARN, "NVENC", "GPU encoding available" if r.returncode == 0 else "falling back to libx264 (slower)")


def check_node() -> None:
    node = shutil.which("node")
    if not node:
        return report(BAD, "node", "Node.js 22+ required for HyperFrames")
    ver = run(["node", "--version"]).stdout.strip()
    major = int(ver.lstrip("v").split(".")[0])
    report(OK if major >= 22 else BAD, "node", ver)
    cli = MOTION / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    if cli.exists():
        hv = run(["node", str(cli), "--version"], env={"HYPERFRAMES_NO_UPDATE_CHECK": "1"}).stdout.strip()
        report(OK, "hyperframes", hv)
    else:
        report(BAD, "hyperframes", f"run: cd {MOTION} && npm install")


def check_python() -> None:
    report(OK, "python", sys.executable)
    try:
        import torch
        cuda = torch.cuda.is_available()
        report(OK if cuda else WARN, "torch", f"{torch.__version__}, CUDA {'yes: ' + torch.cuda.get_device_name(0) if cuda else 'NO (CPU only, slow)'}")
    except ImportError:
        report(BAD, "torch", "not installed in this Python — run setup.ps1 (or set VP_PYTHON)")
    try:
        import importlib.util
        if importlib.util.find_spec("nemo") is None:
            raise ImportError
        report(OK, "nemo_toolkit", "installed (Parakeet transcription)")
    except ImportError:
        report(BAD, "nemo_toolkit", 'pip install "nemo_toolkit[asr]"')
    for mod, why in (("PIL", "camera bubble masks"), ("obsws_python", "OBS control"), ("pynput", "click logging")):
        try:
            __import__(mod)
            report(OK, mod)
        except ImportError:
            report(WARN, mod, f"needed for {why}")


def check_motion_assets() -> None:
    """GSAP and the fonts aren't committed (third-party files): copy them out of motion/node_modules."""
    import re
    nm = MOTION / "node_modules"
    if not nm.exists():
        return report(BAD, "motion assets", f"run: cd {MOTION} && npm ci")
    (MOTION / "vendor").mkdir(exist_ok=True)
    gsap = MOTION / "vendor" / "gsap.min.js"
    if not gsap.exists() and (nm / "gsap" / "dist" / "gsap.min.js").exists():
        shutil.copy2(nm / "gsap" / "dist" / "gsap.min.js", gsap)
    wanted = re.findall(r'url\("([^"]+\.woff2)"\)', (MOTION / "fonts" / "fonts.css").read_text(encoding="utf-8"))
    missing = []
    for name in wanted:
        dest = MOTION / "fonts" / name
        if dest.exists():
            continue
        src = next(iter(nm.glob(f"@fontsource/*/files/{name}")), None)
        if src:
            shutil.copy2(src, dest)
        else:
            missing.append(name)
    ok = gsap.exists() and not missing
    report(OK if ok else BAD, "motion assets", "GSAP + fonts in place" if ok else f"missing: {', '.join(missing) or 'gsap'}")


def check_fonts() -> None:
    FONTS_TTF.mkdir(parents=True, exist_ok=True)
    woffs = sorted((MOTION / "fonts").glob("*.woff2"))
    missing = [w for w in woffs if not (FONTS_TTF / (w.stem + ".ttf")).exists()]
    if missing:
        try:
            from fontTools.ttLib import TTFont
            for w in missing:
                f = TTFont(str(w))
                f.flavor = None
                f.save(str(FONTS_TTF / (w.stem + ".ttf")))
        except ImportError:
            return report(BAD, "caption fonts", "pip install fonttools brotli (to convert the brand fonts to TTF)")
    report(OK, "caption fonts", f"{len(list(FONTS_TTF.glob('*.ttf')))} TTF files in motion/fonts/ttf")


def check_assets() -> None:
    try:
        b = brand()
        report(OK, "brand.json", f"channel '{b.get('channel')}'")
        if b.get("creator") == "Your Name":
            report(WARN, "brand.json", "placeholder name — copy brand/brand.example.json to brand/brand.json and edit it")
    except SystemExit as e:
        report(BAD, "brand.json", str(e))
    sfx = list((ASSETS / "sfx").glob("*.wav"))
    if not sfx:
        subprocess.run([sys.executable, str(ROOT / ".claude/skills/youtube-edit/scripts/make_sfx.py")], check=False)
        sfx = list((ASSETS / "sfx").glob("*.wav"))
    report(OK if sfx else WARN, "sfx", f"{len(sfx)} files")
    music = [p for p in (ASSETS / "music").glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg", ".flac")]
    report(OK if music else WARN, "music", f"{len(music)} tracks" if music else "assets/music is empty — see assets/music/README.md")


def check_obs() -> None:
    try:
        import obsws_python as obs
        cl = obs.ReqClient(host="localhost", port=4455, password=obs_password(), timeout=3)
        v = cl.get_video_settings()
        report(OK, "OBS websocket", f"connected; canvas {v.base_width}x{v.base_height}")
    except Exception as e:  # noqa: BLE001 — any failure here just means "not reachable"
        report(WARN, "OBS websocket", f"not reachable ({type(e).__name__}). Enable it in OBS > Tools > WebSocket Server Settings")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--obs", action="store_true")
    a = ap.parse_args()
    check_ffmpeg()
    check_node()
    check_python()
    check_motion_assets()
    check_fonts()
    check_assets()
    if a.obs:
        check_obs()
    print("\nAll good." if not problems else f"\n{problems} problem(s) to fix.")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
