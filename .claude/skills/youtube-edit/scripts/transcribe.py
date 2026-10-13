"""Transcribe a video's recording locally with NVIDIA Parakeet (word-level timestamps).

    python transcribe.py <slug> [--model nvidia/parakeet-tdt-0.6b-v2] [--chunk 240]

Writes work/words.json   {"words": [{"w": "Hello", "s": 0.48, "e": 0.80}, ...], ...}
       work/transcript.txt  one sentence per line with times and word-index ranges, for reading.
Long recordings are split at pauses into ~4 min chunks so the 10 GB GPU never runs out of memory.
Use --model nvidia/parakeet-tdt-0.6b-v3 for non-English (25 European languages).
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

from common import Video, ffmpeg, fmt_time, log, run, save_json

SR = 16000


def find_silences(wav: Path) -> list[tuple[float, float]]:
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af",
             "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"], check=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(starts, ends))


def plan_chunks(duration: float, silences: list[tuple[float, float]], target: float) -> list[tuple[float, float]]:
    """Split [0, duration] near every `target` seconds, preferring the middle of a pause."""
    if duration <= target * 1.25:
        return [(0.0, duration)]
    mids = [(a + b) / 2 for a, b in silences]
    cuts, pos = [], 0.0
    while duration - pos > target * 1.25:
        want = pos + target
        cands = [m for m in mids if want - target * 0.25 <= m <= want + target * 0.25]
        cut = min(cands, key=lambda m: abs(m - want)) if cands else want
        cuts.append(cut)
        pos = cut
    edges = [0.0, *cuts, duration]
    return list(zip(edges[:-1], edges[1:]))


def transcribe_chunks(paths: list[Path], model_name: str) -> list:
    import logging
    import torch
    logging.getLogger("nemo_logger").setLevel(logging.ERROR)
    import nemo.collections.asr as nemo_asr
    from nemo.utils import logging as nemo_logging
    nemo_logging.setLevel(logging.ERROR)

    if not torch.cuda.is_available():
        log("WARNING: CUDA not available — transcribing on CPU (slow).")
    m = nemo_asr.models.ASRModel.from_pretrained(model_name)
    if torch.cuda.is_available():
        m = m.cuda()
    m.eval()
    with torch.inference_mode():
        out = m.transcribe([str(p) for p in paths], timestamps=True, batch_size=1, num_workers=0, verbose=False)
    if isinstance(out, tuple):  # some NeMo versions return (best_hyps, all_hyps)
        out = out[0]
    return out


def sentences(words: list[dict]) -> list[tuple[int, int]]:
    """Group word indices into sentence-ish lines: break on . ? ! or pauses longer than 1 s."""
    groups, start = [], 0
    for i, w in enumerate(words):
        last = i == len(words) - 1
        end_punct = w["w"].endswith((".", "?", "!"))
        long_pause = not last and words[i + 1]["s"] - w["e"] > 1.0
        too_long = i - start >= 40
        if last or end_punct or long_pause or too_long:
            groups.append((start, i))
            start = i + 1
    return groups


def write_transcript(words: list[dict], path: Path, title: str) -> None:
    lines = [f"# {title}", "# [line] start-end  text  (w<first>-<last> = word indices for cut commands)", ""]
    groups = sentences(words)
    for n, (a, b) in enumerate(groups):
        if n:
            gap = words[a]["s"] - words[groups[n - 1][1]]["e"]
            if gap >= 0.8:
                lines.append(f"      ... {gap:.1f}s pause")
        text = " ".join(w["w"] for w in words[a:b + 1])
        lines.append(f"[{n}] {fmt_time(words[a]['s'])}-{fmt_time(words[b]['e'])}  {text}  (w{a}-w{b})")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--model", default="nvidia/parakeet-tdt-0.6b-v2")
    ap.add_argument("--chunk", type=float, default=240.0, help="target chunk length in seconds")
    a = ap.parse_args()

    v = Video(a.slug)
    if not v.meta.get("has_audio"):
        raise SystemExit("The recording has no audio track to transcribe")
    v.work.mkdir(exist_ok=True)
    wav = v.path("audio16k.wav")
    log("Extracting 16 kHz mono audio...")
    # Track 1 only: in multi-track OBS recordings track 2 is computer sound, which must not be transcribed.
    ffmpeg(["-i", v.source, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", wav])
    duration = v.meta["duration"]

    chunks = plan_chunks(duration, find_silences(wav), a.chunk)
    chunk_dir = v.work / "chunks"
    chunk_dir.mkdir(exist_ok=True)
    paths = []
    for i, (s, e) in enumerate(chunks):
        p = chunk_dir / f"chunk{i:03d}.wav"
        ffmpeg(["-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", wav, "-c:a", "pcm_s16le", p])
        paths.append(p)
    log(f"Transcribing {fmt_time(duration)} in {len(paths)} chunk(s) with {a.model} ...")

    t0 = time.time()
    hyps = transcribe_chunks(paths, a.model)
    words = []
    for (offset, _), h in zip(chunks, hyps):
        for w in (h.timestamp or {}).get("word", []):
            text = str(w.get("word", "")).strip()
            if text:
                words.append({"w": text, "s": round(offset + float(w["start"]), 3),
                              "e": round(offset + float(w["end"]), 3)})
    for p in paths:
        p.unlink(missing_ok=True)

    save_json(v.path("words.json"), {
        "model": a.model, "duration": duration, "source": str(v.source),
        "text": " ".join(w["w"] for w in words), "words": words,
    })
    write_transcript(words, v.path("transcript.txt"), f"{a.slug} — raw recording")
    log(f"Done in {time.time() - t0:.1f}s: {len(words)} words -> work/words.json, work/transcript.txt")


if __name__ == "__main__":
    main()
