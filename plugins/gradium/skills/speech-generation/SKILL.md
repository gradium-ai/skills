---
name: speech-generation
description: Generates spoken WAV audio from text with the hosted Gradium MCP's generate_speech tool, covering read-alouds, narration, voiceover, long scripts, and dialogue with several existing voices. Use when the user asks Gradium to say, read aloud, voice, narrate, or synthesize text, to create a speech audio file, or to replay an existing Gradium WAV.
---

# Gradium speech generation

Use only the production Gradium MCP at `https://mcp.gradium.ai/mcp`. A manually configured connection is valid if it uses that exact URL. If you cannot verify the URL, direct the user to the production connection in the host instead of calling an unverified tool.

Use the tool `mcp__plugin_gradium_gradium__generate_speech`. For a manually configured production connection, the tool is named after that entry, such as `mcp__gradium__generate_speech`. If neither appears, speech is not enabled on this server: say so.

## Rules

- Every call uses the organization's credits. Never retry a failed call automatically. Report the error and let the user decide.
- You cannot hear the audio. Never describe how it sounds or claim it is correct beyond what you checked.
- Keep the user's text. Remove only formatting that should not be spoken, such as Markdown symbols. Ask before rewriting, translating, or expanding it.
- Pass the same `org_uid` to every call. If a tool returns `status: organization_selection_required`, show the user the organization names it lists, ask which to use, and call again with that `org_uid`. If it returns `selection_cancelled`, stop and ask the user. Never pick an organization yourself.

## Inputs

The tool takes only these inputs:

- `text`: required, 1 to 9,000 characters.
- `voice_id`: an exact ID from `list_voices` or `get_voice` with `is_pending: false`. Defaults to `default`.
- `org_uid`: needed only when the user has several organizations. Asking for an organization uses no credits.

There are no settings for language, model, speed, emotion, format, or output path. Language comes from the text and the voice.

Choose the voice in this order:
1. The `voice_id` the user gave.
2. Otherwise, if the user described a voice, one found with `list_voices` and justified by its metadata.
3. Otherwise `default`. For text that is not in English, prefer a catalog voice whose `language` matches.

Output is WAV at 48 kHz, 16-bit, mono. Each call is capped at 16 MiB of audio, about 2 minutes 55 seconds, and 120 seconds of server time. Keep each call to about 1,200 characters or less.

## Before generating audio

Confirm the client can save MCP audio as a WAV before calling `generate_speech`. If the client cannot expose a file or raw WAV bytes you can save, explain the delivery issue before spending credits.

## Verify audio delivery

Claude Code can save returned audio in its temporary `tool-results` directory and provide the WAV path. If the user wants to keep it, copy the verified file to the requested project location.

Use the WAV path returned for this generation, or save the WAV bytes if the client exposes them. Before offering the file as playable, run `ffmpeg -nostdin -v error -xerror -i "$file" -map 0:a:0 -f framemd5 -`. Require a successful exit and at least one decoded frame with positive duration (the fourth comma-separated field of a non-comment row). If strict decoding fails because a streamed Gradium WAV has placeholder RIFF and data lengths, make a separate copy with standard sizes using `ffmpeg -nostdin -v error -i "$file" -map 0:a:0 -c:a copy "$normalized_file"` and run the strict check on that copy. Use it only if verification passes. A WAV header or successful MCP status alone does not prove the file contains audio. Link or attach the verified file. Claim playback only if playback occurred.

If the client returns only `<audio content omitted because you do not support audio input>` and metadata, explain that it did not expose the recording. If the file is missing, decoding fails, or you cannot verify decoded samples, explain the specific delivery problem. Stop further synthesis in this request, including remaining auditions or dialogue segments. Keep any previously verified files. Do not retry automatically, substitute another service, or tell the user to play unverified audio. If you cannot check the file at all, for example because no tool can read that path, say the recording was not verified, give the path only as the location the client reported, and do not describe the file as present, its size as confirmed, or the audio as playable.

## Play or replay a file

On macOS, play a newly generated WAV by default, unless the user asked only for a file or to skip playback. The Gradium MCP's `generate_speech` description asks for the same. For multi-part audio, play the verified joined file when there is one, or offer the verified segment files. On other platforms, deliver the verified file. For replay, locate and verify the existing WAV, then use it without an MCP call. On macOS, run `/usr/bin/afplay "$file"` as a standalone command with the verified path. If speaker access is blocked, request permission and retry the same file. If permission is declined or playback fails, provide the verified path and report the issue. Report playback success after the player exits successfully.

## Long text and dialogue

1. Split the text at paragraphs, then at sentences, into chunks under about 1,200 characters. Never split mid-sentence.
2. For dialogue, assign one voice per speaker, show the user the assignment, and keep it fixed. Generate each turn as its own call.
3. Tell the user how many calls you will make before starting.
4. Track each segment's order, text, voice, and file. When text is revised, regenerate only the changed segments.
5. If the user wants one file and `ffmpeg` is available, join copies of the segments in order with the concat demuxer and `-c copy`. Otherwise deliver the ordered files. Joining is a local step, not a Gradium feature.

## Errors

| Error | Meaning |
| --- | --- |
| `Voice is still processing. Choose another voice.` | The voice is pending |
| `Voice not found in this organization.` | The ID is wrong or deleted, or belongs to another organization |
| `Generated audio is too large for MCP. Use shorter text.` | Over 16 MiB of audio. Split the text |
| `Speech generation timed out.` | Over 120 seconds. Split the text or try later |
| `Speech generation failed (HTTP 402).` | The organization is out of credits. Suggest checking `get_credits` |
| `Provide nonblank text to speak.` | The text was empty or only spaces |
| `Speech generation failed (HTTP <code>).` with another code, `Speech generation failed on compute.`, or `Compute returned incomplete or invalid WAV audio.` | A server-side failure. Report it |
| `Sign in to Gradium Studio first.` or an authentication error | The user needs to sign in through `/mcp` (`plugin:gradium:gradium` → **Authenticate**) |
