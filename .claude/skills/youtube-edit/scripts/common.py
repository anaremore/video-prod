"""Shared helpers for the youtube-edit pipeline scripts (stdlib only)."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SCRIPTS = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS.parent


def _find_root() -> Path:
    env = os.environ.get("VIDEO_PROD_ROOT")
    if env:
        return Path(env).resolve()
    for p in [SKILL_DIR, *SKILL_DIR.parents]:
        if (p / "motion").is_dir() and (p / "brand").is_dir():
            return p
    sys.exit("Could not find the video-prod project root (a folder with motion/ and brand/). Set VIDEO_PROD_ROOT.")


ROOT = _find_root()
MOTION = ROOT / "motion"
BRAND_DIR = ROOT / "brand"
VIDEOS = ROOT / "videos"
ASSETS = ROOT / "assets"
FONTS_TTF = MOTION / "fonts" / "ttf"


# ---------------------------------------------------------------- io

def load_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        if default is not None:
            return default
        sys.exit(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- video folders

class Video:
    """A per-video working folder: videos/<slug>/{source,work,gfx,research,final}."""

    def __init__(self, slug: str):
        self.slug = slug
        self.dir = VIDEOS / slug
        if not (self.dir / "video.json").exists():
            sys.exit(f"No video named '{slug}'. Create it with new_video.py first. ({self.dir})")
        self.meta = load_json(self.dir / "video.json")
        self.work = self.dir / "work"
        self.gfx = self.dir / "gfx"
        self.research = self.dir / "research"
        self.final = self.dir / "final"

    @property
    def source(self) -> Path:
        return Path(self.meta["source"])

    @property
    def iso(self) -> dict | None:
        return self.meta.get("iso")

    @property
    def fps(self) -> float:
        return float(self.meta["fps"])

    def path(self, name: str) -> Path:
        return self.work / name

    @property
    def plan_path(self) -> Path:
        return self.dir / "plan.json"

    def plan(self) -> dict:
        return load_json(self.plan_path, default={})

    def save_meta(self) -> None:
        save_json(self.dir / "video.json", self.meta)


LOCAL = ROOT / "local"  # personal, gitignored: OBS state + backups, notes


def _merge(base: dict, over: dict) -> dict:
    """Deep-merge dicts: values in `over` win, nested dicts merge key by key."""
    out = dict(base)
    for k, val in over.items():
        out[k] = _merge(out[k], val) if isinstance(val, dict) and isinstance(out.get(k), dict) else val
    return out


def brand() -> dict:
    """brand/brand.default.json (shipped, generic) deep-merged with brand/brand.json (yours, gitignored)."""
    base = load_json(BRAND_DIR / "brand.default.json")
    mine = BRAND_DIR / "brand.json"
    return _merge(base, load_json(mine)) if mine.exists() else base


THEMES = MOTION / "themes"
CAPTION_DEFAULTS = {"enabled": True, "max_words": 4, "max_chars": 26, "margin_v": 110, "margin_v_raised": 330,
                    "uppercase": False, "box": False, "pop": False, "glow": False, "outline_px": 5, "shadow_px": 2}


def themes() -> dict:
    """Shipped themes (themes.json) plus your own brand/client themes (themes.local.json, gitignored)."""
    reg = load_json(THEMES / "themes.json")
    local = THEMES / "themes.local.json"
    if local.exists():
        reg = {**reg, **load_json(local)}
    return {k: val for k, val in reg.items() if not k.startswith("_")}


def theme(name: str | None = None) -> dict:
    """The graphics theme in effect: {name, description, colors, captions}.

    Order of precedence: plan.json "style" (pass it as name) > brand.json "style" > "glass".
    brand.json "colors" / "captions" entries override the theme's own values."""
    b = brand()
    reg = themes()
    name = name or b.get("style") or "glass"
    if name not in reg:
        sys.exit(f"Unknown style '{name}'. Themes: {', '.join(reg)} (motion/themes/themes.json)")
    t = reg[name]
    own = lambda d: {k: val for k, val in (d or {}).items() if not k.startswith("_")}  # noqa: E731
    colors = {**t["colors"], **own(b.get("colors"))}
    caps = {**CAPTION_DEFAULTS, **t.get("captions", {}), **own(b.get("captions"))}
    return {"name": name, "css": t.get("css", name), "description": t.get("description", ""), "colors": colors, "captions": caps}


