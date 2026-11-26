#!/usr/bin/env python3
"""Stream the source audio through Gradium live translation (speech-to-speech) in real time.

Usage: live_translate.py <workdir> --target en --voice <voice_id>
Reads workdir/source_24k.pcm. Writes workdir/live/events.json and live/audio.wav (48 kHz).
Sessions cap at 300 s, so longer audio is split at the quietest point before each 280 s
mark; each part gets 8 s of trailing silence (or the last sentence is dropped) and is paced
in real time (faster input makes the pipeline drop sentences). Takes about as long as the video.
"""
import argparse, asyncio, base64, json, os, time, wave
import numpy as np
import websockets

ap = argparse.ArgumentParser()
ap.add_argument("workdir"); ap.add_argument("--target", required=True, help="en, fr, de, es, pt")
ap.add_argument("--voice", required=True)
a = ap.parse_args()
SR_IN, CHUNK, PART = 24000, 1920 * 2, 280          # 80 ms chunks of 24 kHz s16 mono
pcm = open(f"{a.workdir}/source_24k.pcm", "rb").read()
os.makedirs(f"{a.workdir}/live", exist_ok=True)

# split points (in samples) at the quietest 100 ms within 30 s before each PART mark
x = np.frombuffer(pcm, np.int16).astype(np.float32)
cuts, start = [0], 0
while len(x) - start > PART * SR_IN:                # every part, plus 8 s padding, stays under 300 s
    lo, hi = start + (PART - 30) * SR_IN, start + PART * SR_IN
    win = x[lo:hi][: (hi - lo) // 2400 * 2400].reshape(-1, 2400)
    start = lo + int(np.argmin((win ** 2).mean(axis=1))) * 2400 + 1200
    cuts.append(start)
cuts.append(len(x))

async def translate(part: bytes):
    setup = {"type": "setup", "model_name": "s2s-translate", "stt_model_name": "stt-translate",
             "tts_model_name": "default", "input_format": "pcm", "output_format": "pcm",
             "voice_id": a.voice, "json_config": {"target_language": a.target}}
    part += bytes(SR_IN * 2 * 8)
    events, audio = [], []
    async with websockets.connect("wss://api.gradium.ai/api/speech/s2s", max_size=None,
                                  additional_headers={"x-api-key": os.environ["GRADIUM_API_KEY"]}) as ws:
        await ws.send(json.dumps(setup))
        ready = json.loads(await ws.recv())
        if ready.get("type") != "ready": raise SystemExit(ready)
        t0 = time.monotonic()

        async def producer():
            for i, off in enumerate(range(0, len(part), CHUNK)):
                await asyncio.sleep(max(0, t0 + i * 0.08 - time.monotonic()))
                await ws.send(json.dumps({"type": "audio", "audio": base64.b64encode(part[off:off + CHUNK]).decode()}))
            await ws.send(json.dumps({"type": "end_of_stream"}))

        async def consumer():
            while True:
                msg = json.loads(await ws.recv())
                if msg["type"] == "audio": audio.append(base64.b64decode(msg["audio"])); continue
                if msg["type"] == "error": raise SystemExit(msg)
                if msg["type"] == "end_of_stream": return
                events.append(msg)
                if msg["type"] == "text": print(msg["text"], end=" ", flush=True)

        await asyncio.gather(producer(), consumer())
    return events, b"".join(audio), ready.get("sample_rate", 48000)

all_events, all_audio, out_offset = [], [], 0.0
for n, (s, e) in enumerate(zip(cuts, cuts[1:])):
    if len(cuts) > 2: print(f"\n[part {n + 1}/{len(cuts) - 1}: {s / SR_IN:.1f}-{e / SR_IN:.1f}s]")
    events, audio, sr = asyncio.run(translate(pcm[s * 2:e * 2]))
    for ev in events:                               # shift onto the concatenated output timeline
        for k in ("start_s", "stop_s"):
            if k in ev: ev[k] = round(ev[k] + out_offset, 3)
    all_events += events; all_audio.append(audio)
    out_offset += len(audio) / 2 / sr

json.dump(all_events, open(f"{a.workdir}/live/events.json", "w"), indent=1, ensure_ascii=False)
with wave.open(f"{a.workdir}/live/audio.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(b"".join(all_audio))
print()
