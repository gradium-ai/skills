# Gradium Skills

Reusable Agent Skills for building with [Gradium](https://gradium.ai) —
text-to-speech, speech-to-text, speech-to-speech translation, voice
cloning, pronunciation control, talking-video, and live-avatar workflows.

Skills in this repo follow the `SKILL.md` package format: each skill
lives in its own folder with a required `SKILL.md` file and optional
resources such as `references/` and `scripts/`. Every endpoint, field
name, and behavior note was verified against the live Gradium API, and
the bundled scripts are tested end to end.

## Available skills

| Skill | Purpose |
| --- | --- |
| `gradium-text-to-speech` | Generate speech: one-shot and streaming synthesis, voice settings, word-level timestamps, pauses, pronunciation fixes. Ships `scripts/tts.py` and the flagship voice catalog. |
| `gradium-speech-to-text` | Transcribe audio: batch and realtime, semantic VAD turn-taking, keyword boosting, subtitle (SRT) output. Ships `scripts/transcribe.py`. |
| `gradium-speech-translation` | Live speech-to-speech translation, dubbing workflows, re-voicing. Ships `scripts/s2s.py`. |
| `gradium-voice-cloning` | Clone voices from a short sample and manage the voice library. |
| `gradium-pruna-video` | Talking videos: drive Pruna AI video models with Gradium-generated speech. Ships `scripts/voice_video.py`. |
| `gradium-live-avatar-agent` | Build a realtime voice agent with Gradium Voice Design/STT/TTS, LiveKit orchestration, and a LemonSlice animated avatar. |
| `gradium-api` | Wire-level REST + WebSocket reference for any language or edge runtime. |
| `gradium-sdk` | Python SDK (`pip install gradium`): async client, call shapes, result objects, CLI. |
| `gradium-docs` | Maps any task to the exact page of docs.gradium.ai. |
| `gradium-setup-api-key` | Key setup and validation, safe key handling, browser-token pattern. |
| `migrate-to-gradium` | Switch voice API integrations from other providers to Gradium. |

## Requirements

- A Gradium API key in the `GRADIUM_API_KEY` environment variable
  (the `gradium-setup-api-key` skill walks through setup and validation).
- `gradium-pruna-video` additionally needs a `PRUNA_API_KEY`.
- `gradium-live-avatar-agent` additionally needs a `LEMONSLICE_API_KEY`
  and LiveKit credentials. It uses LiveKit Inference for the default LLM
  when credits are available, or a user-provided LLM endpoint otherwise.
- Bundled scripts use Python 3.10+ with `requests` (plus `websockets`
  for streaming); `ffmpeg` is recommended for audio conversion.

## Install for Claude Code

Copy any skill folder into your Claude skills directory:

```bash
mkdir -p ~/.claude/skills
cp -R gradium-text-to-speech ~/.claude/skills/
```

Then prompt Claude Code with requests such as:

```text
Generate a voiceover for this script with a British male voice, slightly slower.
```

## Install for Codex

Copy the skill folder into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
cp -R gradium-text-to-speech ~/.codex/skills/
```

Then prompt Codex with requests such as:

```text
Use $gradium-text-to-speech to narrate docs/intro.md into intro.wav.
```

## Quick start without an agent

The bundled scripts run standalone:

```bash
export GRADIUM_API_KEY=...
python gradium-text-to-speech/scripts/tts.py "Hello, world!" --out hello.wav
python gradium-speech-to-text/scripts/transcribe.py hello.wav --language en
python gradium-speech-translation/scripts/s2s.py hello.wav --to fr \
    --voice YhIHaAfQ0cQPDV9R --out bonjour.wav
```

`examples/generate.sh` regenerates the full demo set (speech styles,
French dub, re-voicing, subtitles, optional talking video) and doubles
as an end-to-end smoke test of the skills.

## Platform capabilities at a glance

- **Languages:** English, French, German, Spanish, Portuguese
- **TTS:** 48 kHz WAV/PCM/Opus output, telephony codecs, word-level
  timestamps, WebSocket streaming, `<flush>` / `<break>` tags,
  pronunciation dictionaries
- **STT:** batch + realtime, semantic VAD turn-taking signals, keyword
  boosting (up to 500 terms), adaptive latency control
- **S2S:** live translation between the five languages with any
  target-language voice, including clones
- **Voices:** 80+ flagship voices plus cloning from ~10 s of audio
- **Auth:** `x-api-key` header server-side; short-lived tokens for
  browser/mobile WebSockets

## Notes

- Keep one canonical skill folder in this repo.
- Do not create separate Codex and Claude copies unless a tool requires
  provider-specific metadata.
- `migrate-to-gradium/agents/openai.yaml` is Codex UI metadata. Other
  agents can ignore it and read `SKILL.md` plus the referenced files.

## Support

- Docs: [docs.gradium.ai](https://docs.gradium.ai) (agent-friendly:
  every page is fetchable as markdown, index at
  [docs.gradium.ai/llms.txt](https://docs.gradium.ai/llms.txt))
- Contact: support@gradium.ai

## License

[MIT](LICENSE)
