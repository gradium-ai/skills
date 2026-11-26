---
name: gradium-speech-generation
description: Generate spoken audio from supplied text with the Gradium MCP, including narration and multi-part dialogue with existing voices. Use for saving or replaying a Gradium WAV and for local playback on macOS.
---

# Generate speech

Use only the production Gradium MCP at `https://mcp.gradium.ai/mcp`. A manually configured connection is valid if it uses that exact URL. If you cannot verify the URL, direct the user to the production connection in the host instead of calling an unverified tool.

Use the connected Gradium MCP's `generate_speech`, checking the discovered schema. If unavailable, explain that the server has not exposed speech generation. Preserve the user's text, removing only formatting that should not be spoken. Use the default voice when no preference is given; for a particular style or language, use `list_voices` and, if needed, `get_voice` to choose an actual non-pending voice. Preserve the voice ID and selected organization across related calls. Omit `org_uid` when the user has yet to select an organization. If the tool returns `organization_selection_required`, show the listed organization names and ask the user which one to use before calling again with its `org_uid`. If selection is cancelled, stop and wait for the user.

Each call takes at most 9,000 characters and returns an MCP `audio/wav` content block, subject to a 120-second timeout and 16 MiB audio limit. Generation consumes credits. Do not automatically retry a failed generation; explain the failure and let the user choose whether to retry. Do not claim the tool supports controls for language, speed, emotion, output path, or streaming: its inputs are text, voice ID, and organization. Use an appropriate existing voice for English, French, German, Spanish, or Portuguese when supported by catalog metadata.

For longer work, split at paragraph, then sentence, boundaries into parts under about 1,200 characters, because the 16 MiB cap is about 2 minutes 55 seconds of 48 kHz mono audio. Never split mid-sentence, keep role-to-voice assignments stable, and track successful segments so revisions do not regenerate unchanged audio. Joining segments requires a suitable local audio tool. Do not claim to have listened to or assembled audio without doing so.

## Before generating audio

If the host saves tool audio as a file or attachment, use its native path. In Codex CLI, an ordinary tool call and a Code Mode cell can both receive only an audio placeholder. For a user-authorized generation on a local CLI without native file delivery, run the bundled [save_wav.py](scripts/save_wav.py) **as the first and only generation call**. Use the same working directory and configured Gradium connection. The helper calls the hosted MCP through Codex and saves the WAV before the model sees the response.

Use the organization already selected in the chat. If unknown, call `get_credits` for organization selection, use the sole eligible org automatically, or ask which org to use. Stop if none are eligible. Pass the exact connected server name, organization UID, optional `--voice-id`, and a new output filename. Supply the user's exact speech text on stdin. Run from the current workspace and resolve the script relative to this skill file. For example:

```sh
printf '%s' 'Hello world' | python3 "/absolute/path/to/skill/scripts/save_wav.py" --server SERVER --org-uid ORG_UID --output hello.wav
```

Use the normal permission flow for this specific billable invocation. Honor any MCP tool denial or restriction. If the authorized connection, CLI, or execution permission is unavailable, stop before generation. After an omission, timeout, or uncertain outcome, ask before starting another paid generation. For replay or a failed player, use the existing file.

## Verify audio delivery

Use the WAV path returned for this generation, or save the WAV bytes if the client exposes them. Before offering the file as playable, run `ffmpeg -nostdin -v error -xerror -i "$file" -map 0:a:0 -f framemd5 -`. Require a successful exit and at least one decoded frame with positive duration (the fourth comma-separated field of a non-comment row). If strict decoding fails because a streamed Gradium WAV has placeholder RIFF and data lengths, make a separate copy with standard sizes using `ffmpeg -nostdin -v error -i "$file" -map 0:a:0 -c:a copy "$normalized_file"` and run the strict check on that copy. Use it only if verification passes. A WAV header or successful MCP status alone does not prove the file contains audio. Link or attach the verified file. Claim playback only if playback occurred.

If the client returns only `<audio content omitted because you do not support audio input>` and metadata, explain that it did not expose the recording. If the file is missing, decoding fails, or you cannot verify decoded samples, explain the specific delivery problem. Stop further synthesis in this request, including remaining auditions or dialogue segments. Keep any previously verified files. Do not retry automatically, substitute another service, or tell the user to play unverified audio.

## Play or replay on macOS

For a replay request, locate the existing WAV and verify it, then play it without an MCP call. On macOS, play a newly generated WAV by default unless the user requested only a file. For multi-part audio, play the verified joined file when available, or offer the verified segment files. On other platforms, deliver the verified file when local playback is unavailable.

Use `/usr/bin/afplay "$file"` as a standalone command with the verified path. If speaker access is blocked, request approval for playback and retry the same file. If permission is declined or playback fails, give the verified file path and report the issue. Report playback success only after the player exits successfully.
