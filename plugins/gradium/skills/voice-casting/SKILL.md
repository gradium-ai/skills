---
name: voice-casting
description: Finds, compares, and shortlists existing Gradium voices for a narrator, character, assistant, or other speaking role, using the hosted Gradium MCP's list_voices and get_voice tools and the metadata they return. Use when the user wants a Gradium voice that sounds a certain way, asks for voice recommendations, asks which voices exist for a language or accent, or wants details on a voice ID.
allowed-tools: mcp__plugin_gradium_gradium__list_voices mcp__plugin_gradium_gradium__get_voice
---

# Gradium voice casting

Use only the production Gradium MCP at `https://mcp.gradium.ai/mcp`. A manually configured connection is valid if it uses that exact URL. If you cannot verify the URL, direct the user to the production connection in the host instead of calling an unverified tool.

Pick voices only from the metadata the server returns. The server filters exactly and does no semantic matching. You compare the results with the user's brief.

Use the tools `mcp__plugin_gradium_gradium__list_voices` and `mcp__plugin_gradium_gradium__get_voice`. Both are free. For a manually configured production connection, the tools are named after that entry, such as `mcp__gradium__list_voices`.

## Rules

- Copy voice IDs exactly as returned; they are case-sensitive. Never invent a voice ID, name, or attribute.
- Never infer a voice's language, accent, gender, or age from its name.
- A quality such as "warm" counts as matched only when the voice's `description` or a tag says so. Missing metadata is not evidence either way.
- Exclude voices with `is_pending: true`. They cannot generate speech yet.
- Pass the same `org_uid` to every call. If a tool returns `status: organization_selection_required`, show the user the organization names it lists, ask which to use, and call again with that `org_uid`. If it returns `selection_cancelled`, stop and ask the user. Never pick an organization yourself.

## list_voices

- `language`: a two-letter code such as `fr`. Covers every accent and region of the language.
- `locale`: an exact locale such as `fr-fr`, `fr-sn`, or `fr-fr-x-southern`.
- `gender` and `use_case`: exact, case-insensitive matches. Values include `male` and `female`, and `narration`, `customer service`, and `conversational`. These lists are not complete.
- `search`: a substring of a voice name or ID. It is not a description search.
- `source`: `catalog`, the default, or `organization` for the organization's own custom voices. An empty organization list means it has no discoverable custom voices.
- `limit`: use 20 to 30. A 50-voice page exceeds Claude Code's inline result size and arrives as a file.
- Filters combine with AND. Follow `next_skip` with the same filters until it is `null` or you have enough candidates.

Each voice has `voice_id`, `name`, `description`, `language`, `locale`, `gender`, `age`, `translations`, `is_catalog`, `rank`, `is_pending`, and `tags`. Each tag is a `{category, value}` pair. Categories seen include `region`, `gender`, `age`, `use-case`, `emotion`, `pitch`, `pace`, `texture`, and `accent`.

`rank` orders catalog voices: below 1 marks flagship voices the Gradium team picked by hand, 1 means recommended, and above 1 is the rest of the catalog. `null` means unranked or custom. `list_voices` returns the best rank first. When several voices match the brief equally well, prefer the lower rank.

## get_voice

`get_voice(voice_id, org_uid?)` returns the same fields for one known ID. It does not search or rank. `Voice not found in this organization.` means the ID is wrong or deleted, or belongs to another organization.

## Workflow

1. Turn only the attributes the user stated into filters: language, locale or accent, gender, and use case. Keep subjective qualities for comparison.
2. Call `list_voices`. If too few voices fit, relax the narrowest filter (locale before language, use case before gender) and say you did.
3. Compare each candidate's description and tags with the brief. Break ties with the lower `rank`.
4. Return a shortlist of two to four voices. For each, give its name, exact `voice_id`, locale, gender, and age, and quote the description or tag words that match the brief. Note any part of the brief that no candidate's metadata supports.

## Auditions

Generate audio only when the user asks to hear candidates, because each generation uses credits. Make one `generate_speech` call per voice with the same short line in the voice's language. Do not retry failures automatically. Before the first audition, check the [audio save path](../speech-generation/SKILL.md#before-generating-audio). Apply the audio delivery checks in [speech generation](../speech-generation/SKILL.md#verify-audio-delivery) after each call, before generating the next audition. Label each verified file with its voice name. You cannot hear the audio, so let the user judge how it sounds. If `generate_speech` is not available, say auditions are unavailable on this server.
