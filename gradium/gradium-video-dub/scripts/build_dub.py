#!/usr/bin/env python3
"""Build the dub track and matching subtitles from script.json.

Usage: build_dub.py <workdir> --voice <voice_id> [--target en] [--max-tempo 1.12] [--subs-only]

Dub: keeps the live-translation audio for unchanged sentences, re-records edited ones with
Gradium TTS in the same voice (each take checked with STT, retried if it drifts, cached),
places every sentence at its onset, and time-compresses (rubberband) up to --max-tempo.
Writes dub_track.wav, subs.ass, placement.json, dub_duration.txt.
--subs-only: just subs.ass, timed to the onsets (for the original-audio, subtitled version).
"""
import argparse, asyncio, difflib, hashlib, io, json, os, re, subprocess, tempfile, wave
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("workdir"); ap.add_argument("--voice"); ap.add_argument("--target", required=True, help="target language: en, fr, de, es, pt")
ap.add_argument("--max-tempo", type=float, default=1.12); ap.add_argument("--subs-only", action="store_true")
a = ap.parse_args()
wd = a.workdir
script = json.load(open(f"{wd}/script.json"))
src = json.load(open(f"{wd}/source.json"))
video_dur, speech_end = src["duration"], src["speech_end"]
SR = 48000

W, H = src.get("width", 1280), src.get("height", 720)
band = json.load(open(f"{wd}/band.json")) if os.path.exists(f"{wd}/band.json") else None
FONT = round(H * 0.047) if W >= H else round(W * 0.05)          # same visual size on landscape and vertical
MARGIN_V = (H - band["y"] - band["h"] + round(H * 0.02)) if band else round(H * 0.1)   # sit inside the covered strip
MARGIN_LR = round(W * 0.12)
json.dump({"font": FONT}, open(f"{wd}/layout.json", "w"))  # render.py sizes the cover strip from this

def ass(cues, path):
    t = lambda s: f"{int(s // 3600)}:{int(s // 60 % 60):02}:{s % 60:05.2f}"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: S,Inter SemiBold,{FONT},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{max(1, FONT // 20)},0,2,{MARGIN_LR},{MARGIN_LR},{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [f"Dialogue: 0,{t(s)},{t(e)},S,,0,0,0,,{txt}" for s, e, txt in cues]
    open(path, "w", encoding="utf-8").write(head + "\n".join(lines) + "\n")

if a.subs_only:
    cues = []
    for k, s in enumerate(script):
        end = script[k + 1]["onset"] - 0.1 if k + 1 < len(script) else min(video_dur, speech_end + 0.6)
        cues.append((s["onset"], end, s["text"]))
    ass(cues, f"{wd}/subs.ass"); print(f"wrote {wd}/subs.ass ({len(cues)} cues)"); raise SystemExit

import gradium
if not a.voice: raise SystemExit("--voice is required for the dub")

with wave.open(f"{wd}/live/audio.wav") as w:
    assert w.getframerate() == SR
    live = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)

def trim(x, thr=250):
    idx = np.where(np.abs(x) > thr)[0]
    return x[max(0, idx[0] - int(0.02 * SR)): idx[-1] + int(0.06 * SR)] if len(idx) else x

def rms(x):
    v = x[np.abs(x) > 300]; return float(np.sqrt(np.mean(v ** 2))) if len(v) else 1.0

clips = []
for k, s in enumerate(script):
    lo = s["out_start"] if k == 0 else max(script[k - 1]["out_end"], s["out_start"] - 0.15)
    hi = s["out_end"] if k + 1 == len(script) else min(script[k + 1]["out_start"], s["out_end"] + 0.15)
    clips.append(trim(live[int(lo * SR): int(hi * SR)]))
redo = [k for k, s in enumerate(script) if s["text"] != s["live"] or s.get("spoken")]

words = lambda t: re.sub(r"[^\w ]", " ", t.lower()).split()
async def rerecord():
    c = gradium.client.GradiumClient(api_key=os.environ["GRADIUM_API_KEY"])
    sem = asyncio.Semaphore(2)                       # account limit is 5 concurrent sessions
    os.makedirs(f"{wd}/tts_cache", exist_ok=True)
    async def one(k):
        say = script[k].get("spoken") or script[k]["text"]
        path = f"{wd}/tts_cache/{hashlib.sha1(f'{a.voice}|{say}'.encode()).hexdigest()[:16]}.npy"
        if os.path.exists(path): return k, np.load(path)
        best = (-1, None)
        for attempt in range(5):
            async with sem:
                r = await c.tts(setup={"model_name": "default", "voice_id": a.voice, "output_format": "pcm"}, text=say)
                pcm = np.frombuffer(r.raw_data, np.int16)
                buf = io.BytesIO()
                with wave.open(buf, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(r.sample_rate)
                    w.writeframes(np.concatenate([pcm, np.zeros(r.sample_rate, np.int16)]).tobytes())
                heard = (await c.stt({"model_name": "default", "input_format": "wav",
                                      "json_config": {"language": a.target}}, buf.getvalue())).text
            # STT may write numbers as digits ("24 7") or words: accept a match with either form
            score = max(difflib.SequenceMatcher(None, words(t), words(heard)).ratio() for t in (say, script[k]["text"]))
            print(f"  line {k + 1} take {attempt + 1}: {score:.2f}  heard: {heard.strip()}", flush=True)
            if score > best[0]: best = (score, pcm)
            if score >= 0.92: break                      # one wrong word in a short line fails
        assert r.sample_rate == SR
        clip = trim(best[1].astype(np.float32)); np.save(path, clip)
        return k, clip
    return await asyncio.gather(*[one(k) for k in redo])

ref = np.median([rms(c) for k, c in enumerate(clips) if k not in redo] or [3000.0])
for k, clip in asyncio.run(rerecord()):
    clips[k] = clip * (ref / rms(clip))             # match loudness to the live output

def stretch(x, tempo):
    with tempfile.TemporaryDirectory() as d:
        with wave.open(f"{d}/i.wav", "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(np.clip(x, -32768, 32767).astype(np.int16).tobytes())
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"{d}/i.wav", "-af", f"rubberband=tempo={tempo:.4f}:pitchq=quality", f"{d}/o.wav"], check=True)
        with wave.open(f"{d}/o.wav") as w: return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)

