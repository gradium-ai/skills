"""Regression tests use fake providers and locally generated media, never API keys."""
import asyncio
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch
import wave

ROOT = Path(__file__).resolve().parents[1]
KEY = "GRADIUM" + "_API_KEY"
PKEY = "PRUNA" + "_API_KEY"
LKEY = "LIVEAVATAR" + "_API_KEY"
FKEY = "FAL" + "_KEY"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


tts = load("tts", "gradium/gradium-text-to-speech/scripts/tts.py")
stt = load("stt", "gradium/gradium-speech-to-text/scripts/transcribe.py")
s2s = load("s2s", "gradium/gradium-speech-translation/scripts/s2s.py")
video = load("video", "pruna/gradium-pruna-video/scripts/voice_video.py")
grade = load("grade", "pruna/gradium-pruna-video/scripts/grade_render.py")
validator = load("validator", "scripts/validate_repo.py")
orch = load("orchestrator", "live-avatar/heygen/gradium-heygen-live-avatar/scripts/orchestrator.py")
mm = load("minimax", "fal/gradium-minimax-designed-avatar/scripts/minimax_avatar.py")


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
             patch.object(video, "time", Mock(monotonic=lambda: clock[0], sleep=elapse)), \
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


def envelope(data, status=200):
    """A LiveAvatar-shaped response: {"code", "message", "data"} with a string body."""
    r = response(status=status, data={"code": 100, "message": "", "data": data})
    r.text = ""
    return r


