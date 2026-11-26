#!/usr/bin/env python3
"""Render the final video: cover burned-in source subtitles, burn subs.ass, set the audio.

Usage: render.py <workdir> [--video dl/video.mp4] [--keep-audio] [--out final.mp4]
Default swaps in dub_track.wav (holding the last frame if the dub runs long);
--keep-audio keeps the original speech (subtitled version).
"""
import argparse, json, os, subprocess

ap = argparse.ArgumentParser()
ap.add_argument("workdir"); ap.add_argument("--video"); ap.add_argument("--keep-audio", action="store_true")
ap.add_argument("--out")
a = ap.parse_args()
wd = a.workdir
video = a.video or f"{wd}/dl/video.mp4"
out = a.out or f"{wd}/final.mp4"
dur = json.load(open(f"{wd}/source.json"))["duration"]

pad = 0.0
if not a.keep_audio and os.path.exists(f"{wd}/dub_duration.txt"):
    pad = max(0.0, float(open(f"{wd}/dub_duration.txt").read()) - dur)
v = f"[0:v]tpad=stop_mode=clone:stop_duration={pad:.3f}" if pad > 0.01 else "[0:v]null"
if os.path.exists(f"{wd}/band.json"):
    b = json.load(open(f"{wd}/band.json"))
    if os.path.exists(f"{wd}/layout.json"):      # grow the strip upward so three subtitle lines fit
        need = round(json.load(open(f"{wd}/layout.json"))["font"] * 3.6)
        if b["h"] < need: b["y"], b["h"] = max(0, b["y"] + b["h"] - need), need
    v += (f",split[base][b];[b]crop=iw:{b['h']}:0:{b['y']},gblur=sigma=30:steps=3,eq=brightness=-0.08[bl];"
          f"[base][bl]overlay=0:{b['y']},drawbox=x=0:y={b['y']}:w=iw:h={b['h']}:color=black@0.38:t=fill")
subs = os.path.abspath(f"{wd}/subs.ass").replace("\\", "/").replace(":", "\\:")
v += f",ass='{subs}'[v]"

cmd = ["ffmpeg", "-v", "error", "-y", "-i", video]
if a.keep_audio:
    graph, amap = v, ["-map", "0:a", "-c:a", "copy"]
else:
    cmd += ["-i", f"{wd}/dub_track.wav"]
    graph = v + ";[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,pan=stereo|c0=c0|c1=c0[a]"
    amap = ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
cmd += ["-filter_complex", graph, "-map", "[v]", *amap, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
subprocess.run(cmd, check=True)
print(out)
