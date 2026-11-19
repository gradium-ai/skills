---
name: gradium-voice-casting
description: Find and audition existing Gradium voices for a character, narration, or other speaking role using the Gradium MCP.
---

# Find a voice

Use only the production Gradium MCP at `https://mcp.gradium.ai/mcp`. A manually configured connection is valid if it uses that exact URL. If you cannot verify the URL, direct the user to the production connection in the host instead of calling an unverified tool.

Discover the connected Gradium MCP's `list_voices`, `get_voice`, and, when available, `generate_speech` tools. Use their actual schemas and preserve exact IDs.

Use `list_voices` to browse the catalog or the organization's own voices. Language, locale, gender, and use case are exact filters; `search` matches a name or ID substring, not a natural-language description. Filter only on attributes the user actually specified; compare returned descriptions and tags with their brief. Follow `next_skip` with unchanged filters when needed, and relax filters if there are no suitable results. Do not invent attributes or voice IDs. `get_voice` inspects a known ID; it does not select a voice. Catalog `rank` below 1 marks flagship voices the Gradium team picked by hand, 1 means recommended, above 1 is the rest of the catalog, and `null` means unranked or custom. `list_voices` returns the best rank first; when voices match the brief equally well, prefer the lower rank.

Return a concise shortlist with evidence from metadata and exact IDs. Skip pending voices for generation. If the request includes an audition, use `generate_speech` with the same short, language-appropriate text for each candidate. Generation spends credits; listing and inspection do not. Before the first audition, check the [audio save path](../gradium-speech-generation/SKILL.md#before-generating-audio). Apply the audio delivery checks in [speech generation](../gradium-speech-generation/SKILL.md#verify-audio-delivery) after each call, before generating the next audition. Label each verified file with its voice name. If speech generation is unavailable, provide metadata-based choices and say auditioning is unavailable.

Omit `org_uid` when the user has yet to select an organization. If the tool returns `organization_selection_required`, show the listed organization names and ask the user which one to use before calling again with its `org_uid`. If selection is cancelled, stop and wait for the user. Pass the resolved organization to subsequent calls. Support English, French, German, Spanish, and Portuguese where the returned catalog supports the requested language; never assume a voice's language or accent from its name.
