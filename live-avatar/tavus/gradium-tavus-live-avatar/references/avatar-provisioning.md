# Tavus face and PAL provisioning

Provisioning is a one-time step that yields a `face_id` and, optionally, a `pal_id`.
The worker only reads them from the environment.

## Account, key, and credits

- Sign up for a developer account at [platform.tavus.io](https://platform.tavus.io)
  (`/auth/sign-up?is_developer=true`). Plans and billing live there.
- Generate the API key in PAL Maker's Developer section at
  [maker.tavus.io/dev](https://maker.tavus.io/dev). Every request to
  `https://tavusapi.com` carries it in the `x-api-key` header.
- Sessions started through the LiveKit plugin are Tavus conversations and draw
  from your plan's conversational video minutes. Confirm the rate that applies to
  echo/LiveKit conversations on your plan before launch.

Developer plans as published on the Tavus pricing page (verify before quoting):

| Plan | Monthly | Included minutes | Overage | Concurrent streams | Custom faces |
| --- | --- | --- | --- | --- | --- |
| Free | $0 | 25 | none | 1 | none (stock only) |
| Starter | $59 | 100 | $0.37/min | 3 | 3 per month |
| Growth | $397 | 1,250 | $0.32/min | 10 | 7 per month |
| Enterprise | custom | scaled | custom | custom | unlimited |

Buy more minutes or upgrade in the Tavus platform billing page. Overage is
available on paid plans only; the Free plan stops when its minutes are used.

## Choose a stock face

```bash
curl -s "https://tavusapi.com/v2/faces?face_type=system&verbose=true&limit=50" \
  -H "x-api-key: $TAVUS_API_KEY"
```

Each entry returns `face_id`, `face_name`, `status`, `model_name`, and a
`thumbnail_video_url`. Prefer `status: completed` faces trained on
`phoenix-4.5` or `phoenix-4`. Show the user two or three thumbnails and let them
pick; do not choose a face that implies a real person without their say-so.

For the first run you may omit both `face_id` and `pal_id`; the plugin uses
Tavus's stock LiveKit PAL and its default stock face.

## Create a custom face (paid plans)

Custom faces are trained from a 2 to 3 minute video or from a single image.
Both paths are `POST https://tavusapi.com/v2/faces`:

```json
{
  "face_name": "Studio host",
  "model_name": "phoenix-4.5",
  "train_image_url": "https://example.com/portrait.png",
  "voice_name": "anna",
  "auto_fix_training_image": true
}
```

- Use `train_video_url` (a direct download link) or `train_image_url`, never both.
- Image training requires `voice_name` (a Tavus stock voice slug) or
  `default_voice_id`. That voice is not used in this stack, because Gradium
  supplies the audio, but the field is mandatory.
- `phoenix-4.5` returns a watermarked preview in about a minute from a photo and
  refines in the background; `phoenix-4` completes fully before delivery.
- Poll `GET /v2/faces/{face_id}` until `status` is `completed`; `error` means
  the training material was rejected.
- Tavus requires that you hold the rights to the likeness, voice, and footage.
  Confirm authorization with the user before uploading a real person.

## Create a custom PAL (optional)

The stock LiveKit PAL is enough for most agents. Create your own only when you
need a different default face or Tavus-side settings such as a maximum call
duration. A PAL used with LiveKit must be echo mode with a `livekit` transport:

```bash
curl -s https://tavusapi.com/v2/pals \
  -H "x-api-key: $TAVUS_API_KEY" -H "Content-Type: application/json" \
  -d '{
    "pal_name": "gradium-livekit",
    "default_face_id": "<face_id>",
    "pipeline_mode": "echo",
    "layers": {"transport": {"transport_type": "livekit"}}
  }'
```

Store the returned `pal_id` as `TAVUS_PAL_ID`. Do not add a `system_prompt`,
LLM, or TTS layer; Gradium and your LLM own the conversation.

## Guardrails

- Provisioning scripts must mock every Tavus endpoint in tests.
- Never retry face training automatically; it consumes a custom-face slot.
- Keep training videos and portraits out of version control and the web root.
- Log `face_id`, `pal_id`, and `conversation_id`, never the API key.

## Pipecat alternative

Pipecat has a first-party Tavus service: `uv add "pipecat-ai[tavus]"`, then
`TavusVideoService(api_key=..., replica_id=..., persona_id="pipecat0", session=aiohttp_session)`.
The `pipecat0` persona tells Tavus to expect echo audio from the Pipecat bot rather than a Tavus
voice, so the Gradium TTS voice is preserved. The service creates two Daily rooms (one with the
avatar, one with the user) and forwards interruptions with a reset of the audio task. Keep Gradium
STT and TTS as the speech providers in the Pipecat pipeline exactly as you would in LiveKit.
