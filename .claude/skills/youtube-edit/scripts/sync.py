"""Line up a separate camera file with the main (screen) recording by matching their audio.

    python sync.py <screen.mp4> <cam.mp4>      # print the measured offset / drift (new_video.py calls this)

Both files must contain the same room sound (each device's own mic is fine).
The offset is measured near the start and near the end, so clock drift between the two recordings
is measured too:  main_time = cam_time * stretch + offset.
"""
from __future__ import annotations

import subprocess
import sys

import numpy as np

SR = 4000  # 4 kHz is plenty for alignment (0.25 ms resolution) and keeps the FFTs small


def read_audio(path: str, start: float, dur: float) -> np.ndarray:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(start, 0):.3f}", "-t", f"{dur:.3f}",
           "-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def lag(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Seconds to add to b's timestamps to line it up with a, and a confidence score (peak / mean)."""
    if len(a) < SR or len(b) < SR:
        return 0.0, 0.0
    # Envelope-ish preprocessing: remove DC and normalise so loudness differences don't matter.
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    corr = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    corr = np.abs(corr)
    k = int(np.argmax(corr))
    if k > n // 2:
        k -= n
    conf = float(corr.max() / (corr.mean() + 1e-9))
    return k / SR, conf


def window_offset(main: str, cam: str, cam_start: float, w: float, main_start: float, main_len: float) -> tuple[float, float]:
    """Offset d (main_time = cam_time + d) measured with a cam window [cam_start, +w] searched in main."""
    main_start = max(main_start, 0.0)
    L, conf = lag(read_audio(main, main_start, main_len), read_audio(cam, cam_start, w))
    # lag(): main_local = cam_local + L, so main_time = main_start + (cam_time - cam_start) + L
    return main_start - cam_start + L, conf


def measure(main: str, cam: str, main_dur: float, cam_dur: float, window: float = 45.0, search: float = 15.0) -> dict:
    """Offset near the start and near the end of the cam file; their difference gives clock drift.

    Returns offset/stretch for  main_time = cam_time * stretch + offset.  The camera may start up to
    `search` seconds before or after the screen recording."""
    if cam_dur < 3 * window:  # short clip: one window over (nearly) the whole camera file, no drift estimate
        w = max(cam_dur - 0.4, 0.5)
        d, conf = window_offset(main, cam, 0.2, w, 0.2 - search, w + 2 * search)
        return {"offset": round(d, 4), "stretch": 1.0, "confidence": round(conf, 1),
                "offset_start": round(d, 4), "offset_end": round(d, 4)}
    w = min(window, cam_dur / 3)
    c0 = min(search, cam_dur / 4)                      # start window, a little into the cam file
    d0, conf0 = window_offset(main, cam, c0, w, c0 - search, w + 2 * search)
    c1 = max(cam_dur - w - 2.0, c0 + w)                # end window
    d1, conf1 = window_offset(main, cam, c1, w, c1 + d0 - 2.0, w + 4.0)  # drift is small: narrow search
    t0, t1 = c0 + w / 2, c1 + w / 2                    # window centres, in cam time
    if t1 - t0 > 60 and conf1 >= 8:
        stretch = ((t1 + d1) - (t0 + d0)) / (t1 - t0)
    else:
        stretch = 1.0
    offset = (t0 + d0) - stretch * t0
    return {"offset": round(offset, 4), "stretch": round(stretch, 7), "confidence": round(min(conf0, conf1), 1),
            "offset_start": round(d0, 4), "offset_end": round(d1, 4)}


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    from common import media_info
    main_f, cam_f = sys.argv[1], sys.argv[2]
    mi, ci = media_info(main_f), media_info(cam_f)
    if not ci["has_audio"]:
        sys.exit("The camera file has no audio, so it can't be synced by sound.")
    r = measure(main_f, cam_f, mi["duration"], ci["duration"])
    drift_ms = (r["stretch"] - 1.0) * ci["duration"] * 1000
    print(f"offset {r['offset']:+.3f}s (cam starts {'after' if r['offset'] > 0 else 'before'} the screen), "
          f"drift {drift_ms:+.0f} ms over {ci['duration']:.0f}s, confidence {r['confidence']}")


if __name__ == "__main__":
    main()
