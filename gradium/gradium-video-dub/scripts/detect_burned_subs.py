#!/usr/bin/env python3
"""Find burned-in (white) subtitles in the lower part of the frame and make contact sheets.

Usage: detect_burned_subs.py <video> <workdir>
Writes band.json {y, h} (strip to cover) when subtitles are found, plus subs_sheet_N.png:
the strip every 0.5 s with a timestamp, so you can read the original captions and timing.
"""
import glob, json, os, subprocess, sys
import numpy as np

video, wd = sys.argv[1], sys.argv[2]
W, H = map(int, subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height", "-of", "csv=p=0", video], capture_output=True, text=True).stdout.strip().split(","))
y0 = int(H * 0.55); h0 = H - y0
# stream frames one at a time and count how often each pixel is near-pure white (subtitle text),
# so memory stays flat however long the video is
proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", video, "-vf", f"fps=4,crop={W}:{h0}:0:{y0}",
                         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
count, n, size = np.zeros((h0, W), np.int32), 0, h0 * W * 3
while len(buf := proc.stdout.read(size)) == size:
    count += np.frombuffer(buf, np.uint8).reshape(h0, W, 3).min(axis=2) > 235
    n += 1
if proc.wait() != 0: raise SystemExit("ffmpeg failed to decode the video")
count[count > n * 0.5] = 0                         # drop static white areas (screens, walls)
rows = count.sum(axis=1)
text_rows = np.where(rows > n * 3)[0]
# group rows into runs (allow small gaps between two subtitle lines), keep the lowest compact run
runs = []
for r in text_rows:
    if runs and r - runs[-1][1] <= 25: runs[-1][1] = r
    else: runs.append([r, r])
runs = [r for r in runs if r[1] - r[0] < H * 0.2 and rows[r[0]:r[1] + 1].sum() > n * 200]
band = None
if runs:
    top, bot = y0 + runs[-1][0], y0 + runs[-1][1]
    band = {"y": max(0, int(top - 14)), "h": int(min(H, bot + 18) - max(0, top - 14)), "width": W, "height": H}
    json.dump(band, open(f"{wd}/band.json", "w"))
    print("burned-in subtitles found:", band)
else:
    print("no burned-in white subtitles found")

# contact sheets of the subtitle area for reading the original captions
y, h = (band["y"], band["h"]) if band else (y0, h0)
tmp = f"{wd}/_sheet_frames"; os.makedirs(tmp, exist_ok=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf",
    f"fps=2,crop={W}:{h}:0:{y},scale=690:-1,drawtext=text='%{{pts\\:hms}}':x=2:y=2:fontsize=14:fontcolor=yellow:box=1:boxcolor=black",
    "-fps_mode", "vfr", f"{tmp}/f%04d.png"], check=True)
frames = sorted(glob.glob(f"{tmp}/f*.png"))
for i in range(0, len(frames), 22):
    grp = frames[i:i + 22]
    args = sum([["-i", f] for f in grp], [])
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-filter_complex", f"vstack=inputs={len(grp)}" if len(grp) > 1 else "null",
                    f"{wd}/subs_sheet_{i // 22}.png"], check=True)
for f in frames: os.remove(f)
os.rmdir(tmp)
print("contact sheets:", sorted(glob.glob(f"{wd}/subs_sheet_*.png")))