# ---------------------------------------------------------------- processes

def run(cmd: list, *, quiet: bool = True, check: bool = True, env: dict | None = None,
        cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [str(c) for c in cmd]
    if not quiet:
        log("$ " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, **(env or {})}, cwd=cwd)
    if check and r.returncode != 0:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-25:])
        sys.exit(f"Command failed ({r.returncode}): {cmd[0]} ...\n{tail}")
    return r


def ffmpeg(args: list, **kw) -> subprocess.CompletedProcess:
    return run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], **kw)


def probe(path: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(r.stdout)


def media_info(path: Path) -> dict:
    """Duration, size, fps and stream presence for a media file."""
    p = probe(path)
    v = next((s for s in p["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in p["streams"] if s["codec_type"] == "audio"), None)
    info = {"duration": float(p["format"].get("duration", 0)), "has_audio": a is not None,
            "has_video": v is not None}
    if v:
        num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 30.0
        info.update(width=int(v["width"]), height=int(v["height"]), fps=round(fps, 3))
    return info


def video_encoder_args(quality: str = "final") -> list:
    """NVENC when available (NVIDIA GPUs), libx264 otherwise."""
    if _has_nvenc():
        cq = {"final": "19", "intermediate": "17"}[quality]
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", cq, "-b:v", "0",
                "-pix_fmt", "yuv420p"]
    crf = {"final": "18", "intermediate": "16"}[quality]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", crf, "-pix_fmt", "yuv420p"]


_NVENC = None


def _has_nvenc() -> bool:
    global _NVENC
    if _NVENC is None:
        if os.environ.get("VP_NO_NVENC"):
            _NVENC = False
        else:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                "color=s=256x256:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"],
                               capture_output=True)
            _NVENC = r.returncode == 0
    return _NVENC


# ---------------------------------------------------------------- time helpers

def snap(t: float, fps: float) -> float:
    """Round a time to the nearest frame boundary."""
    return round(t * fps) / fps


def fmt_time(t: float) -> str:
    t = max(t, 0.0)
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    return f"{h}:{m:02d}:{s:05.2f}" if h else f"{m:02d}:{s:05.2f}"


def yt_time(t: float) -> str:
    """YouTube chapter timestamp (m:ss or h:mm:ss)."""
    t = int(math.floor(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def filter_path(p: Path) -> str:
    """Escape a Windows path for use inside an FFmpeg filter argument (e.g. subtitles=...)."""
    s = str(Path(p).resolve()).replace("\\", "/")
    return s.replace(":", "\\:").replace("'", "\\'")


def obs_password() -> str:
    """OBS WebSocket password: $OBS_WS_PASSWORD, else read from OBS's own local config (never printed)."""
    if os.environ.get("OBS_WS_PASSWORD"):
        return os.environ["OBS_WS_PASSWORD"]
    cfg = Path(os.path.expandvars(r"%APPDATA%\obs-studio\plugin_config\obs-websocket\config.json"))
    if cfg.exists():
        data = json.loads(cfg.read_text(encoding="utf-8"))
        if not data.get("server_enabled"):
            sys.exit("OBS WebSocket server is off: OBS > Tools > WebSocket Server Settings > Enable, then Apply.")
        return data.get("server_password", "") if data.get("auth_required", True) else ""
    return ""


def which_or_exit(name: str) -> str:
    p = shutil.which(name)
    if not p:
        sys.exit(f"'{name}' not found on PATH")
    return p
