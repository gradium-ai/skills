#!/usr/bin/env python3
"""Grade a Pruna avatar render: build frame montages a human (or agent
with vision) must inspect before the video ships.

Produces <prefix>_sweep.png (8 frames evenly spaced — catches blinks,
gaze drift, hallucinated text) and <prefix>_mouth.png (frames at speech
midpoints — mouth must be visibly articulating).

Usage:
  python grade_render.py out.mp4 report            # even mouth sampling
  python grade_render.py out.mp4 report whisper.json   # word-timed sampling
        (whisper.json = `python3 -m whisper AUDIO --word_timestamps True
         --output_format json`; midpoints of real words beat guessing)

Requires ffmpeg/ffprobe on PATH.
"""
import json
import os
import subprocess
import sys


def frames(video, times, vf, prefix):
    files = []
    for i, t in enumerate(times):
        f = f"{prefix}_{i}.png"
        subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", f"{t:.2f}", "-i", video,
                        "-frames:v", "1", "-vf", vf, f], check=True)
        files.append(f)
    out = f"{prefix}.png"
    n = len(files)
    subprocess.run(["ffmpeg", "-v", "quiet", "-y"] + sum((["-i", f] for f in files), [])
                   + ["-filter_complex", "".join(f"[{i}]" for i in range(n)) + f"hstack={n}", out],
                   check=True)
    for f in files:
        os.remove(f)
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    video, prefix = sys.argv[1], sys.argv[2]
    whisper_json = sys.argv[3] if len(sys.argv) > 3 else None
    dur = float(subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                                "-of", "csv=p=0", video], capture_output=True, text=True).stdout)

    sweep = frames(video, [dur * (i + 0.5) / 8 for i in range(8)],
                   "scale=180:-1", f"{prefix}_sweep")

    if whisper_json:
        with open(whisper_json) as fh:
            d = json.load(fh)
        words = [w for s in d["segments"] for w in s.get("words", [])]
        picks = words[2::max(1, len(words) // 6)][:6]
        times = [(w["start"] + w["end"]) / 2 for w in picks]
        label = [w["word"].strip() for w in picks]
    else:
        times = [dur * (i + 0.5) / 6 for i in range(6)]
        label = [f"{t:.1f}s" for t in times]
    mouth = frames(video, times, "scale=180:-1", f"{prefix}_mouth")

    print(f"{sweep}: eyes/artifacts — look for blinks, pupils, gaze drift, burned-in text")
    print(f"{mouth}: mouth at {label} — must be visibly articulating")
    print(f"duration: {dur:.2f}s (compare against the source audio)")


if __name__ == "__main__":
    main()
