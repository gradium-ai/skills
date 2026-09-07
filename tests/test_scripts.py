"""Regression tests use fake providers and locally generated media, never API keys."""
import asyncio
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import wave

ROOT = Path(__file__).resolve().parents[1]
KEY = "GRADIUM" + "_API_KEY"
PKEY = "PRUNA" + "_API_KEY"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tts = load("tts", "gradium/gradium-text-to-speech/scripts/tts.py")
stt = load("stt", "gradium/gradium-speech-to-text/scripts/transcribe.py")
s2s = load("s2s", "gradium/gradium-speech-translation/scripts/s2s.py")
video = load("video", "pruna/gradium-pruna-video/scripts/voice_video.py")
grade = load("grade", "pruna/gradium-pruna-video/scripts/grade_render.py")
validator = load("validator", "scripts/validate_repo.py")


def response(body=b"", status=200, location=None, data=None):
    r = Mock(status_code=status, content=body, headers={})
    r.is_redirect = status in (301, 302, 303, 307, 308)
    r.is_permanent_redirect = status in (301, 308)
    if location:
        r.headers["Location"] = location
    stream = io.BytesIO(body)
    r.raw.read1.side_effect = lambda n, **kw: stream.read(n)
    r.json.return_value = data
    r.__enter__ = Mock(return_value=r)
    r.__exit__ = Mock(return_value=False)
    return r


def wav():
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        w.writeframes(b"\0\0" * 2400)
    return b.getvalue()


class Socket:
    def __init__(self, messages):
        self.messages = iter(messages)

    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def send(self, message): pass
    async def recv(self): return json.dumps({"type": "ready"})
    def __aiter__(self): return self

    async def __anext__(self):
        try:
            return json.dumps(next(self.messages))
        except StopIteration:
            raise StopAsyncIteration


