# MiniMax H3 Max lip-sync render on fal

Use this reference after the Gradium voice has been approved and promoted.
`minimax/h3-max/lip-sync/image-to-video` on fal.ai animates one portrait from a
speech track. The audio determines the clip length and preserves the designed
voice; MiniMax adds no voice of its own.

## Hard limits that shape the script

| Constraint | Value | What to do |
| --- | --- | --- |
| Minimum audio | 5 s | The script pads shorter speech with silence to 5.2 s |
| Maximum audio per generation | 14.8 s | Anything longer is cut to its first 14.8 s by the model. The script refuses longer audio unless `--allow-clip` is passed; prefer shortening the script |
| Portrait aspect ratio | 0.4 to 2.5 (width / height) | The script checks decoded dimensions and refuses out-of-range images; crop first |
| Image formats | jpg, jpeg, png, webp, gif, avif, heic, heif | The script accepts PNG, JPEG, and WebP and sniffs the bytes rather than trusting the extension |
| Audio formats | mp3, ogg, wav, m4a, aac | The script always sends mono 24 kHz WAV |

Because one generation covers at most 14.8 seconds, settle the script length
during intake: about 30 to 40 words depending on the approved voice's pace.
Do not stitch several generations into one clip by default; each is an
independent sample and the identity, lighting, and pose drift between them. If
the user needs a longer piece, propose separate scenes with cuts between them
and get agreement before spending credits on more than one generation.

## Pricing and resolution

fal charges per second of output video:

| `resolution` | Rate | 14.8 s clip |
| --- | --- | --- |
| `480P` | $0.05/s | $0.74 |
| `768P` (default) | $0.08/s | $1.18 |
| `1080P` | $0.16/s | $2.37 |
| `2K` | $0.32/s | $4.74 |

Use `768P` for drafts and first takes. Choose `1080P` or `2K` only when the user
wants it and has seen the charge. The script prints the estimated charge before
it submits. Output uses the supported aspect ratio nearest the portrait.

## 1. Synthesize the production WAV

Call `POST https://api.gradium.ai/api/post/speech/tts` with `x-api-key`:

```json
{
  "text": "<approved script>",
  "voice_id": "<permanent Gradium voice ID>",
  "output_format": "wav",
  "only_audio": true
}
```

Apply the approved language-specific rewrite rules, pronunciation dictionary,
speed, and pauses when the project uses them. Validate that the response is a
bounded, decodable WAV before sending it downstream, then measure its duration
against the 5 to 14.8 second window.

## 2. Submit the request

The bundled script does steps 2 to 4 (`render`):

```bash
export GRADIUM_API_KEY=... FAL_KEY=...
python scripts/minimax_avatar.py render "Hi, I'm Arthur. Let's set up your policy." \
    --image portrait.png --voice <voice_id> --out talking.mp4
python scripts/minimax_avatar.py render --audio speech.wav --image portrait.png --out talking.mp4
```

It sends the portrait and WAV inline as base64 data URIs, which fal documents
as accepted input, so no upload endpoint is involved and the key only ever
reaches `queue.fal.run`. Inline inputs are capped at 8 MiB each; downscale a
huge portrait rather than raising the cap. A hosted product that renders many
clips should upload assets once with `fal_client.upload_file(path)` and pass
the returned HTTPS URL instead; the request shape is otherwise identical.

Queue submission, with the key in an `Authorization: Key` header:

```bash
curl -X POST https://queue.fal.run/minimax/h3-max/lip-sync/image-to-video \
  -H "Authorization: Key $FAL_KEY" -H "Content-Type: application/json" \
  -d '{
    "image_url": "<https URL or data URI of the portrait>",
    "audio_url": "<https URL or data URI of the WAV>",
    "resolution": "768P",
    "enable_safety_checker": true
  }'
```

The response is `{"request_id": "...", "status_url": "...", "response_url": "...",
"cancel_url": "..."}`. Keep `request_id`; build the status and result URLs
yourself from the model's owner and alias (`minimax/h3-max`) rather than
following URLs from the response.

Optional fields:

- `enable_transcription: true` has MiniMax transcribe the audio to guide lip
  sync. Try it (`--transcribe`) when a take mumbles through dense or
  non-English speech; leave it off for the first take.
- `seed` reproduces or rerolls a take. The result reports the seed used.
- `enable_safety_checker` stays `true`. Send it explicitly.

With the Python client the same call is
`fal_client.subscribe("minimax/h3-max/lip-sync/image-to-video", arguments={...})`.

## 3. Poll

`GET https://queue.fal.run/minimax/h3-max/requests/{request_id}/status` with the
same header returns `IN_QUEUE` (with `queue_position`), `IN_PROGRESS` (with
`logs` when `?logs=1`), or `COMPLETED`. Poll every few seconds with an overall
deadline; the script allows 15 minutes and never resubmits on timeout. Treat
429 and 5xx as transient with bounded backoff. Note that fal retries a request
internally up to ten times unless `X-Fal-No-Retry: 1` is sent.

## 4. Fetch the result and download

`GET https://queue.fal.run/minimax/h3-max/requests/{request_id}` returns:

```json
{
  "video": {"url": "https://v3.fal.media/files/.../output.mp4", "content_type": "video/mp4",
            "file_name": "output.mp4", "file_size": 2411309},
  "seed": 1234,
  "duration": 12.4,
  "timings": {"inference": 41.2}
}
```

A failed request answers this call with an error status and a `detail` field;
validation failures (aspect ratio, audio length, unsupported format) arrive
this way. When downloading `video.url`:

- require HTTPS, no embedded credentials, and the default port;
- send no API key at all: the CDN URL is self-authorizing;
- follow relative redirects by resolving them, revalidate each hop, and stop
  after a handful;
- cap response bytes and validate the container and duration before replacing
  any existing output.

Results persist according to the account's media expiration settings, so
download and store the MP4 rather than linking to the fal URL.

Use an HTTP client and structured JSON APIs in application code. The curl
snippets are illustrative; never build a shell command by concatenating
user-controlled paths, prompts, filenames, URLs, ids, or scripts.

## Getting a good take

- Prefer a clean, single-subject portrait with the face unobstructed, some
  space around the head, and lighting that stays believable in motion.
- MiniMax reads emphasis and rhythm from the audio. If articulation looks weak,
  try `--transcribe` before rerolling seeds.
- The first frames sit close to the source image. Trim or fade the first
  quarter second locally only if the transition distracts.
- There is no motion prompt on this endpoint; framing and gesture come from
  the portrait. Choose or crop the portrait accordingly.

Official fal documentation:

- https://fal.ai/models/minimax/h3-max/lip-sync/image-to-video/api
- https://fal.ai/docs/model-apis/model-endpoints/queue
