---
name: gradium-video-dub
description: Translate a video's speech into another language with Gradium's APIs, then burn translated subtitles onto the video and/or dub it in the speaker's own cloned voice, timed to the speaker. Use this whenever someone shares a video or a post/page with a video (LinkedIn, YouTube, X, a direct .mp4) and wants it translated, subtitled, captioned or dubbed between English, French, German, Spanish and Portuguese, wants the original burned-in subtitles removed, or mentions Gradium live translation, speech-to-speech, voice cloning or voice localization for a video, even if they don't say "dub".
license: MIT
compatibility: Requires internet access, a Gradium API key (GRADIUM_API_KEY), ffmpeg with libass and rubberband, and Python packages gradium, websockets and numpy.
metadata:
  "openclaw":
    "requires":
      "env":
      - "GRADIUM_API_KEY"
    "primaryEnv": "GRADIUM_API_KEY"
---

# Gradium video dub

Turn a video in one language into a subtitled or dubbed video in another, using Gradium for
transcription, live translation (speech-to-speech), voice cloning, TTS and STT. The scripts
in `scripts/` do the mechanical work; your job is the judgment: checking the translation,
tightening lines to fit, and choosing the voice.

Works between any of Gradium's languages: English (`en`), French (`fr`), German (`de`),
Spanish (`es`) and Portuguese (`pt`), in either direction. Use `--lang any` when the source
language is unknown.

Needs `GRADIUM_API_KEY`, `ffmpeg` (with libass and rubberband), and `pip install gradium websockets numpy`.
API details and limits: [references/gradium-api.md](references/gradium-api.md). For audio-only
translation see [gradium-speech-translation](../gradium-speech-translation/SKILL.md); for
voice-library management and consent guidance see [gradium-voice-cloning](../gradium-voice-cloning/SKILL.md).

## Deliverables

Ask which the user wants if it isn't clear:
1. **Subtitled**: original voice, translated subtitles burned in.
2. **Dubbed**: speaker's voice replaced by the translation in their own cloned voice, subtitles matching the dub.

## Workflow

Keep downloads in their own folder (`$W/dl`) and run scripts from the skill folder, passing paths as arguments.

```bash
S=<this skill dir>/scripts; W=<work dir>
python $S/fetch_video.py "<url or file>" $W/dl                    # -> $W/dl/video.mp4
python $S/transcribe_source.py $W/dl/video.mp4 $W --lang <src>    # source transcript + timings
python $S/detect_burned_subs.py $W/dl/video.mp4 $W                # finds old subtitles, contact sheets
python $S/live_translate.py $W --target <tgt> --voice <voice_id>  # Gradium live translation
python $S/make_script.py $W                                       # -> $W/script.json to review
python $S/build_dub.py $W --target <tgt> --voice <voice_id>       # dub track + matching subtitles
python $S/build_dub.py $W --target <tgt> --subs-only              # or: subtitles only
python $S/render.py $W [--keep-audio]                             # -> $W/final.mp4
```

### 1. Source timing
`transcribe_source.py` writes `source.json`: the source sentences with start times and the
moment the speaker stops (`speech_end`). If the video has burned-in subtitles,
`detect_burned_subs.py` also writes `subs_sheet_*.png` contact sheets (subtitle strip every
0.5 s, timestamped). Read them: human-edited captions are often more accurate than STT for
both wording and timing. Detection looks for white text; for other colours, write
`band.json` (`{"y": top, "h": height}` in pixels) by hand from the contact sheets.

### 2. Voice (dub only)
Clone the speaker only with their permission. Ask the user to confirm it; don't assume.
Then: `python $S/clone_voice.py $W/dl/video.mp4 --lang <source lang> --name "<Name>" --consent`.
The script prints the voice id.

- **To keep the speaker's accent** (usually what people want), use the source-language
  clone directly with the target language. It speaks the target language with their natural
  accent and stays closest to their timbre.
- **Voice Localization** (`references/gradium-api.md`) only offers fixed accents (General
  American, Standard British, ...). It changes how the person sounds, so use it only when
  the user asks for that accent.

For subtitles only, the voice doesn't matter: pick any catalog voice in the target language
(`GET /voices/?include_catalog=true&locale=<tgt>-...`).

### 3. Live translation
`live_translate.py` streams the source audio in real time (80 ms chunks, 8 s of trailing
silence so the last sentence isn't dropped), splits videos longer than the 300 s session cap
at quiet points, and saves `live/events.json` + `live/audio.wav`. It takes about as long as
the video.
Gradium's text timestamps follow the *output* audio, which runs longer than the video, so
never use them for subtitle timing. `make_script.py` handles this.

### 4. Review the script (the important step)
`make_script.py` writes `script.json`, one entry per translated sentence:
`{"id", "live", "text", "onset", "spoken"}`. For each entry:

- **Check `text` against the source** (`source.json`, or the burned-in captions). The live
  model makes real errors: product terms swapped for look-alikes ("freemium" → "premium",
  "API" → "app"), dropped negations, mangled endings. Rewrite wrong sentences faithfully in `text`. Any sentence whose `text`
  differs from `live` gets re-recorded in the cloned voice.
- **Set `onset`** to when the speaker starts the matching source sentence (seconds).
  `make_script.py` pre-fills a guess by order; correct it from `source.json`.
- **Fit the timing (dub).** Run `build_dub.py`, read the drift report, and trim wordy lines
  (filler words, stacked connectors, padded phrasing) until drift stays under ~0.8 s and the
  last line ends near `speech_end`. German and French usually run longer than English, so
  expect more trimming going into them. Keep every point the speaker makes. Don't speed speech
  past ~1.12×; shorter wording sounds better than fast talking.
- **`spoken`** (optional) overrides what TTS says when it differs from the subtitle. Use it
  for numbers, symbols and acronyms the clone reads oddly, written out in the target
  language (`"24/7"` → `"twenty-four seven"`, `"24h/24"` → `"vingt-quatre heures sur vingt-quatre"`).

Show the user the corrected sentences before the final render when the stakes are high
(public posts, someone's name attached).

### 5. Build and render
`build_dub.py` re-records changed lines with TTS in the chosen voice. It checks each take
with STT and retries when the clone slips into the source language, and caches good takes
so later runs stay stable. It then places each sentence at its `onset` and writes
`dub_track.wav`, `subs.ass` and `placement.json`. `--subs-only` skips audio and times the
subtitles to the onsets.

`render.py` covers the old subtitle strip (blur and dark bar) when `band.json` exists, burns
`subs.ass`, and either keeps the original audio (`--keep-audio`) or swaps in the dub, freezing
the last frame if the dub runs a bit long. Check a few frames and run STT on the result
before handing it over.

## Pitfalls

- Gradium allows 5 concurrent sessions per account; the scripts cap themselves at 2–3.
- Clones occasionally drift into the source language mid-sentence; STT verification in
  `build_dub.py` catches it.
- Each clone uses a custom-voice slot on the account. Tell the user which voice ids you created.
