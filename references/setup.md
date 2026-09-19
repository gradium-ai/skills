# Runtime and installation

Source: https://github.com/browser-use/jev-ultrafast
API reviewed at commit `1231850a0bf1a0c0341fe408ef1668dbbfdfac46`.
Requires Python 3.12+, uv, Chrome, and Browser Harness (installed by uv).

Install the skill folder in one of these locations:

- Codex: `${CODEX_HOME:-$HOME/.codex}/skills/jev-browser`
- Claude Code: `$HOME/.claude/skills/jev-browser`, or `.claude/skills/jev-browser` in a project

Copy the complete folder, including scripts and references. Do not overwrite an existing skill without inspecting it. Start a new assistant session if needed for discovery. Invoke as `$jev-browser` in Codex or `/jev-browser` for a standalone Claude Code installation. The Claude marketplace installation documented in [README.md](../README.md) uses `/jev-browser:jev-browser` instead. Choose one installation method.

Keep the runtime outside the skill folder. Example setup (choose a suitable runtime directory):

```bash
git clone https://github.com/browser-use/jev-ultrafast.git /absolute/path/to/jev-runtime
git -C /absolute/path/to/jev-runtime checkout 1231850a0bf1a0c0341fe408ef1668dbbfdfac46
export JEV_ROOT=/absolute/path/to/jev-runtime
uv sync --project "$JEV_ROOT" --frozen --no-dev
cp "$JEV_ROOT/.env.example" "$JEV_ROOT/.env"
chmod 600 "$JEV_ROOT/.env"
uv run --frozen --no-dev --project "$JEV_ROOT" browser-harness --doctor
```

Run the copy step only for a new `.env`. Have the user configure keys locally; do not ask them to paste secrets into chat. Connect Browser Harness to a dedicated automation Chrome profile with no unrelated accounts, saved passwords, or extensions. The runner cannot enforce profile isolation. Follow Browser Harness's connection instructions and Chrome's remote-debugging prompt. Do not expose debugging to the public network.

Model configuration (not needed for inspection):

```dotenv
TYPESAFE_API_KEY=<configured locally>
TYPESAFE_MODEL=jev-latest
TEXT_MODEL_API_KEY=<configured locally>
TEXT_MODEL_BASE_URL=https://openrouter.ai/api/v1
TEXT_MODEL=inception/mercury-2.5
TEXT_MODEL_REASONING=none
```

These text-model settings match the reviewed upstream example, not a guarantee of ongoing provider availability. Other OpenAI-compatible helpers can be configured; verify their JSON output and reasoning options. The runner requires TypeSafe credentials for agent runs. A text-model key is required only when Jev types; without it, a typing attempt stops with an error. Configure the helper before delegating forms that require typing. Inspection needs no model credentials.

The runner uses `Agent(url, goal, screenshots=False)`, `command('tick')`, `snapshot()`, and `browser.observe(screenshot=False)`. A fresh observation supplies URL, visible text, and observed control values for verification. It does not reuse the last model decision as evidence. Default output omits raw model requests, typed-action history, and screenshots.

For a live smoke test, use the Wikipedia example in SKILL.md. It consumes paid API calls. Validate both the returned URL and visible article title. Runtime setup and a live smoke test must succeed before describing this skill as operational on a particular machine.

## Validation

Run bundled offline checks with `python3 -m unittest discover -s /absolute/path/to/jev-browser/tests`. The updated runner was also tested against a local HTML fixture in real Chrome: observed frame discovery, standalone frame handoff, a 2400px viewport, checked-field extraction, and hidden/password value exclusion. This used no model credentials or external registrations. The earlier booking investigation exercised these recovery techniques on live sites, but arbitrary sites and provider typing compatibility are not guaranteed.

Install and run with `--frozen --no-dev` to avoid upstream development dependencies. The reviewed upstream lock includes pytest 8.4.2, affected by CVE-2025-71176; it is not needed by this wrapper, whose tests use Python unittest. Upstream development work requires a separately reviewed dependency update.
