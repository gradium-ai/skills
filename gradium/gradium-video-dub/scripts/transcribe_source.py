#!/usr/bin/env python3
"""Extract the source audio and transcribe it with Gradium STT (timestamps included).

Usage: transcribe_source.py <video> <workdir> --lang fr
Writes: workdir/source_24k.pcm and source.json {duration, speech_end, sentences:[{start, text}], words:[{t, text}]}.
"""
import argparse, asyncio, json, os, re, subprocess
import numpy as np
import gradium

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("workdir"); ap.add_argument("--lang", required=True, help="en, fr, de, es, pt, or any")
a = ap.parse_args()
os.makedirs(a.workdir, exist_ok=True)

pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", a.video, "-vn", "-ac", "1", "-ar", "24000", "-f", "s16le", "-"],
                     capture_output=True, check=True).stdout
open(f"{a.workdir}/source_24k.pcm", "wb").write(pcm)
x = np.frombuffer(pcm, np.int16).astype(np.float32)
duration = len(x) / 24000

# when the speaker stops: last frame clearly above the noise floor
env = np.sqrt(np.convolve(x ** 2, np.ones(600) / 600, "same")[::240])   # 10 ms hop
speech_end = float(np.where(env > np.percentile(env, 30) * 2)[0][-1] * 0.01)

async def stt():
    c = gradium.client.GradiumClient(api_key=os.environ["GRADIUM_API_KEY"])
    return await c.stt({"model_name": "default", "input_format": "pcm", "json_config": {"language": a.lang}},
                       np.frombuffer(pcm, np.int16), sample_rate=24000)
res = asyncio.run(stt())

words = [{"t": round(w.start_s, 2), "text": w.text.strip()} for w in res.text_with_timestamps]
sentences, cur = [], None
for w in words:
    # a token can span a sentence end ("payants. C'est"): split it there
    for j, piece in enumerate(re.split(r"(?<=[.?!…])\s+", w["text"])):
        if cur is None: cur = {"start": w["t"], "text": piece}
        else: cur["text"] += " " + piece
        if piece.endswith((".", "?", "!", "…")): sentences.append(cur); cur = None
if cur: sentences.append(cur)

W, H = map(int, subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
    "stream=width,height", "-of", "csv=p=0", a.video], capture_output=True, text=True).stdout.strip().split(",")[:2])
json.dump({"lang": a.lang, "width": W, "height": H, "duration": round(duration, 2), "speech_end": round(speech_end, 2), "sentences": sentences, "words": words},
          open(f"{a.workdir}/source.json", "w"), indent=1, ensure_ascii=False)
for s in sentences: print(f"{s['start']:6.2f}  {s['text']}")
print(f"duration {duration:.2f}s, speaker stops at {speech_end:.2f}s")
