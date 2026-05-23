# Gradium Skills

Reusable Agent Skills for working with Gradium.

Skills in this repo follow the `SKILL.md` package format: each skill
lives in its own folder with a required `SKILL.md` file and optional
resources such as `references/`.

## Available skills

| Skill | Purpose |
| --- | --- |
| `migrate-to-gradium` | Switch voice API integrations from ElevenLabs, Cartesia, or Deepgram to Gradium. |

## Install for Codex

Copy the skill folder into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
cp -R migrate-to-gradium ~/.codex/skills/
```

Then prompt Codex with requests such as:

```text
Use $migrate-to-gradium to switch this project from Cartesia to Gradium.
```

## Install for Claude Code

Claude Code can use the same `SKILL.md` package. Copy the skill folder
into your Claude skills directory:

```bash
mkdir -p ~/.claude/skills
cp -R migrate-to-gradium ~/.claude/skills/
```

Then prompt Claude Code with requests such as:

```text
Use the migrate-to-gradium skill to switch this app from Deepgram to Gradium.
```

## Notes

- Keep one canonical skill folder in this repo.
- Do not create separate Codex and Claude copies unless a tool requires
  provider-specific metadata.
- `agents/openai.yaml` is Codex UI metadata. Other agents can ignore it
  and read `SKILL.md` plus the referenced files.
