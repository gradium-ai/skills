# Gradium MCP plugins for Codex and Claude Code

This folder ships the `gradium` plugin for Codex and Claude Code, with four skills. Both use the production Gradium MCP at `https://mcp.gradium.ai/mcp`.

Each client installs the `gradium` plugin from its own marketplace manifest at the root of this repository.

Full guide: [docs.gradium.ai/integrations/mcp](https://docs.gradium.ai/integrations/mcp)

```
skills/
├── .agents/plugins/marketplace.json    Codex marketplace
├── .claude-plugin/marketplace.json      Claude Code marketplace
├── plugins/gradium-codex/               Codex plugin and four skills
└── plugins/gradium/                     Claude Code plugin
    ├── .claude-plugin/plugin.json       plugin "gradium" v0.2.0
    ├── .mcp.json                        remote HTTP server "gradium" → mcp.gradium.ai/mcp
    ├── skills/
    │   ├── setup/                       /gradium:setup             sign-in, tool check, error meanings
    │   ├── credits/                     /gradium:credits           balances and organization choice
    │   ├── voice-casting/               /gradium:voice-casting     find and compare voices from metadata
    │   └── speech-generation/           /gradium:speech-generation generate WAV, long text, dialogue
    └── evals/                           claude plugin eval suite (5 cases, mocked Gradium tools)
```

The skills follow Claude Code's [skills guide](https://code.claude.com/docs/en/skills) and the [skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices):
- Each skill has a third-person description stating what it does and when to use it.
- Each skill is self-contained, with its key rules near the top.
- The Claude Code plugin uses `allowed-tools` for free credit checks and voice lookups. Speech generation uses organization credits and follows the client's approval settings.

## What the hosted MCP provides

| Tool | Purpose | Cost |
| --- | --- | --- |
| `get_credits` | Remaining and allocated credits, plan, billing period, and rollover date per organization | Free |
| `list_voices` | Browse catalog or organization voices. Filters for language, locale, gender, and use case are exact; `search` matches names and IDs only | Free |
| `get_voice` | Metadata for one known voice ID | Free |
| `generate_speech` | Text (up to 9,000 characters) and a voice ID in, WAV out. Exposed only when the server has speech enabled | 1 credit per character |

The beta has no transcription, translation, voice cloning, or API-key access, and no settings for speed, emotion, or format. Voice casting compares the tool's descriptions and tags with your request. Use the Gradium SDK or API when your app needs streaming speech, transcription, or voice cloning.

## Install in Codex

Run:

```bash
codex plugin marketplace add gradium-ai/skills
codex plugin add gradium@gradium
```

Start a new Codex session and sign in to the Gradium MCP when prompted. The Codex package is in `plugins/gradium-codex` and connects to `https://mcp.gradium.ai/mcp`.

The bundled speech-generation skill handles saving, playback, and replay. On macOS it uses `afplay` for local playback. If your Codex CLI session cannot save the MCP audio, start a new session with `codex --enable code_mode` on a version that supports it. The skill checks for a way to save the WAV before synthesis. Speech generation and auditions use FFmpeg to verify saved WAVs.

## Install in Claude Code

You need:
- Claude Code 2.1.281 or later
- a [Gradium Studio](https://studio.gradium.ai) account that belongs to an active organization

1. Add the marketplace and install the plugin:

   ```bash
   claude plugin marketplace add gradium-ai/skills
   ```

   ```bash
   claude plugin install gradium@gradium
   ```

   Or, inside Claude Code, run `/plugin marketplace add gradium-ai/skills`, then `/plugin install gradium@gradium`.
2. Start a new Claude Code session.

To get later changes, run `claude plugin marketplace update gradium`, then `claude plugin update gradium@gradium`, and start a new session.

To try a local checkout without installing it:

```bash
claude --plugin-dir /path/to/skills/plugins/gradium
```

### If you already configured the production MCP manually

Claude Code connects each server URL only once. A manually configured production connection takes priority over the plugin connection. If `claude mcp list` already shows `https://mcp.gradium.ai/mcp` (for example as `gradium`), Claude Code uses that entry and does not connect the plugin's copy. The skills still work, because the tool names are the same apart from the prefix (`mcp__gradium__…` instead of `mcp__plugin_gradium_gradium__…`).

To use the plugin's own connection, remove your entry first. This also discards that entry's sign-in.

```bash
claude mcp remove gradium -s user
```

## Sign in

1. In Claude Code, run `/mcp`.
2. Select **plugin:gradium:gradium**. It shows as needing authentication until you sign in.
3. Choose **Authenticate**. Your browser opens the Gradium Studio sign-in page (studio.gradium.ai). Sign in with your Gradium Studio account, allow access, then return to Claude Code. If the browser cannot get back to Claude Code, paste the full callback URL from the address bar into the prompt in `/mcp`.

You can also sign in from your shell. It opens the browser the same way, and finishes on its own once you approve access there:

```bash
claude mcp login plugin:gradium:gradium
```

Never paste tokens or callback codes into the chat. Use **Clear authentication** in `/mcp` to sign out.

## Check the tools

In `/mcp`, the server should show as connected with `get_credits`, `get_voice`, `list_voices`, and, when speech is enabled, `generate_speech`. Then ask:

> /gradium:setup Check my Gradium connection and list the tools you can use.

Claude should make one free call (`get_credits`) and report which tools are available, including whether `generate_speech` is enabled.

## Test prompts

| # | Prompt | Expected behavior | Credits |
| --- | --- | --- | --- |
| 1 | How many Gradium credits do I have left, and when do they roll over? | Uses the `credits` skill and `get_credits`. Reports organization, remaining out of allocated credits, plan, and rollover date, with no invented values | Free |
| 2 | Using Gradium, find me a warm French voice for narrating an audiobook. Give me a shortlist with voice IDs. | Uses `voice-casting`. Filters `list_voices` by `language=fr` (and maybe `use_case=narration`), follows `next_skip`, skips pending voices, and lists exact IDs, quoting the description or tag words that justify each pick | Free |
| 3 | Show me the details for voice `<an ID from prompt 2>`. | Calls `get_voice` with the exact ID and reports only returned fields | Free |
| 4 | Show me the voices that belong to my organization. | `list_voices` with `source=organization`. An empty result is reported as "no custom voices", not as an error | Free |
| 5 | Use Gradium to say "Hello from Gradium." with the default voice, and save it as `audio/hello.wav`. | One `generate_speech` call, no automatic retry. Claude verifies that the WAV decodes before offering it, then saves it at the requested path when permitted | 1 credit per character |
| 6 | Audition two of those French voices with the same short sentence. | Uses identical text and verifies each WAV before generating the next audition | Small |
| 7 | Generate speech with voice ID `not-a-real-voice`. | Reports `Voice not found in this organization.` and does not retry or substitute a voice | Free (fails before generation) |

If you belong to several Gradium organizations, Claude should ask which one to use instead of picking one.

## How audio works in Claude Code

Claude Code does not play audio inside the conversation, and Claude cannot hear it. When `generate_speech` succeeds, Claude Code saves the WAV to the session's `tool-results` folder under `~/.claude/projects/` and gives Claude the file path:

```
[Audio from plugin:gradium:gradium] Binary content (audio/wav, 240KB) saved to …/tool-results/mcp-plugin_gradium_gradium-blob-….wav
```

- Claude Code cleans up that folder automatically. Ask Claude to copy the file into your project. Because the source is under `~/.claude`, Claude Code asks you to approve the copy.
- On macOS, the speech generation skill plays each new WAV with `afplay` by default. Say if you only want the file. On other systems, open the file in any audio player.
- The WAV is 48 kHz, 16-bit mono, streamed with placeholder size fields in its header. `ffprobe`, `afinfo`, and `afplay` read it. If another tool rejects it, rewrite it with `ffmpeg -i in.wav -c copy out.wav`.
- At that format, the server's 16 MiB cap is about 2 min 55 s of audio, so the skill splits long text into chunks of about 1,200 characters, well under the 9,000-character input limit.

## Run the evals

`plugins/gradium/evals/` contains five eval cases:
- credits balance
- casting a warm French narrator
- reading a sentence aloud when the returned WAV path is missing
- a failed generation with no retry
- a transcription request the beta cannot serve

They run against mocked Gradium tools, built from recorded responses and the server's real tool schemas. They need no Gradium sign-in and spend no Gradium credits. They do use your Claude usage: about $0.40 per pass at one run per case.

```bash
cd plugins/gradium && claude plugin eval . --runs 1 --ablation none --no-publish
```

Drop `--runs 1 --ablation none` to use the default of three runs per case plus a no-plugin baseline. Run the suite after every skill or description change. Results go to `evals/results/`, which is ignored.

## Feedback

Tell us on [Discord](https://discord.gg/T85yt8kD33) or open an issue in this repository. Include the Claude Code version (`claude --version`), the plugin version (`claude plugin list`), the prompt, which tools Claude called, what it returned, and what you expected. Do not include access tokens, callback URLs, or text or audio you are not allowed to share.

## License

[MIT](../LICENSE)
