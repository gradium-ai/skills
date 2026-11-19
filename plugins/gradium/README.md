# gradium (Claude Code plugin)

Connects Claude Code to the hosted Gradium MCP (`https://mcp.gradium.ai/mcp`, beta). It lets you browse and shortlist Gradium voices from their metadata, generate speech as WAV files, and check credit balances. Sign in with your Gradium Studio account through `/mcp` → `plugin:gradium:gradium` → Authenticate.

Skills: `/gradium:setup`, `/gradium:credits`, `/gradium:voice-casting`, `/gradium:speech-generation`.

Speech generation uses your organization's Gradium credits, and it is available only when the server has speech enabled. Claude Code saves returned audio to a file and gives Claude its path; it does not play audio inline.

See `../../README.md` for install steps, test prompts, and known limitations, and the [Gradium MCP guide](https://docs.gradium.ai/integrations/mcp) for the tools.