class Scripts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.media = Path(cls.temp.name) / "sample.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=s=64x64:r=10",
            "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.media),
        ], check=True, timeout=30)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name) / "out.wav"
        self.out.write_bytes(b"previous output")
        # A forgotten mock cannot turn a regression test into a paid API call.
        for target, kwargs in [
            ("requests.sessions.Session.send", {"side_effect": AssertionError("network forbidden")}),
            ("sys.stdout", {"new": io.StringIO()}),
            ("sys.stderr", {"new": io.StringIO()}),
        ]:
            p = patch(target, **kwargs); p.start(); self.addCleanup(p.stop)

    def test_tts_rejects_redirect_and_preserves_output(self):
        with patch.dict(os.environ, {KEY: "test-only"}), \
             patch("sys.argv", ["tts", "hello", "--out", str(self.out)]), \
             patch.object(tts.requests, "post", return_value=response(status=307)) as post:
            self.assertEqual(tts.main(), 1)
            self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(self.out.read_bytes(), b"previous output")

    def test_tts_success_retains_request_shape(self):
        with patch.dict(os.environ, {KEY: "test-only"}), \
             patch("sys.argv", ["tts", "hello", "--speed", "fast", "--out", str(self.out)]), \
             patch.object(tts.requests, "post", return_value=response(wav())) as post:
            self.assertEqual(tts.main(), 0)
            self.assertEqual(post.call_args.kwargs["json"]["json_config"], {"padding_bonus": -2.0})
        self.assertEqual(self.out.read_bytes(), wav())

    def test_stt_rejects_redirect(self):
        with patch.dict(os.environ, {KEY: "test-only"}), \
             patch("sys.argv", ["stt", str(self.out)]), \
             patch.object(stt.requests, "post", return_value=response(status=302)) as post:
            self.assertEqual(stt.main(), 1)
            self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def translate(self, messages):
        args = Mock(audio="input.wav", voice="voice", to="fr", out=str(self.out))
        with patch.object(s2s.subprocess, "run", return_value=Mock(stdout=b"\0\0")) as process, \
             patch.object(s2s.websockets, "connect", return_value=Socket(messages)):
            result = asyncio.run(s2s.run(args, "test-only"))
            self.assertTrue(process.call_args.kwargs["check"])
            self.assertIn("296", process.call_args.args[0])
            return result

    def test_translation_error_close_empty_and_bad_audio_preserve_output(self):
        for messages in ([{"type": "error"}], [], [{"type": "end_of_stream"}],
                         [{"type": "audio", "audio": "invalid!"}]):
            with self.subTest(messages=messages), self.assertRaises((ValueError, EOFError, wave.Error)):
                self.translate(messages)
            self.assertEqual(self.out.read_bytes(), b"previous output")

    def test_translation_success(self):
        self.assertEqual(self.translate([
            {"type": "audio", "audio": base64.b64encode(wav()).decode()},
            {"type": "end_of_stream"},
        ]), 0)
        self.assertEqual(self.out.read_bytes(), wav())

    def test_translation_cli_returns_nonzero_on_decode_failure(self):
        with patch.dict(os.environ, {KEY: "test-only"}), \
             patch("sys.argv", ["s2s", "bad.wav", "--to", "fr", "--voice", "voice",
                                "--out", str(self.out)]), \
             patch.object(s2s.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
            self.assertEqual(s2s.main(), 1)
        self.assertEqual(self.out.read_bytes(), b"previous output")

    def test_stalled_translation_times_out_without_replacing_output(self):
        class Stalled(Socket):
            async def __anext__(self):
                await asyncio.Event().wait()
        wait_for = asyncio.wait_for
        async def short_timeout(awaitable, timeout):
            return await wait_for(awaitable, .01)
        args = Mock(audio="input.wav", voice="voice", to="fr", out=str(self.out))
        with patch.object(s2s.subprocess, "run", return_value=Mock(stdout=b"\0\0")), \
             patch.object(s2s.websockets, "connect", return_value=Stalled([])), \
             patch.object(s2s.asyncio, "wait_for", side_effect=short_timeout), \
             self.assertRaises(asyncio.TimeoutError):
            asyncio.run(s2s.run(args, "test-only"))
        self.assertEqual(self.out.read_bytes(), b"previous output")

    def test_polling_deadline_does_not_resubmit_prediction(self):
        clock = [0]
        def elapse(seconds): clock[0] += seconds
        def poll(*args, **kwargs):
            elapse(min(30, kwargs["timeout"]))
            return response(data={"status": "processing"})
        posts = [response(data={"urls": {"get": "https://api.pruna.ai/file"}})] * 2
        posts += [response(data={"id": "prediction"})]
        with patch.dict(os.environ, {PKEY: "test-only"}), \
             patch("sys.argv", ["video", "--audio", str(self.media), "--image", str(self.media)]), \
             patch.object(video.requests, "post", side_effect=posts) as post, \
             patch.object(video.requests, "get", side_effect=poll), \
             patch.object(video.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(video.time, "sleep", side_effect=elapse), \
             self.assertRaisesRegex(SystemExit, "20 minutes"):
            video.main()
        self.assertEqual(clock[0], 1200)
        self.assertEqual(post.call_count, 3)  # Two uploads, one paid prediction.

    def test_download_relative_redirect_and_cross_origin_key_removal(self):
        responses = [response(status=302, location="/render"),
                     response(status=302, location="https://cdn.example.org/file"),
                     response(self.media.read_bytes())]
        with patch.object(video.requests, "get", side_effect=responses) as get:
            video.download("https://api.pruna.ai/start", "test-only", str(self.out), 2)
        self.assertEqual(get.call_args_list[1].args[0], "https://api.pruna.ai/render")
        self.assertEqual(get.call_args_list[0].kwargs["headers"], {"apikey": "test-only"})
        self.assertEqual(get.call_args_list[2].kwargs["headers"], {})
        self.assertTrue(all(not c.kwargs["allow_redirects"] for c in get.call_args_list))
        self.assertEqual(self.out.read_bytes(), self.media.read_bytes())

    def test_download_origin_validation(self):
        self.assertFalse(video.is_pruna_host("https://cdn.pruna.ai/file"))
        self.assertFalse(video.is_pruna_host("https://api.pruna.ai:8443/file"))
        for url in ("http://api.pruna.ai/file", "https://user@api.pruna.ai/file",
                    "https://api.pruna.ai:8443/file"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                video.download(url, "test-only", str(self.out))

    def test_bad_media_size_deadline_and_duration_preserve_output(self):
        for body, limit, deadline, expected in [
            (b"<html>error</html>", video.MAX_BYTES, time.monotonic() + 30, None),
            (self.media.read_bytes(), 10, time.monotonic() + 30, None),
            (b"", video.MAX_BYTES, time.monotonic() - 1, None),
            (self.media.read_bytes(), video.MAX_BYTES, time.monotonic() + 30, 20),
        ]:
            with patch.object(video, "MAX_BYTES", limit), \
                 self.assertRaises((ValueError, TimeoutError, subprocess.CalledProcessError)):
                video.save_media(response(body), str(self.out), deadline, True, expected)
            self.assertEqual(self.out.read_bytes(), b"previous output")

    def test_avatar_pipeline_success(self):
        image = self.out.parent / "portrait.png"
        image.write_bytes(b"test image")
        posts = [response(data={"urls": {"get": "https://api.pruna.ai/image"}}),
                 response(data={"urls": {"get": "https://api.pruna.ai/audio"}}),
                 response(data={"id": "prediction"})]
        gets = [response(data={"status": "succeeded", "generation_url": "https://api.pruna.ai/video"}),
                response(self.media.read_bytes())]
        with patch.dict(os.environ, {PKEY: "test-only"}), \
             patch("sys.argv", ["video", "--audio", str(self.media), "--image", str(image),
                                "--out", str(self.out)]), \
             patch.object(video.requests, "post", side_effect=posts) as post, \
             patch.object(video.requests, "get", side_effect=gets) as get:
            self.assertEqual(video.main(), 0)
            self.assertTrue(all(not c.kwargs["allow_redirects"] for c in post.call_args_list + get.call_args_list))
            inp = post.call_args.kwargs["json"]["input"]
            self.assertTrue(inp["disable_prompt_upsampling"])
            self.assertFalse(inp["disable_safety_filter"])

    def test_grading_preserves_colliding_files_and_handles_empty_words(self):
        prefix = str(self.out.parent / "report")
        collision = Path(prefix + "_sweep_0.png")
        collision.write_bytes(b"existing image")
        words = self.out.parent / "words.json"
        words.write_text('{"segments": []}')
        with patch("sys.argv", ["grade", str(self.media), prefix, str(words)]):
            grade.main()
        self.assertEqual(collision.read_bytes(), b"existing image")
        self.assertTrue(Path(prefix + "_mouth.png").read_bytes().startswith(b"\x89PNG"))

    def test_secret_examples_and_structured_values(self):
        value = "test-only-" + "a" * 30
        for name, content in [(".env.example", KEY + "=" + value),
                              ("config.json", json.dumps({KEY: value})),
                              ("config.yaml", PKEY + ": " + value)]:
            path = self.out.parent / name
            path.write_text(content)
            with patch.object(validator, "ROOT", self.out.parent):
                errors = []; validator._secret_hygiene(path, errors)
            self.assertTrue(errors, name)
        path.write_text(KEY + "=your_key_here\n" + PKEY + "=\n")
        errors = []; validator._secret_hygiene(path, errors)
        self.assertEqual(errors, [])

    def test_frontmatter_requires_valid_yaml(self):
        skill = self.out.parent / "sample"
        skill.mkdir()
        path = skill / "SKILL.md"
        for description, valid in [('Speech: translate audio', False),
                                   ('"Speech: translate audio"', True)]:
            path.write_text('---\nname: sample\ndescription: ' + description + '\n---\n')
            with patch.object(validator, "ROOT", self.out.parent):
                errors = []; validator._frontmatter(path, errors)
            self.assertEqual(not errors, valid)


if __name__ == "__main__":
    unittest.main()
