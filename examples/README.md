# Examples

The audio examples are generated fresh from the live API, which also
makes this a one-command smoke test of the audio skills. Finished video
examples live in [pruna-designed-avatar/](pruna-designed-avatar/).

Generate the audio set:

```bash
export GRADIUM_API_KEY=...
./generate.sh              # speech, dubbing, re-voicing, subtitles
./generate.sh --video      # + Pruna talking-avatar video (needs PRUNA_API_KEY
                           #   and a portrait.png in this folder)
```

What it produces:

| File | Skill exercised | What to listen/look for |
| --- | --- | --- |
| `example_tts.wav` | gradium-text-to-speech | Baseline synthesis, default voice |
| `example_tts_fast.wav` | gradium-text-to-speech | Faster pace; "Dr." / "5th" / "$20" expanded by rewrite rules |
| `example_captions.srt` | gradium-speech-to-text | Word-timestamp subtitles, "Gradium" spelled right via keyword boost |
| `example_dub_fr.wav` | gradium-speech-translation | The English line re-spoken in French |
| `example_revoice.wav` | gradium-speech-translation | Same English words, different voice (re-voicing) |
| `example_avatar.mp4` | gradium-pruna-video | Portrait lip-syncing the Gradium-generated line |

Generated files are gitignored; only this README and `generate.sh` are
tracked. The audio steps cost a few cents of Gradium credits; the
optional video step costs ~$0.15 of Pruna credits.
