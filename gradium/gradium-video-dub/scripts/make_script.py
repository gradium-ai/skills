#!/usr/bin/env python3
"""Turn the live translation into an editable script.json (one entry per sentence).

Usage: make_script.py <workdir> [--force]
Each entry: id, live (as translated), text (edit this), onset (when the speaker starts the
matching source sentence, pre-filled by order: verify it), spoken (optional TTS override),
out_start/out_end (position in live/audio.wav), source_hint.
"""
import json, os, sys

wd = sys.argv[1]
path = f"{wd}/script.json"
if os.path.exists(path) and "--force" not in sys.argv:
    raise SystemExit(f"{path} exists (it may hold your edits). Use --force to overwrite.")

src = json.load(open(f"{wd}/source.json"))
ev = [e for e in json.load(open(f"{wd}/live/events.json")) if e["type"] == "text"]
sent, cur = [], None
for e in ev:
    if cur is None: cur = [e["start_s"], e["stop_s"], e["text"].strip()]
    else: cur[1] = e["stop_s"]; cur[2] += ("" if cur[2].endswith("—") else " ") + e["text"].strip()
    if cur[2].endswith((".", "?", "!", "…")): sent.append(cur); cur = None
if cur: sent.append(cur)

# onset guess: the same relative position in the source words (by characters), snapped to a
# word that follows a pause when one is close. Rough: always check against source.json.
words = src.get("words") or [{"t": x["start"], "text": x["text"]} for x in src["sentences"]]
cum, acc = [], 0
for w in words: cum.append(acc); acc += len(w["text"]) + 1
tot_src, tot_tr = acc or 1, sum(len(s[2]) + 1 for s in sent) or 1
def guess(frac):
    i = max(0, min(len(words) - 1, next((j for j, c in enumerate(cum) if c >= frac * tot_src), len(words) - 1)))
    starts = [j for j in range(max(0, i - 4), min(len(words), i + 5))
              if j == 0 or words[j - 1]["text"].endswith((",", ".", "?", "!", ":"))]
    j = min(starts, key=lambda j: abs(j - i)) if starts else i
    return words[j]["t"], " ".join(w["text"] for w in words[j:j + 12])

script, before = [], 0
for i, (a, z, t) in enumerate(sent):
    onset, hint = guess(before / tot_tr)
    script.append({"id": i + 1, "live": t, "text": t, "onset": onset, "spoken": None,
                   "out_start": a, "out_end": z, "source_hint": hint})
    before += len(t) + 1
json.dump(script, open(path, "w"), indent=1, ensure_ascii=False)
for s in script: print(f"{s['id']:2} @{s['onset']:6.2f}  {s['text']}\n            src: {s['source_hint'][:90]}")
print(f"\nWrote {path}. Fix 'text' and 'onset' against the source before building.")
