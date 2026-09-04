#!/usr/bin/env python3
"""Validate skill packages without installing or executing their dependencies."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 5 * 1024 * 1024
FRONTMATTER_FIELD = re.compile(r"^([a-zA-Z][\w-]*):\s*(.+)$", re.MULTILINE)
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SECRET_ASSIGNMENT = re.compile(
    r"(?mi)^[ \t]*(?:export[ \t]+)?"
    r"(?:ANTHROPIC_API_KEY|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|"
    r"BASETEN_API_KEY|GITHUB_TOKEN|GRADIUM_API_KEY|HF_TOKEN|"
    r"LEMONSLICE_API_KEY|LIVEKIT_API_KEY|LIVEKIT_API_SECRET|LLM_API_KEY|"
    r"OPENAI_API_KEY|PRUNA_API_KEY)"
    r"[ \t]*=[ \t]*([^\r\n#]+)"
)
TOKEN_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])ghp_[A-Za-z0-9]{30,}(?![A-Za-z0-9])"),
    re.compile(
        r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{20,}\."
        r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
    ),
)
PLACEHOLDER_PARTS = (
    "...",
    "example",
    "paste",
    "placeholder",
    "their",
    "your",
    "<",
    "${",
    "$",
    "os.environ",
    "os.getenv",
)


def _tracked_files() -> list[Path]:
    ignored_roots = {".git", ".venv", "__pycache__"}
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not any(part in ignored_roots for part in path.parts)
    ]


def _frontmatter(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        errors.append(f"{path.relative_to(ROOT)}: missing YAML frontmatter")
        return
    block = text[4:].split("\n---\n", 1)[0]
    fields = dict(FRONTMATTER_FIELD.findall(block))
    for required in ("name", "description"):
        if not fields.get(required, "").strip():
            errors.append(f"{path.relative_to(ROOT)}: missing {required}")
    if fields.get("name", "").strip() != path.parent.name:
        errors.append(
            f"{path.relative_to(ROOT)}: name must match directory {path.parent.name!r}"
        )


def _links(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for raw_target in MARKDOWN_LINK.findall(text):
        target = raw_target.split("#", 1)[0].strip()
        if not target or target.startswith(("https://", "http://", "mailto:", "#")):
            continue
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            errors.append(f"{path.relative_to(ROOT)}: link escapes repository: {target}")
            continue
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)}: broken local link: {target}")


def _secret_hygiene(path: Path, errors: list[str]) -> None:
    text_suffixes = {
        ".go",
        ".js",
        ".json",
        ".md",
        ".mjs",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".yaml",
        ".yml",
    }
    if path.suffix.lower() not in text_suffixes and path.name not in {"Dockerfile"}:
        return
    text = path.read_text(encoding="utf-8", errors="ignore")
    for match in SECRET_ASSIGNMENT.finditer(text):
        value = match.group(1).strip().strip("\"'").casefold()
        if value and not any(part in value for part in PLACEHOLDER_PARTS):
            errors.append(
                f"{path.relative_to(ROOT)}: possible populated credential assignment"
            )
    if any(pattern.search(text) for pattern in TOKEN_PATTERNS):
        errors.append(f"{path.relative_to(ROOT)}: possible credential token")
    if re.search(r"https?://[^\s/]+\.ngrok-free\.(?:app|dev)", text, re.IGNORECASE):
        errors.append(f"{path.relative_to(ROOT)}: temporary ngrok URL must not be committed")


def main() -> int:
    errors: list[str] = []
    files = _tracked_files()

    skill_files = sorted(ROOT.glob("*/SKILL.md"))
    if not skill_files:
        errors.append("no top-level skill packages found")
    for skill_file in skill_files:
        _frontmatter(skill_file, errors)

    for path in files:
        relative = path.relative_to(ROOT)
        if path.is_symlink():
            errors.append(f"{relative}: symbolic links are not allowed")
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"{relative}: exceeds {MAX_FILE_BYTES} bytes")
            continue
        if path.suffix.lower() == ".md":
            _links(path, errors)
        if path.suffix.lower() == ".py":
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
            except SyntaxError as exc:
                errors.append(f"{relative}:{exc.lineno}: Python syntax error: {exc.msg}")
        _secret_hygiene(path, errors)

    tracked_env = [
        path.relative_to(ROOT)
        for path in files
        if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example")
    ]
    for path in tracked_env:
        errors.append(f"{path}: real environment file must not be tracked")

    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Validated {len(skill_files)} skills and {len(files)} repository files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
