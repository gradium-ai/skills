---
name: gradium-pruna-video
description: Turn text into a talking video by piping Gradium text-to-speech audio into Pruna AI's video generation models (P-Video-Avatar for talking heads from a portrait, P-Video for audio-conditioned scene video). Use when the user wants a talking avatar, spokesperson clip, lip-synced character, product demo presenter, or any video whose speech should use a specific Gradium voice (flagship or cloned) instead of Pruna's built-in voices — including phrasings like "make this image talk", "voice this video with my cloned voice", "talking banana", or "avatar video from this script". Also use when adding a separately generated audio track to a Pruna video generation.
license: MIT
compatibility: Requires internet access, a Gradium API key (GRADIUM_API_KEY), and a Pruna API key (PRUNA_API_KEY). Pruna renders cost real credits (~$0.025/s at 720p).
metadata: {"openclaw": {"requires": {"env": ["GRADIUM_API_KEY", "PRUNA_API_KEY"]}, "primaryEnv": "PRUNA_API_KEY"}}
---

# Gradium voice → Pruna video

Pruna's video models accept an uploaded audio file and lip-sync to it.
That makes them a natural downstream for Gradium TTS: any flagship or
**cloned** Gradium voice can drive the video, with Gradium's speed,
pronunciation-dictionary, and pause controls intact — instead of
Pruna's 30 built-in voices.

Why generate the audio separately at all: exact voice identity (clones),
exact pronunciation (`rewrite_rules`, pronunciation dictionaries), exact
pacing (`padding_bonus`, `<break>` tags), and a reusable audio asset.

## Pick a Pruna model

| Model | Input | Output | Use for |
| --- | --- | --- | --- |
| `p-video-avatar` | portrait image + audio | talking-head video, lip-synced | spokesperson, character head-shots. ~$0.025/s at 720p, $0.045/s at 1080p |
| `p-video` | prompt + image + audio, `save_audio: true` | scene video conditioned on the audio, audio embedded | animated scenes where speech drives motion. Video length follows the audio; `duration` is ignored |

Both are called the same way; only the `Model` header and `input`
fields differ.

## End-to-end (bundled, tested script)

```bash
export GRADIUM_API_KEY=... PRUNA_API_KEY=...
python scripts/voice_video.py "Welcome to the demo!" \
    --image portrait.png --gradium-voice NbpkqMVS3CJeq2j8 --out talking.mp4
# or reuse existing audio instead of synthesizing:
python scripts/voice_video.py --audio narration.wav --image portrait.png --out talking.mp4
# scene mode (p-video):
python scripts/voice_video.py "..." --image scene.png --mode scene \
    --prompt "the character gestures while speaking, office background"
```

The script does the whole pipeline: Gradium TTS → Pruna upload →
prediction → poll → download → duration check.

## The pipeline, step by step

1. **Synthesize speech with Gradium** (see gradium-text-to-speech).
   `output_format: "wav"` — Pruna accepts wav, mp3, flac. Keep clips
   under ~3 minutes; avatar consistency drifts on very long takes.

2. **Upload image and audio to Pruna** (multipart field is `content`):
   ```bash
   curl -X POST https://api.pruna.ai/v1/files \
     -H "apikey: $PRUNA_API_KEY" -F "content=@speech.wav"
   # -> {"id": "file-...", "urls": {"get": "https://api.pruna.ai/v1/files/file-..."}}
   ```
   Use the `urls.get` value in the prediction request.

3. **Create the prediction** — model selected via the `Model` header:
   ```bash
   curl -X POST https://api.pruna.ai/v1/predictions \
     -H "Content-Type: application/json" -H "apikey: $PRUNA_API_KEY" \
     -H "Model: p-video-avatar" \
     -d '{"input": {"image": "<image-url>", "audio": "<audio-url>",
          "resolution": "720p",
          "video_prompt": "The person speaks with subtle gestures."}}'
   ```
   - `audio` takes priority over `voice_script`/built-in TTS — when you
     pass audio, Pruna's own voices are bypassed entirely.
   - For `p-video`: pass `prompt` (required), `image`, `audio`, and
     `save_audio: true` (without it the output video is silent).
   - Async by default: response is `{"id": ..., "get_url": ...}`. Add
     header `Try-Sync: true` to block up to 60 s instead.

4. **Poll** `GET /v1/predictions/status/{id}` every ~5 s until
   `status` is `succeeded` (then `generation_url` holds the MP4) or
   `failed`. Renders typically take tens of seconds; budget minutes for
   1080p or long clips.

5. **Download** the `generation_url` (send the `apikey` header) and
   save as `.mp4`.

## Judging the result

- `ffprobe` the output: video duration should match the audio duration
  (avatar mode) — a big mismatch means the audio didn't take.
- Extract the audio track (`ffmpeg -i out.mp4 -ar 24000 -ac 1 check.wav`)
  and round-trip through Gradium STT: the transcript should match your
  script. Silent output in scene mode usually means `save_audio` was
  omitted.
- Lip-sync quality is best judged by eye; regenerate with a `seed` for
  reproducible comparisons.

## Common mistakes

1. Passing a local file path or base64 in `input.audio` — Pruna wants
   the **uploaded file URL** from `/v1/files`.
2. Forgetting the `Model` header — the endpoint is shared by all Pruna
   models.
3. Scene mode without `save_audio: true` — video renders fine but mute.
4. Setting `duration` alongside `audio` — it's ignored; the audio's
   length wins.
5. Using Pruna's `voice_script` *and* expecting a Gradium voice — the
   whole point of this skill is to pass `audio` instead.
6. Auth header is `apikey` (lowercase, no prefix) — not `x-api-key`
   (that's Gradium) and not `Authorization: Bearer`.

## References

- Pruna model docs: https://docs.pruna.ai/en/stable/docs_pruna_endpoints/performance_models/p-video-avatar.html
  and `.../p-video.html`; API portal: https://docs.api.pruna.ai/
- Gradium voice choices and TTS tuning: gradium-text-to-speech skill
  (clone voices via gradium-voice-cloning to make the avatar speak in a
  specific person's voice — with their consent).
