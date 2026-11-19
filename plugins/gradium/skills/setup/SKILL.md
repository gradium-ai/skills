---
name: setup
description: Connects Claude Code to the hosted Gradium MCP, checks which Gradium tools are available, and diagnoses Gradium sign-in, membership, and organization errors. Use when the user asks to set up or sign in to Gradium, when Gradium tools are missing or need authentication, or when a Gradium tool returns an access error.
allowed-tools: mcp__plugin_gradium_gradium__get_credits
---

# Gradium setup

Use only the production Gradium MCP at `https://mcp.gradium.ai/mcp`. A manually configured connection is valid if it uses that exact URL. If you cannot verify the URL, direct the user to the production connection in the host instead of calling an unverified tool.

The plugin's MCP server `gradium` (`https://mcp.gradium.ai/mcp`) appears in `/mcp` as `plugin:gradium:gradium`, with tools named `mcp__plugin_gradium_gradium__<tool>`. Claude Code may use a manually configured production connection in preference to the plugin connection. The tool prefix then follows the connection name, such as `mcp__gradium__<tool>`.

## Tools the server can expose

- `get_credits`, `list_voices`, `get_voice`: free, and always present once the user is signed in.
- `generate_speech`: uses credits, and is present only when the server has speech enabled.

The Gradium MCP beta has no transcription, translation, voice cloning, voice design, or API-key tools. Say so instead of improvising them.

## Check the connection

1. Look for the Gradium tools above in your tool list.
2. If none are present, the server needs sign-in. Tell the user to run `/mcp`, select `plugin:gradium:gradium`, choose **Authenticate**, and sign in in the browser with their Gradium Studio account. Running `claude mcp login plugin:gradium:gradium` from a shell does the same.
3. If they are present, call `get_credits` (free) to confirm the connection works. Then report which tools are available and whether `generate_speech` is among them.

Only a successful tool call proves the connection works. Never ask for or print tokens, passwords, client secrets, or callback URLs.

## Errors

Quote the tool's error, then explain it from this table. Do not guess at other causes.

| Error | Meaning | Next step |
| --- | --- | --- |
| Server needs authentication, or HTTP 401 | Not signed in, or the sign-in expired or was revoked | Re-authenticate in `/mcp` |
| `Sign in to Gradium Studio first.` | This account has no active Gradium Studio user | Sign in to Studio at https://studio.gradium.ai once with the same account, then re-authenticate in `/mcp` |
| `No active membership for this organization.` | The `org_uid` is not one of the user's organizations, or the account has none | Call `get_credits` and use an `org_uid` from `organizations` |
| `status: organization_selection_required` | The user has several organizations and none was chosen | Show the listed names, ask which to use, and call again with its `org_uid` |
| `selection_cancelled` | The user cancelled the organization form | Ask the user before calling again |
| `generate_speech` missing, or `TTS is not enabled on this MCP server.` | Speech is disabled on this server | Say so; voices and credits still work |
