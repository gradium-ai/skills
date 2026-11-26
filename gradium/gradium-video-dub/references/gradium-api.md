# Gradium API cheat sheet (for video dubbing)

Base `https://api.gradium.ai/api`, header `x-api-key: $GRADIUM_API_KEY`. Docs index: https://docs.gradium.ai/llms.txt
Languages everywhere: `en`, `fr`, `de`, `es`, `pt`. Limit: 5 concurrent sessions per account.

## Live translation (speech-to-speech)
`wss://api.gradium.ai/api/speech/s2s`. First message:
```json
{"type":"setup","model_name":"s2s-translate","stt_model_name":"stt-translate","tts_model_name":"default",
 "input_format":"pcm","output_format":"pcm","voice_id":"<voice>","json_config":{"target_language":"en"}}
```
- Input `pcm`: 24 kHz s16 mono, send `{"type":"audio","audio":<b64>}` in 1920-sample (80 ms) chunks, then `{"type":"end_of_stream"}`.
- Output: `audio` (b64, 48 kHz s16 mono) and `text` (`text`, `start_s`, `stop_s`) messages, then `end_of_stream`.
- `text` timestamps are on the output audio timeline, which runs longer than the source.
- The stream may end before the final sentence is out: append ~8 s of silence to the input.
- Docs say `voice_id` must be a target-language voice. A source-language clone also works and keeps the speaker's accent.

## Voices
- Clone: `POST /voices/` multipart `audio_file`, `name`, `language` (of the sample), optional `start_s`, `enhance`, `timeout_s`. Returns `{"uid": ...}`. ≥10 s of clean speech.
- List: `GET /voices/?include_catalog=true&locale=en-us&gender=female&limit=100`. Get one: `GET /voices/{uid}`.
- Each clone or saved voice uses a custom-voice slot.

## Voice Localization (change language/accent of an existing voice)
- `GET /voice-generator/available-accents` (fixed list, e.g. en: General American, Standard British, Irish, Scottish, Australian, Indian English; no free-text accents).
- `POST /voice-generator/localize` `{"src_voice","target_language","accent","gender","n_samples":1-5}` → `embeddings[].embedding_id` (`vox_emb_...`).
- Poll `GET /voice-generator/embeddings?embedding_id=...` until `ready`; audition with REST TTS; keep with `POST /voices/from-embedding` `{"voxium_embedding_id","name","description"}` → `uid`.

## TTS
SDK: `await client.tts(setup={"model_name":"default","voice_id":v,"output_format":"pcm"}, text=...)` → `raw_data` (48 kHz s16 mono), `sample_rate`, `text_with_timestamps`.
REST: `POST /speech/tts` `{"text","voice_id","model_name":"default","output_format":"wav","only_audio":true}`.
Speed: `json_config: {"padding_bonus": -4.0..4.0}` (negative = faster).

## STT
SDK: `await client.stt({"model_name":"default","input_format":"pcm"|"wav","json_config":{"language":"fr"}}, audio, sample_rate=24000)`
→ `text`, `text_with_timestamps[]` (`text`, `start_s`, `stop_s`). Set `language` (or `"any"`).