class HeygenOrchestrator(unittest.TestCase):
    """The Gradium x LiveAvatar orchestrator, exercised without Gradium, LiveAvatar, or an LLM."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        p = patch("requests.sessions.Session.send", side_effect=AssertionError("network forbidden"))
        p.start(); self.addCleanup(p.stop)
        self.cfg = orch.Config.from_env({KEY: "test-only", LKEY: "test-only", "LLM_MODEL": "test-model",
                                         "MAX_SESSION_S": "300"})

    def test_sentence_splitter_streams_sentences_then_tail(self):
        splitter, out = orch.SentenceSplitter(), []
        for delta in ["Hello there", ". How are", " you? I am", " fine"]:
            out += splitter.feed(delta)
        self.assertEqual(out, ["Hello there.", "How are you?"])
        self.assertEqual(splitter.flush(), "I am fine")
        self.assertIsNone(splitter.flush())

    def test_turn_detector_needs_pending_words_and_consecutive_steps(self):
        detector = orch.TurnDetector(0.7, 2.0, 2)
        quiet = [{"horizon_s": 0.5, "inactivity_prob": 0.1}, {"horizon_s": 2.0, "inactivity_prob": 0.9}]
        busy = [{"horizon_s": 2.0, "inactivity_prob": 0.2}]
        self.assertFalse(detector.observe(quiet, has_pending_words=False))
        self.assertFalse(detector.observe(quiet, True))
        self.assertTrue(detector.observe(quiet, True))
        self.assertFalse(detector.observe(quiet, True))
        self.assertFalse(detector.observe(busy, True))
        self.assertFalse(detector.observe(quiet, True))

    def test_barge_in_needs_two_words_and_fires_once(self):
        policy = orch.BargeInPolicy(2)
        self.assertFalse(policy.on_user_word(avatar_talking=False))
        self.assertFalse(policy.on_user_word(True))
        self.assertTrue(policy.on_user_word(True))
        self.assertFalse(policy.on_user_word(True))
        policy.reset()
        self.assertFalse(policy.on_user_word(True))

    def test_tool_calls_are_reassembled_validated_and_clamped(self):
        acc = orch.ToolCallAccumulator()
        acc.feed([{"index": 0, "id": "call_1", "function": {"name": "show_", "arguments": '{"title": "Bon'}}])
        acc.feed([{"index": 0, "function": {"name": "card", "arguments": 'jour\\u0007", "body": "' + "x" * 200 + '"}'}}])
        [call] = acc.completed()
        ui, result = orch.dispatch_tool(call["name"], call["arguments"])
        self.assertEqual((ui["widget"], ui["props"]["title"], len(ui["props"]["body"])), ("card", "Bonjour", 160))
        self.assertTrue(result["shown"])
        self.assertIsNone(orch.dispatch_tool("show_card", '{"body": "no title"}')[0])
        self.assertFalse(orch.dispatch_tool("show_card", "not json")[1]["shown"])
        self.assertIsNone(orch.dispatch_tool("run_shell", '{"cmd": "rm"}')[0])
        self.assertEqual(orch.dispatch_tool("hide_card", "{}")[0], {"widget": "hide", "props": {}})

    def test_sse_parsing_and_llm_payload(self):
        self.assertEqual(orch.parse_sse_line("data: [DONE]"), "DONE")
        self.assertEqual(orch.parse_sse_line('data: {"a": 1}'), {"a": 1})
        for line in (": keep-alive", "data: nope", "", "event: x"):
            self.assertIsNone(orch.parse_sse_line(line))
        payload = orch.LlmStream(self.cfg, [{"role": "user", "content": "hi"}], orch.TOOLS).payload()
        self.assertEqual((payload["model"], payload["stream"], payload["max_tokens"]), ("test-model", True, 256))
        self.assertEqual([t["function"]["name"] for t in payload["tools"]], ["show_card", "hide_card"])

    def test_liveavatar_start_shape_and_missing_ws_url_stops_the_session(self):
        posts = [envelope({"session_id": "sid", "session_token": "tok"}),
                 envelope({"session_id": "sid", "livekit_url": "wss://lk", "livekit_client_token": "ct"}),
                 envelope(None)]
        cfg = replace(self.cfg, avatar_id="av-1", sandbox=True)
        with patch.object(orch.requests, "post", side_effect=posts) as post, \
             self.assertRaises(orch.LiveAvatarError):
            orch.start_liveavatar_session(cfg)
        token, start, stop = post.call_args_list
        self.assertEqual(token.kwargs["json"], {"mode": "LITE", "avatar_id": "av-1", "is_sandbox": True,
                                                "max_session_duration": 300})
        self.assertEqual(token.kwargs["headers"]["X-API-KEY"], "test-only")
        self.assertEqual(start.kwargs["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(stop.kwargs["json"], {"session_id": "sid", "reason": "SERVER_ERROR"})
        self.assertTrue(all(not c.kwargs["allow_redirects"] for c in post.call_args_list))

    def test_liveavatar_redirect_rejected_and_public_avatar_fallback(self):
        listing = envelope({"results": [{"id": "a", "status": "INIT", "type": "VIDEO"},
                                        {"id": "b", "status": "ACTIVE", "type": "IMAGE"},
                                        {"id": "c", "status": "ACTIVE", "type": "VIDEO"}]})
        with patch.object(orch.requests, "get", return_value=listing) as get, \
             patch.object(orch.requests, "post", return_value=envelope(None, status=307)) as post, \
             self.assertRaises(orch.LiveAvatarError) as ctx:
            orch.start_liveavatar_session(self.cfg)
        self.assertEqual(ctx.exception.status, 307)
        self.assertEqual(post.call_args.kwargs["json"]["avatar_id"], "c")
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertIsNone(orch.pick_public_avatar([{"id": "x", "status": "FAILED"}]))

    def test_media_leg_gates_on_connected_and_tracks_talking(self):
        async def run():
            sent = []
            class Ws:
                async def send(self, payload): sent.append(json.loads(payload))
            leg = orch.MediaLeg("wss://media.example/ws")
            leg.ws = Ws()
            await leg.speak("AAAA")
            self.assertEqual(sent, [])  # dropped: the server has not said "connected"
            leg.handle_event(json.dumps({"type": "session.state_updated", "state": "connected"}))
            await leg.speak(base64.b64encode(b"\0" * 48000).decode())  # one second of 24 kHz PCM16
            self.assertEqual(sent[-1]["type"], "agent.speak")
            self.assertIn("event_id", sent[-1])
            self.assertTrue(leg.talking)  # playback estimate covers the queued second
            await leg.interrupt()
            self.assertEqual(sent[-1]["type"], "agent.interrupt")
            self.assertFalse(leg.talking)
            leg.handle_event(json.dumps({"type": "agent.state_updated", "previous_state": "idle",
                                         "new_state": "talking"}))
            self.assertTrue(leg.talking)
            await leg.set_listening(True)  # pose changes are skipped while talking
            self.assertEqual(sent[-1]["type"], "agent.interrupt")
            leg.handle_event(json.dumps({"type": "session.state_updated", "state": "disconnected"}))
            await leg.speak_end()
            self.assertEqual(len(sent), 2)
        asyncio.run(run())

    def test_session_barge_in_turn_end_and_backchannel(self):
        async def run():
            sent, replies = [], []
            browser = Mock()
            async def send(message): sent.append(json.loads(message))
            browser.send = send
            session = orch.Session(self.cfg, browser, "persona", "")
            media, stt = Mock(talking=True), Mock()
            async def interrupt(): sent.append({"type": "_interrupt"})
            async def set_listening(listening): pass
            async def flush(): return 1
            async def fake_reply(text): replies.append(text)
            media.interrupt, media.set_listening = interrupt, set_listening
            stt.flush, stt.rotation_due = flush, lambda: False
            session.media, session.stt, session.reply = media, stt, fake_reply

            await session.on_stt_message({"type": "text", "text": "hey"})
            self.assertNotIn({"type": "_interrupt"}, sent)
            await session.on_stt_message({"type": "text", "text": "stop"})
            self.assertIn({"type": "_interrupt"}, sent)
            self.assertIn({"type": "interrupted"}, sent)

            media.talking = False
            vad = [{"horizon_s": 2.0, "inactivity_prob": 0.95}]
            await session.on_stt_message({"type": "step", "vad": vad})
            self.assertIsNone(session.awaiting_flush)
            await session.on_stt_message({"type": "step", "vad": vad})
            self.assertEqual(session.awaiting_flush, 1)
            await session.on_stt_message({"type": "flushed", "flush_id": 99})  # not ours
            await session.on_stt_message({"type": "flushed", "flush_id": 1})
            await asyncio.sleep(0)
            self.assertEqual(replies, ["hey stop"])
            self.assertEqual(sent[-1], {"type": "turn", "role": "user", "id": session.user_turn_id,
                                        "text": "hey stop", "done": True})

            media.talking = True
            await session.on_stt_message({"type": "text", "text": "mm-hmm"})
            session.awaiting_flush = 2
            await session.on_stt_message({"type": "flushed", "flush_id": 2})
            await asyncio.sleep(0)
            self.assertEqual(replies, ["hey stop"])  # a one-word backchannel gets no answer
        asyncio.run(run())

    def test_env_loader_and_config_validation(self):
        env_file = self.dir / ".env"
        env_file.write_text(KEY + '="from-file"\n# comment\nPORT=9000 # inline\nlower=no\nLLM_MODEL=m\n')
        env = orch.load_env_file(env_file, {KEY: "preset"})
        self.assertEqual((env[KEY], env["PORT"], env["LLM_MODEL"]), ("preset", "9000", "m"))
        self.assertNotIn("lower", env)
        problems = orch.Config.from_env({**env, LKEY: "k", "HOST": "0.0.0.0",
                                         "LLM_BASE_URL": "http://llm.internal/v1"}).validate()
        self.assertTrue(any(p.startswith("HOST") for p in problems))
        self.assertTrue(any("LLM_BASE_URL" in p for p in problems))
        self.assertEqual(orch.Config.from_env({**env, LKEY: "k", "LLM_BASE_URL": "http://localhost:11434/v1"}).validate(), [])
        self.assertEqual(orch.Config.from_env({}).missing(), [KEY, LKEY, "LLM_MODEL"])

    def test_static_files_are_confined_and_carry_a_policy(self):
        server = orch.Server(self.cfg)
        ok = server.process_request(None, Mock(path="/app.js?v=1"))
        self.assertEqual((ok.status_code, ok.headers["Content-Type"]), (200, "text/javascript; charset=utf-8"))
        self.assertIn("script-src 'self' https://cdn.jsdelivr.net", ok.headers["Content-Security-Policy"])
        for path in ("/../orchestrator.py", "/prompts/greeting.md", "/.env"):
            self.assertEqual(server.process_request(None, Mock(path=path)).status_code, 404, path)
        self.assertIsNone(server.process_request(None, Mock(path="/ws")))
        self.assertTrue(orch.load_prompt(self.dir / "missing.md", "fallback").startswith("fallback"))
        (self.dir / "p.md").write_text("Be kind\x07\n" + "x" * 5000)
        self.assertEqual(len(orch.load_prompt(self.dir / "p.md", "")), 4000)
        self.assertNotIn("\x07", orch.load_prompt(self.dir / "p.md", ""))



class MinimaxAvatar(unittest.TestCase):
    """Gradium Voice Design + TTS -> MiniMax H3 Max on fal, with every provider faked."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.speech = {}
        for seconds in (2, 6, 16):
            path = root / f"speech{seconds}.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=s=64x64:r=10",
                "-f", "lavfi", "-i", "sine=frequency=440", "-t", str(seconds),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
            ], check=True, timeout=60)
            cls.speech[seconds] = path
        cls.portrait, cls.tall = root / "portrait.png", root / "tall.png"
        for path, size in ((cls.portrait, "64x64"), (cls.tall, "64x200")):
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                            f"color=s={size}:r=1", "-frames:v", "1", str(path)], check=True, timeout=30)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name) / "out.mp4"
        self.out.write_bytes(b"previous output")
        for target, kwargs in [
            ("requests.sessions.Session.send", {"side_effect": AssertionError("network forbidden")}),
            ("sys.stdout", {"new": io.StringIO()}),
            ("sys.stderr", {"new": io.StringIO()}),
        ]:
            p = patch(target, **kwargs); p.start(); self.addCleanup(p.stop)

    def render(self, audio, *extra):
        return patch("sys.argv", ["mm", "render", "--audio", str(audio), "--image", str(self.portrait),
                                  "--out", str(self.out), *extra])

    def test_render_success_sends_inline_inputs_and_downloads_without_a_key(self):
        media = self.speech[6].read_bytes()
        posts = [response(data={"request_id": "req_1", "status_url": "https://evil.example/x"})]
        gets = [response(data={"status": "IN_QUEUE", "queue_position": 2}),
                response(data={"status": "COMPLETED"}),
                response(data={"video": {"url": "https://v3.fal.media/files/out.mp4"}, "seed": 7}),
                response(media)]
        with patch.dict(os.environ, {FKEY: "test-only"}), self.render(self.speech[6]), \
             patch.object(mm.requests, "post", side_effect=posts) as post, \
             patch.object(mm.requests, "get", side_effect=gets) as get, \
             patch.object(mm.time, "sleep"):
            self.assertEqual(mm.main(), 0)
        self.assertEqual(post.call_args.args[0], "https://queue.fal.run/minimax/h3-max/lip-sync/image-to-video")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Key test-only")
        body = post.call_args.kwargs["json"]
        self.assertTrue(body["image_url"].startswith("data:image/png;base64,"))
        self.assertTrue(body["audio_url"].startswith("data:audio/wav;base64,"))
        self.assertEqual((body["resolution"], body["enable_safety_checker"]), ("768P", True))
        self.assertNotIn("enable_transcription", body)
        urls = [c.args[0] for c in get.call_args_list]
        self.assertEqual(urls[:3], ["https://queue.fal.run/minimax/h3-max/requests/req_1/status"] * 2
                         + ["https://queue.fal.run/minimax/h3-max/requests/req_1"])
        self.assertEqual(get.call_args_list[3].kwargs["headers"], {})  # CDN download carries no key
        self.assertTrue(all(not c.kwargs["allow_redirects"] for c in post.call_args_list + get.call_args_list))
        self.assertEqual(self.out.read_bytes(), media)
        self.assertAlmostEqual(mm.media_duration(str(self.out.with_name("out_speech.wav"))), 6, delta=.2)

    def test_audio_window_pads_short_refuses_long_and_clips_only_when_allowed(self):
        with patch.dict(os.environ, {FKEY: "test-only"}), \
             patch.object(mm.requests, "post", return_value=response(status=500)) as post:
            with self.render(self.speech[16]), self.assertRaisesRegex(ValueError, "14.8"):
                mm.main()
            self.assertEqual(post.call_count, 0)
            for source, expected, flag in ((self.speech[2], 5.2, []), (self.speech[16], 14.8, ["--allow-clip"])):
                with self.render(source, *flag), self.assertRaisesRegex(SystemExit, "HTTP 500"):
                    mm.main()
                self.assertAlmostEqual(mm.media_duration(str(self.out.with_name("out_speech.wav"))),
                                       expected, delta=.2)
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args.kwargs["json"]["enable_safety_checker"], True)
        self.assertEqual(self.out.read_bytes(), b"previous output")

    def test_portrait_checks_reject_bad_aspect_ratio_and_non_images(self):
        with patch.dict(os.environ, {FKEY: "test-only"}), \
             patch.object(mm.requests, "post", side_effect=AssertionError("must not submit")), \
             patch("sys.argv", ["mm", "render", "--audio", str(self.speech[6]), "--image", str(self.tall),
                                "--out", str(self.out)]), \
             self.assertRaisesRegex(ValueError, "aspect ratio"):
            mm.main()
        with self.assertRaisesRegex(ValueError, "PNG, JPEG, or WebP"):
            mm.image_mime(str(self.speech[6]))
        self.assertEqual(mm.image_mime(str(self.portrait)), "image/png")

    def test_polling_deadline_does_not_resubmit(self):
        clock = [0]
        def elapse(seconds): clock[0] += seconds
        def poll(*args, **kwargs):
            elapse(min(30, kwargs["timeout"]))
            return response(data={"status": "IN_PROGRESS", "logs": []})
        with patch.dict(os.environ, {FKEY: "test-only"}), self.render(self.speech[6]), \
             patch.object(mm.requests, "post", return_value=response(data={"request_id": "req_1"})) as post, \
             patch.object(mm.requests, "get", side_effect=poll), \
             patch.object(mm, "time", Mock(monotonic=lambda: clock[0], sleep=elapse)), \
             self.assertRaisesRegex(SystemExit, "15 minutes"):
            mm.main()
        self.assertEqual(clock[0], 900)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(self.out.read_bytes(), b"previous output")

    def test_failed_result_surfaces_validation_detail_and_download_url_checks(self):
        gets = [response(data={"status": "COMPLETED"}),
                response(status=422, data={"detail": [{"msg": "aspect ratio out of range\x07"}]})]
        with patch.dict(os.environ, {FKEY: "test-only"}), self.render(self.speech[6]), \
             patch.object(mm.requests, "post", return_value=response(data={"request_id": "req_1"})), \
             patch.object(mm.requests, "get", side_effect=gets), \
             self.assertRaisesRegex(SystemExit, r"HTTP 422: aspect ratio out of range $"):
            mm.main()
        for url in ("http://v3.fal.media/f", "https://user@v3.fal.media/f", "https://v3.fal.media:8443/f"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                mm.download(url, str(self.out))
        self.assertEqual(self.out.read_bytes(), b"previous output")

    def test_design_writes_audition_and_reports_candidate(self):
        audition = self.out.with_name("audition.wav")
        posts = [response(data={"embeddings": [{"embedding_id": "vox_emb_1", "ready": False}]}),
                 response(wav())]
        gets = [response(data={"embeddings": []}),  # not indexed yet
                response(data={"embeddings": [{"embedding_id": "vox_emb_1", "ready": True}]})]
        with patch.dict(os.environ, {KEY: "test-only"}), \
             patch("sys.argv", ["mm", "design", "Calm and warm.", "--language", "fr", "--out", str(audition)]), \
             patch.object(mm.requests, "post", side_effect=posts) as post, \
             patch.object(mm.requests, "get", side_effect=gets) as get, \
             patch.object(mm.requests, "delete", side_effect=AssertionError("must not discard")), \
             patch.object(mm.time, "sleep"):
            self.assertEqual(mm.main(), 0)
        generate, tts = post.call_args_list
        self.assertEqual(generate.kwargs["json"], {"prompt": "Calm and warm.", "language": "fr", "n_samples": 1,
                                                   "json_config": {"cfg_scale": 10.0}})
        self.assertEqual(generate.kwargs["headers"], {"x-api-key": "test-only"})
        self.assertEqual(tts.kwargs["json"]["voice_id"], "vox_emb_1")
        self.assertEqual(tts.kwargs["json"]["text"], mm.AUDITION["fr"])
        self.assertEqual(get.call_args.kwargs["params"], {"embedding_id": "vox_emb_1"})
        self.assertTrue(all(not c.kwargs["allow_redirects"] for c in post.call_args_list + get.call_args_list))
        self.assertEqual(audition.read_bytes(), wav())
        self.assertIn("vox_emb_1", sys.stdout.getvalue())

    def test_design_discards_candidate_when_audition_fails(self):
        posts = [response(data={"embeddings": [{"embedding_id": "vox_emb_2"}]}), response(status=503)]
        with patch.dict(os.environ, {KEY: "test-only"}), \
             patch("sys.argv", ["mm", "design", "Bright.", "--out", str(self.out)]), \
             patch.object(mm.requests, "post", side_effect=posts), \
             patch.object(mm.requests, "get",
                          return_value=response(data={"embeddings": [{"embedding_id": "vox_emb_2", "ready": True}]})), \
             patch.object(mm.requests, "delete", return_value=response(status=204)) as delete, \
             self.assertRaises(ValueError):
            mm.main()
        self.assertEqual(delete.call_args.args[0], "https://api.gradium.ai/api/voice-generator/embeddings/vox_emb_2")
        self.assertFalse(delete.call_args.kwargs["allow_redirects"])
        self.assertEqual(self.out.read_bytes(), b"previous output")

    def test_promote_and_discard_shapes(self):
        with patch.dict(os.environ, {KEY: "test-only"}), \
             patch("sys.argv", ["mm", "promote", "vox_emb_3", "--name", "Arthur", "--description", "calm"]), \
             patch.object(mm.requests, "post", return_value=response(status=201, data={"uid": "voice_abc"})) as post:
            self.assertEqual(mm.main(), 0)
        self.assertEqual(post.call_args.args[0], "https://api.gradium.ai/api/voices/from-embedding")
        self.assertEqual(post.call_args.kwargs["json"],
                         {"voxium_embedding_id": "vox_emb_3", "name": "Arthur", "description": "calm"})
        self.assertIn("voice_abc", sys.stdout.getvalue())
        with patch.dict(os.environ, {KEY: "test-only"}), \
             patch("sys.argv", ["mm", "promote", "../etc", "--name", "x"]), self.assertRaises(SystemExit):
            mm.main()
        with patch.dict(os.environ, {KEY: "test-only"}), patch("sys.argv", ["mm", "discard", "vox_emb_3"]), \
             patch.object(mm.requests, "delete", return_value=response(status=404)) as delete:
            self.assertEqual(mm.main(), 0)  # already gone counts as discarded
        self.assertEqual(delete.call_args.kwargs["headers"], {"x-api-key": "test-only"})


if __name__ == "__main__":
    unittest.main()
