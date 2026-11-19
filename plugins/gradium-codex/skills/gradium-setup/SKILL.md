---
name: gradium-setup
description: Connect or troubleshoot the hosted Gradium MCP for voice discovery, speech generation, and credits.
---

# Connect to Gradium

Use only the production Gradium MCP at `https://mcp.gradium.ai/mcp`. A manually configured connection is valid if it uses that exact URL. If you cannot verify the URL, direct the user to the production connection in the host instead of calling an unverified tool.

Use the host’s connection or sign-in flow. In Codex CLI, the user signs in with `codex mcp login gradium`, which opens the Gradium Studio sign-in page in the browser, and `codex mcp list` shows `OAuth` for `gradium` once signed in. Discover the actual tools: `list_voices`, `get_voice`, `get_credits`, and, when enabled, `generate_speech`. Tool prefixes depend on the host. A successful plugin installation alone does not establish a connection or successful tool call.

If a tool is missing, inspect the connection and available tool list; `generate_speech` may be disabled on the server. If sign-in or a tool call fails, report the observed error and direct the user to the host's connection settings or Gradium support. Do not ask for secrets in chat or claim that OAuth, credentials, or audio playback work without verifying them. The server may require an active organization membership; ask the user to choose an organization when multiple are available.
