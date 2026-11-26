"""Save one authorized Gradium generation through the local Codex MCP connection."""

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import uuid

PRODUCTION_URL = "https://mcp.gradium.ai/mcp"
MAX_WAV_BYTES = 16 * 1024 * 1024


def check_connection(server):
    transport = server["transport"]
    if not (
        server["enabled"]
        and transport["type"] == "streamable_http"
        and transport["url"] == PRODUCTION_URL
    ):
        raise ValueError("Select the enabled production Gradium MCP connection.")
    enabled = server.get("enabled_tools")
    if (
        enabled is not None and "generate_speech" not in enabled
    ) or "generate_speech" in (server.get("disabled_tools") or []):
        raise ValueError("Speech generation is disabled for this connection.")


async def request(proc, number, method, params):
    message = {"method": method, "params": params}
    if number is not None:
        message["id"] = number
    proc.stdin.write(json.dumps(message).encode() + b"\n")
    await proc.stdin.drain()
    if number is None:
        return
    while line := await proc.stdout.readline():
        reply = json.loads(line)
        if "method" in reply:
            if "id" in reply:
                raise ValueError(
                    "Codex requires interaction. Resolve it in the client."
                )
            continue
        if reply.get("id") == number:
            if "error" in reply:
                raise ValueError(
                    f"Codex rejected {method}: {reply['error']['message']}"
                )
            return reply["result"]
    raise ValueError("Codex closed the connection.")


async def generate(server, arguments):
    # The same cwd and Codex installation resolve plugin and manual server names.
    lookup = await asyncio.create_subprocess_exec(
        "codex",
        "mcp",
        "get",
        "--json",
        "--",
        server,
        stdout=asyncio.subprocess.PIPE,
    )
    try:
        config, _ = await lookup.communicate()
    finally:
        if lookup.returncode is None:
            lookup.kill()
            await lookup.wait()
    if lookup.returncode:
        raise ValueError("Could not resolve the named Codex MCP connection.")
    check_connection(json.loads(config))

    proc = await asyncio.create_subprocess_exec(
        "codex",
        "app-server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        # One JSON line holds a base64-encoded WAV plus MCP metadata.
        limit=4 * ((MAX_WAV_BYTES + 2) // 3) + 1024 * 1024,
    )
    try:
        await request(
            proc,
            1,
            "initialize",
            {
                "clientInfo": {"name": "gradium_wav", "version": "1"},
            },
        )
        await request(proc, None, "initialized", {})
        thread = await request(
            proc, 2, "thread/start", {"cwd": os.getcwd(), "ephemeral": True}
        )
        result = await request(
            proc,
            3,
            "mcpServer/tool/call",
            {
                "threadId": thread["thread"]["id"],
                "server": server,
                "tool": "generate_speech",
                "arguments": arguments,
            },
        )
        if not result.get("isError"):
            for block in result["content"]:
                if (
                    block.get("type") == "audio"
                    and block.get("mimeType") == "audio/wav"
                ):
                    wav = base64.b64decode(block["data"], validate=True)
                    if (
                        len(wav) > MAX_WAV_BYTES
                        or wav[:4] != b"RIFF"
                        or wav[8:12] != b"WAVE"
                    ):
                        raise ValueError("Invalid Gradium WAV response.")
                    return wav
        detail = " ".join(
            b["text"] for b in result["content"] if b.get("type") == "text"
        )
        raise ValueError(detail[:600] or "Gradium returned no WAV.")
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.communicate()


def save(server, arguments, path):
    # Reserve a new private file before spending credits. Never overwrite a prior clip.
    with open(path, "xb", opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        try:
            output.write(
                asyncio.run(asyncio.wait_for(generate(server, arguments), 180))
            )
            output.flush()
        except BaseException:
            output.close()
            path.unlink()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--org-uid", required=True, type=uuid.UUID)
    parser.add_argument("--voice-id")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    text = sys.stdin.read()
    if not text.strip() or len(text) > 9000:
        parser.error("Supply 1 to 9000 characters of speech text on stdin.")
    arguments = {"text": text, "org_uid": str(args.org_uid)}
    if args.voice_id:
        arguments["voice_id"] = args.voice_id
    save(args.server, arguments, args.output)
    print(args.output.resolve())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, asyncio.TimeoutError) as exc:
        sys.exit(f"Could not save the WAV: {exc or 'timed out'}. No retry was issued.")
