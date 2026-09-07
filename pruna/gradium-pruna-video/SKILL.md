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
Requires `ffprobe` on PATH. Downloads are limited to 512 MiB and five minutes;
existing outputs are replaced only after media validation. Avatar duration must
match the source audio within 5% or one second, whichever is larger.

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
          "video_prompt": "The person speaks with subtle gestures.",
          "disable_safety_filter": false, "disable_prompt_upsampling": true}}'
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

5. **Download** the `generation_url` and validate it before saving as `.mp4`.
   Send `apikey` only to the exact `https://api.pruna.ai` origin (port 443).
   Follow relative redirects with URL resolution, validate every destination,
   and omit the key on external delivery URLs. Reject HTTP and embedded credentials.

Keep the avatar safety filter enabled and prompt upsampling disabled, as in the
request above. Enabling upsampling can add another provider to the image/prompt
data flow; explain that change before sending user assets. Authenticated API
calls should reject redirects rather than forwarding custom key headers.

## Example prompts (battle-tested)

`video_prompt` shapes everything the lips don't. These worked in
production; adapt the subject, keep the structure — articulation
first, then constraints phrased as physical facts:

- **Human presenter / spokesperson**
  `"The person speaks with subtle hand gestures and natural head
  movement, warm eye contact with the camera, soft office lighting."`
- **Character or statue, strong lip-sync, still eyes** (the most
  reliable pattern found):
  `"The classical marble statue is speaking: its lips and jaw move
  vigorously and precisely with every syllable, the mouth clearly
  opening and closing in sync with the audio. The rest of the statue
  is rigid carved stone. The eyes are solid sculpted marble — because
  they are stone they cannot blink, cannot close and cannot move.
  Plain black background."`
  with `"negative_prompt": "pupils, irises, human eyes, blinking,
  closed eyes, text, captions, watermark"`
- **Closed eyes that stay closed**: use a source image whose lids are
  already closed (harvest a frame from a previous render), plus
  `"The eyes remain completely closed for the entire video: smooth
  carved stone eyelids, never opening."`
- **Anti-text insurance** for speech full of IDs/numbers, appended to
  any prompt: `"The frame contains only the subject on a plain
  background — absolutely no text, no letters, no numbers, no
  subtitles anywhere."` (Reduces but does not guarantee; sweep frames
  after.)

## Judging the result

Avatar generation is a diffusion lottery — grade every render before
showing anyone, and read
[references/render-quirks.md](references/render-quirks.md) for the
full battle-tested playbook (text hallucination on alphanumeric audio,
eye re-animation, first-frame-equals-source, source prep with
`p-image-edit`, when to fix with ffmpeg instead of re-rolling).
The short version:

- `ffprobe` the output: video duration should match the audio duration
  (avatar mode) — a big mismatch means the audio didn't take.
- Extract the audio track (`ffmpeg -i out.mp4 -ar 24000 -ac 1 check.wav`)
  and round-trip through Gradium STT: the transcript should match your
  script. Silent output in scene mode usually means `save_audio` was
  omitted.
- Build two frame montages and *look at them*: 6–8 frames evenly
  spaced (catches blinks, gaze drift, hallucinated text — sparse
  checks miss them), and frames at speech-word midpoints (mouth must
  be visibly articulating; a closed mouth mid-word means lip-sync
  failed).
- Re-roll with a new `seed` when a take fails; prefer cheap ffmpeg
  fixes (crop, drawbox, fade-in) when the flaw sits outside the
  subject.

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
7. Long `negative_prompt` lists freeze the face — a negative stuffed
   with "eye movement, head movement, …" suppressed lip-sync entirely.
   Lead the positive prompt with strong mouth articulation and keep
   negatives to a handful of terms.
8. `negative_prompt_strength` appears in docs but the API rejects it
   (400 "additional properties forbidden") — send `negative_prompt`
   alone.
9. Speech full of IDs/serials/phone numbers can make the model burn
   gibberish pseudo-captions into the frame, and the first frame is
   essentially your source image — sweep frames before shipping (see
   [references/render-quirks.md](references/render-quirks.md)).

## References

- Pruna model docs: https://docs.pruna.ai/en/stable/docs_pruna_endpoints/performance_models/p-video-avatar.html
  and `.../p-video.html`; API portal: https://docs.api.pruna.ai/
- Gradium voice choices and TTS tuning: gradium-text-to-speech skill
  (clone voices via gradium-voice-cloning to make the avatar speak in a
  specific person's voice — with their consent).
