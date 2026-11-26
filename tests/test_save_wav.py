"""Exercise the shipped helper with a real Codex CLI and a local Streamable HTTP MCP."""

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import asyncio
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock
import wave

SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "plugins/gradium-codex/skills/gradium-speech-generation/scripts"
)
sys.path.insert(0, str(SCRIPTS))
import save_wav  # noqa: E402 (load the helper from the plugin under test)


def audio_fixture():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", ""))
        wav.writeframes(bytes(3200))
    return output.getvalue()


class FailureTest(unittest.TestCase):
    def test_error_after_dispatch_leaves_no_file_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "failed.wav"
            with mock.patch.object(
                save_wav, "generate", side_effect=TimeoutError("timed out")
            ) as call:
                with self.assertRaises(TimeoutError):
                    save_wav.save("gradium", {"text": "hello"}, output)
            call.assert_awaited_once()
            self.assertFalse(output.exists())

    def test_interactive_request_stops_the_generation(self):
        proc = mock.Mock()
        proc.stdin.drain = mock.AsyncMock()
        proc.stdout.readline = mock.AsyncMock(
            return_value=b'{"method":"mcpServer/elicitation/request","id":42}\n'
        )
        with self.assertRaisesRegex(ValueError, "requires interaction"):
            asyncio.run(save_wav.request(proc, 3, "mcpServer/tool/call", {}))
        self.assertEqual(proc.stdin.write.call_count, 1)

    def test_tool_restrictions_are_respected(self):
        server = {
            "transport": {"url": save_wav.PRODUCTION_URL, "type": "streamable_http"},
            "enabled": True,
        }
        for restricted in (
            {"enabled": False},
            {"enabled_tools": []},
            {"disabled_tools": ["generate_speech"]},
        ):
            with self.subTest(restricted=restricted), self.assertRaises(ValueError):
                save_wav.check_connection({**server, **restricted})


@unittest.skipUnless(shutil.which("codex"), "requires the Codex CLI")
class SaveWavTest(unittest.TestCase):
    def test_first_call_saves_audio_and_replay_uses_the_file(self):
        raw = audio_fixture()
        calls = []

        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_error(405)

            def do_POST(self):
                msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if "id" not in msg:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                method = msg["method"]
                if method == "initialize":
                    result = {
                        "protocolVersion": msg["params"]["protocolVersion"],
                        "serverInfo": {"name": "fixture", "version": "1"},
                        "capabilities": {"tools": {}},
                    }
                elif method == "tools/list":
                    result = {
                        "tools": [
                            {
                                "name": "generate_speech",
                                "inputSchema": {"type": "object"},
                            }
                        ]
                    }
                elif method == "tools/call":
                    calls.append(msg["params"])
                    result = {
                        "content": [
                            {
                                "type": "audio",
                                "mimeType": "audio/wav",
                                "data": base64.b64encode(raw).decode(),
                            },
                            {"type": "text", "text": "synthetic org"},
                        ]
                    }
                else:
                    result = {}
                data = json.dumps(
                    {"jsonrpc": "2.0", "id": msg["id"], "result": result}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        with (
            ThreadingHTTPServer(("127.0.0.1", 0), Fixture) as server,
            tempfile.TemporaryDirectory() as tmp,
        ):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            url = f"http://127.0.0.1:{server.server_port}/mcp"
            home = Path(tmp)
            (home / "config.toml").write_text(
                f'[mcp_servers.fixture]\nurl = "{url}"\n'
                f'[projects.{json.dumps(os.getcwd())}]\ntrust_level = "trusted"\n'
            )
            args = {
                "text": "Hello",
                "org_uid": "00000000-0000-4000-a000-000000000001",
                "voice_id": "example",
            }
            path = home / "saved.wav"
            with mock.patch.dict(os.environ, CODEX_HOME=tmp):
                # A connection with a different endpoint must never receive the text.
                with self.assertRaisesRegex(ValueError, "production Gradium"):
                    save_wav.save("fixture", args, path)
                self.assertFalse(path.exists())
                self.assertEqual(calls, [])
                with mock.patch.object(save_wav, "PRODUCTION_URL", url):
                    save_wav.save("fixture", args, path)
                    with self.assertRaises(FileExistsError):
                        save_wav.save("fixture", args, path)
                self.assertEqual(path.read_bytes(), raw)
                with wave.open(str(path), "rb") as wav:
                    self.assertEqual(wav.getnframes(), 1600)
                self.assertEqual(
                    [(c["name"], c["arguments"]) for c in calls],
                    [("generate_speech", args)],
                )


if __name__ == "__main__":
    unittest.main()
