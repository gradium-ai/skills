# Gradium Voice Design provisioning

Use this reference only when the user needs a newly designed voice. If they
provide a permanent Gradium `voice_id`, skip this lifecycle and use that voice.

Voice Design is a one-time, server-side flow. It creates a temporary candidate,
lets the user hear an audition, and promotes only the accepted candidate to a
permanent voice. Use `https://api.gradium.ai/api` and the `x-api-key` header.

The bundled script runs the whole lifecycle one step at a time so the user can
listen between steps:

```bash
export GRADIUM_API_KEY=...
python scripts/minimax_avatar.py design "Calm, older, reassuring; measured pace." \
    --language en --out audition.wav        # prints vox_emb_... and writes the audition
python scripts/minimax_avatar.py promote vox_emb_... --name "Arthur"   # prints the voice_id
python scripts/minimax_avatar.py discard vox_emb_...                   # if rejected
```

`design` deletes the candidate itself if the readiness poll or the audition
fails, so a failed run never leaves a stray paid candidate behind.

## Candidate lifecycle (what the script does)

1. Generate one candidate with `POST /voice-generator/generate`:

   ```json
   {
     "prompt": "Calm, older, reassuring, softly textured, with measured pacing.",
     "language": "en",
     "n_samples": 1,
     "json_config": {"cfg_scale": 10.0}
   }
   ```

   The response is `{"embeddings": [{"embedding_id": "vox_emb_...", "ready": false,
   "expires_at": "..."}]}`. Unpromoted candidates expire after 30 days.

2. Poll `GET /voice-generator/embeddings?embedding_id=<vox_emb_id>` until that
   embedding reports `ready: true`. An unknown id returns `200` with an empty
   list, so check the list before reading it. Use a finite deadline and a
   modest interval.

3. Render an audition through `POST /post/speech/tts`:

   ```json
   {
     "text": "It is lovely to meet you. Let me walk you through it.",
     "voice_id": "<vox_emb_id>",
     "output_format": "wav",
     "only_audio": true
   }
   ```

4. Let the user hear the audition. Ask whether to keep it or create one more
   candidate. Never silently generate a batch of paid candidates.

5. After explicit approval, promote it with `POST /voices/from-embedding`:

   ```json
   {
     "voxium_embedding_id": "<vox_emb_id>",
     "name": "Arthur",
     "description": "Calm, older, reassuring, softly textured, with measured pacing."
   }
   ```

   Keeping a candidate is free and clears its expiry. The `201` response's
   `uid` is the permanent `voice_id`; `409` means it was already promoted.

6. Store the `uid` as `GRADIUM_VOICE_ID` or in a secret-backed avatar profile.
   The render path must reuse this id; it must not design a voice per render.

7. Delete rejected, failed, timed-out, or interrupted candidates with
   `DELETE /voice-generator/embeddings/<vox_emb_id>` once their id is known.
   Put cleanup in a `finally`-equivalent path, but never delete a promoted voice.

## Voice fit and audition text

Ground suggestions in visible creative qualities, not sensitive identity
inferences. A useful voice prompt covers vocal age range, warmth or brightness,
texture, pace, energy, intended language, and accent only when requested.

Keep the Voice Design prompt at or below 500 characters and audition text at or
below 100 characters. Use a neutral line that exercises the intended language,
pace, and emotional range without being the production script. The script
ships one default audition line per supported language.

Because MiniMax lip-syncs at most 14.8 seconds, the pacing you approve in the
audition determines how many words fit. A measured voice speaks roughly 30
words in 14 seconds; a brisk one about 40. Say so when the user drafts the
script.

## Operational guardrails

- Supported design languages are `en`, `fr`, `de`, `es`, and `pt`.
- Use the same Gradium TTS model and tuning for audition and final speech.
- Put finite timeouts around generation, polling, audition, promotion, and
  cleanup; cap downloaded audition bytes.
- Check response status and schema before consuming an embedding id or voice id.
- Do not log keys, raw upstream error bodies, or full user-authored scripts.
- Save auditions outside the public web root and exclude them from version
  control. Apply a short retention policy after approval.
- Tests must mock the lifecycle and assert that rejection and interruption clean
  up the temporary candidate.

Gradium documents these endpoints at
https://docs.gradium.ai/guides/voices/voice-design,
https://docs.gradium.ai/api-reference/endpoint/generate-voice,
https://docs.gradium.ai/api-reference/endpoint/create-voice-from-embedding, and
https://docs.gradium.ai/api-reference/endpoint/tts-post.
