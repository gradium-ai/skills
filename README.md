# Jev Browser

A browser automation skill for **Codex and Claude Code**, powered by [Jev Ultrafast](https://github.com/browser-use/jev-ultrafast).

**Experimental — use browser automation with caution.** It can make mistakes and take real actions in your browser. Use a dedicated Chrome profile and verify results.

Give your assistant a browser task. It passes a focused goal to Jev, which navigates Chrome and interacts with the page. Your assistant then checks the result.

## What this adds to Jev

Jev is the browser automation engine. This project packages it as a reusable skill with:

- Instructions for choosing tasks and verifying results.
- A runner with action opt-in, time and step budgets, and optional page checks.
- Tools for inspecting pages and opening embedded booking forms.
- Setup, troubleshooting, and security guidance.

Browser actions run through Jev instead of the assistant's native browser controls. Performance depends on the website and model providers; this project does not promise a universal speedup.

## Get started

You need **Chrome, Python 3.12+, uv, a TypeSafe API key**, and a separate text-model API key for typing. Model API usage is billed separately from your Codex or Claude subscription.

### Agent installation prompt

Publish this folder at the root of `timpratim/jevbrow` on the `main` branch to enable these commands and links.

> Install the experimental Jev Browser skill. If you're in Claude Code, run `claude plugin marketplace add timpratim/jevbrow`, then `claude plugin install jev-browser@jev-browser`. If you're in another agent, run `npx skills add timpratim/jevbrow --skill jev-browser` and select your agent. Use one installation method. You can read the skill at [SKILL.md](https://github.com/timpratim/jevbrow/blob/main/SKILL.md) ([raw](https://raw.githubusercontent.com/timpratim/jevbrow/main/SKILL.md)). Read its security and setup guides, configure credentials locally, then use Jev Browser for browser tasks on this project. Browser automation should be used with caution; verify results and stay within my authorization.

The `npx` method requires Node.js/npm. Installation adds the skill; follow the [setup guide](references/setup.md) to install Jev, configure credentials, and connect Chrome. Start a new assistant session after installation.

### Try it

   **Codex**
   ```text
   $jev-browser Open Wikipedia and find the article about general relativity.
   ```

   **Claude Code**
   ```text
   /jev-browser:jev-browser Open Wikipedia and find the article about general relativity.
   ```

For command-line usage, see [SKILL.md](SKILL.md). For embedded forms or stalled tasks, see [recovery](references/recovery.md).

The Claude example uses the plugin command. A manually installed standalone skill uses `/jev-browser`.

## Scope and safety

Supports navigation, clicks, scrolling, text fields, and native dropdowns. Complex widgets, uploads, popups, and some embedded content need manual help. Form entry requires a compatible text-model configuration.

**Experimental software for trusted local use.** Use a dedicated Chrome profile. Page content and task details are sent to TypeSafe; typing also uses your text-model provider. Keep API keys out of chat and source control.

The runner is not a sandbox and does not enforce approval before each action. Handle passwords, payments, and sensitive accounts yourself. Read [SECURITY.md](SECURITY.md) before running it.

Built on Jev Ultrafast by [browser-use](https://github.com/browser-use/jev-ultrafast). The upstream runtime is installed separately.
