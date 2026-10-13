"""Synthesize a starter set of transition sound effects with FFmpeg (free, no downloads).

    python make_sfx.py [--force]

Writes assets/sfx/whoosh.wav, swoosh-short.wav, pop.wav, click.wav, riser.wav. Swap in your own
(e.g. from freesound.org, CC0) with the same names, or add new ones and reference them by file name.
"""
from __future__ import annotations

import argparse

from common import ASSETS, ffmpeg, log

SFX = {
    # Filtered noise with a swelling envelope and a moving phaser: an air "whoosh".
    "whoosh": ("anoisesrc=d=0.75:c=pink:a=0.9,highpass=f=300,lowpass=f=5500,"
               "volume='pow(sin(PI*t/0.75),2)':eval=frame,aphaser=in_gain=0.6:out_gain=0.9:delay=2.5:decay=0.6:speed=1.8,"
               "aformat=channel_layouts=stereo,aecho=0.7:0.5:18:0.25"),
    "swoosh-short": ("anoisesrc=d=0.35:c=white:a=0.7,highpass=f=900,lowpass=f=8000,"
                     "volume='pow(sin(PI*t/0.35),3)':eval=frame,aformat=channel_layouts=stereo"),
    "pop": ("aevalsrc='0.8*sin(2*PI*(520*t+1400*t*t))*exp(-28*t)':d=0.18:s=48000,"
            "lowpass=f=4000,aformat=channel_layouts=stereo"),
    "click": ("aevalsrc='0.7*sin(2*PI*2200*t)*exp(-90*t)+0.3*sin(2*PI*1100*t)*exp(-60*t)':d=0.08:s=48000,"
              "aformat=channel_layouts=stereo"),
    "riser": ("aevalsrc='0.35*sin(2*PI*(180*t+260*t*t))*(t/1.6)':d=1.6:s=48000,"
              "aformat=channel_layouts=stereo,aecho=0.8:0.6:60:0.3,afade=t=out:st=1.45:d=0.15"),
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    out_dir = ASSETS / "sfx"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, graph in SFX.items():
        out = out_dir / f"{name}.wav"
        if out.exists() and not a.force:
            log(f"  {name}.wav exists, skipping")
            continue
        ffmpeg(["-f", "lavfi", "-i", graph, "-ar", "48000", "-af", "loudnorm=I=-16:TP=-1.5", "-c:a", "pcm_s16le", out])
        log(f"  wrote assets/sfx/{name}.wav")


if __name__ == "__main__":
    main()