track = np.zeros(int((video_dur + 30) * SR), np.float32)
cursor, placed = 0.0, []
for k, clip in enumerate(clips):
    onset = script[k]["onset"]
    slot_end = script[k + 1]["onset"] - 0.1 if k + 1 < len(clips) else speech_end + 0.2
    start = max(onset, cursor)
    tempo = min(a.max_tempo, max(1.0, (len(clip) / SR) / max(0.3, slot_end - start)))
    if tempo > 1.001: clip = stretch(clip, tempo)
    i = int(start * SR); track[i:i + len(clip)] += clip
    end = start + len(clip) / SR; cursor = end + 0.06
    placed.append({"id": script[k]["id"], "onset": onset, "start": round(start, 2), "end": round(end, 2),
                   "drift": round(start - onset, 2), "tempo": round(tempo, 3), "rerecorded": k in redo, "text": script[k]["text"]})

final = max(video_dur, cursor + 0.4)
track = track[: int(final * SR)]; track *= min(1.0, 30000 / max(1.0, np.max(np.abs(track))))
with wave.open(f"{wd}/dub_track.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(track.astype(np.int16).tobytes())
open(f"{wd}/dub_duration.txt", "w").write(f"{final:.3f}")
json.dump(placed, open(f"{wd}/placement.json", "w"), indent=1, ensure_ascii=False)
ass([(p["start"], min((placed[k + 1]["start"] if k + 1 < len(placed) else final) - 0.02, max(p["end"] + 0.4, p["start"] + 1.0)), p["text"])
     for k, p in enumerate(placed)], f"{wd}/subs.ass")

for p in placed:
    flag = "TTS " if p["rerecorded"] else "LIVE"
    print(f"{p['id']:3} {flag} drift {p['drift']:+5.2f}s x{p['tempo']:.2f}  {p['start']:6.2f}-{p['end']:6.2f}  {p['text'][:60]}")
print(f"last line ends {placed[-1]['end']:.2f}s; speaker stops {speech_end:.2f}s; video {video_dur:.2f}s -> output {final:.2f}s")
