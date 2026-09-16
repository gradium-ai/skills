#!/usr/bin/env python3
"""Gradium voice pipeline driving a HeyGen LiveAvatar (LITE mode).

One Python process replaces the GPT-Live bridge of HeyGen's reference demo:

    browser mic ─ws─► this server ─► Gradium STT (semantic VAD turn-taking)
                                  ─► LLM (OpenAI-compatible chat completions, streamed)
                                  ─► Gradium TTS (pcm_24000) ─► LiveAvatar media websocket
    browser ◄─LiveKit─ avatar audio + video (published by LiveAvatar)
    browser ◄─ws────── transcripts, on-screen cards, avatar state, errors

The browser never sees an API key. A LITE session returns the LiveKit room the
browser watches plus a media-server websocket that only this process talks to.
Gradium TTS emits 24 kHz PCM16 base64 chunks, which is exactly what LiveAvatar
consumes, so audio is forwarded verbatim.

Requires: pip install requests websockets   (Python 3.10+)

Usage:
  cp .env.example .env   # fill GRADIUM_API_KEY, LIVEAVATAR_API_KEY, LLM_* server-side
  python orchestrator.py            # http://127.0.0.1:8787
  python orchestrator.py --check    # validate configuration and exit

Local starter: binds to 127.0.0.1 and has no authentication. Read
../references/security-and-privacy.md before exposing it anywhere else.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import requests
import websockets
from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

HERE = Path(__file__).resolve().parent
log = logging.getLogger("orchestrator")

GRADIUM_WS = "wss://api.gradium.ai/api/speech"
LIVEAVATAR_API_DEFAULT = "https://api.liveavatar.com"
DEFAULT_VOICE_ID = "YTpq7expH9539ERJ"  # Gradium's documented safe English default
DEFAULT_LANGUAGE = "en"
SAMPLE_RATE = 24000  # Gradium pcm_24000 == LiveAvatar's required PCM16 24 kHz mono
HTTP_TIMEOUT = (10, 30)
STT_ROTATE_S = 240        # Gradium websocket sessions cap at 300 s; rotate at a turn boundary
FLUSH_TIMEOUT_S = 3.0     # a `flushed` reply that never comes must not wedge turn-taking
MEDIA_READY_TIMEOUT_S = 15
MEDIA_KEEP_ALIVE_S = 120  # LiveAvatar idles a session out after 5 minutes without commands
BARGE_IN_WORDS = 2        # "mm-hmm" is one token; two words over the avatar is an interruption
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SENTENCE_END = re.compile(r"(?<=[.!?…])[\"'”’)\]]*\s+|\n+")
FALLBACK_REPLY = "Sorry, I lost my train of thought. Could you say that again?"

CARD_LIMITS = {"title": 60, "subtitle": 80, "body": 160}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "show_card",
            "description": (
                "Put a short card on the viewer's screen beside the avatar: a title, an "
                "optional subtitle, and one line of body text. Use it when you introduce a "
                "term, a name, a number, or a step the viewer should see written down. "
                "Always also say the answer out loud in the same reply."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Up to 60 characters."},
                    "subtitle": {"type": "string", "description": "Up to 80 characters."},
                    "body": {"type": "string", "description": "Up to 160 characters."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hide_card",
            "description": "Remove the card currently on screen.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

VOICE_RULES = (
    "You are speaking aloud in a live video call through an animated avatar. Reply in one "
    "or two short sentences unless the person asks for detail. Never use lists, markdown, "
    "emoji, stage directions, or URLs: everything you write is spoken. Make answers easy to "
    "interrupt. Do not announce or describe cards that appear on screen; keep talking "
    "naturally. If you are unsure, ask one short question instead of going silent."
)
GREETING_PREAMBLE = (
    "The session just started and the person is listening but has not spoken yet. Open the "
    "conversation now with the following, then stop and wait for them: "
)


# ── configuration ─────────────────────────────────────────────────────────────

def load_env_file(path: Path, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Minimal .env loader: KEY=value lines, optional quotes, never overrides existing vars."""
    env = os.environ if environ is None else environ
    if not path.is_file():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        env.setdefault(key, value)
    return env


@dataclass
class Config:
    gradium_key: str
    liveavatar_key: str
    llm_base_url: str
    llm_model: str
    llm_key: str = ""
    llm_max_tokens: int = 256
    llm_temperature: float = 0.3
    voice_id: str = DEFAULT_VOICE_ID
    language: str = DEFAULT_LANGUAGE
    tts_model: str = "default"
    tts_padding_bonus: Optional[float] = None
    stt_delay_frames: int = 8
    stt_keywords: list[str] = field(default_factory=list)
    turn_threshold: float = 0.7
    turn_horizon: float = 2.0
    turn_consecutive: int = 2
    avatar_id: str = ""
    sandbox: bool = False
    video_quality: str = ""
    liveavatar_api_url: str = LIVEAVATAR_API_DEFAULT
    host: str = "127.0.0.1"
    port: int = 8787
    max_sessions: int = 2
    max_session_s: int = 600
    idle_timeout_s: int = 60
    log_transcripts: bool = False
    prompts_dir: Path = HERE / "prompts"
    static_dir: Path = HERE / "static"

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "Config":
        def flag(name: str) -> bool:
            return env.get(name, "").strip().lower() in {"1", "true", "yes", "on"}

        padding = env.get("GRADIUM_TTS_PADDING_BONUS", "").strip()
        keywords = [k.strip() for k in env.get("GRADIUM_KEYWORDS", "").split(",") if k.strip()]
        return cls(
            gradium_key=env.get("GRADIUM_API_KEY", ""),
            liveavatar_key=env.get("LIVEAVATAR_API_KEY", ""),
            llm_base_url=env.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            llm_model=env.get("LLM_MODEL", ""),
            llm_key=env.get("LLM_API_KEY", ""),
            llm_max_tokens=int(env.get("LLM_MAX_TOKENS", "256")),
            llm_temperature=float(env.get("LLM_TEMPERATURE", "0.3")),
            voice_id=env.get("GRADIUM_VOICE_ID", DEFAULT_VOICE_ID),
            language=env.get("GRADIUM_LANGUAGE", DEFAULT_LANGUAGE),
            tts_model=env.get("GRADIUM_TTS_MODEL", "default"),
            tts_padding_bonus=float(padding) if padding else None,
            stt_delay_frames=int(env.get("GRADIUM_STT_DELAY_FRAMES", "8")),
            stt_keywords=keywords,
            turn_threshold=float(env.get("TURN_THRESHOLD", "0.7")),
            turn_horizon=float(env.get("TURN_HORIZON_S", "2.0")),
            turn_consecutive=int(env.get("TURN_CONSECUTIVE_STEPS", "2")),
            avatar_id=env.get("LIVEAVATAR_AVATAR_ID", ""),
            sandbox=flag("LIVEAVATAR_SANDBOX"),
            video_quality=env.get("LIVEAVATAR_VIDEO_QUALITY", ""),
            liveavatar_api_url=env.get("LIVEAVATAR_API_URL", LIVEAVATAR_API_DEFAULT).rstrip("/"),
            host=env.get("HOST", "127.0.0.1"),
            port=int(env.get("PORT", "8787")),
            max_sessions=int(env.get("MAX_SESSIONS", "2")),
            max_session_s=int(env.get("MAX_SESSION_S", "600")),
            idle_timeout_s=int(env.get("IDLE_TIMEOUT_S", "60")),
            log_transcripts=flag("LOG_TRANSCRIPTS"),
            prompts_dir=Path(env.get("PROMPTS_DIR", str(HERE / "prompts"))),
            static_dir=Path(env.get("STATIC_DIR", str(HERE / "static"))),
        )

    def missing(self) -> list[str]:
        required = [
            ("GRADIUM_API_KEY", self.gradium_key),
            ("LIVEAVATAR_API_KEY", self.liveavatar_key),
            ("LLM_MODEL", self.llm_model),
        ]
        return [name for name, value in required if not value]

    def validate(self) -> list[str]:
        problems = [f"missing {name}" for name in self.missing()]
        if self.language not in {"en", "fr", "de", "es", "pt"}:
            problems.append("GRADIUM_LANGUAGE must be one of en, fr, de, es, pt")
        if not 128 <= self.llm_max_tokens <= 1024:
            problems.append("LLM_MAX_TOKENS must be between 128 and 1024")
        if not self.llm_base_url.startswith("https://") and not is_loopback_url(self.llm_base_url):
            problems.append("LLM_BASE_URL must use https:// unless it points at localhost")
        if not self.liveavatar_api_url.startswith("https://"):
            problems.append("LIVEAVATAR_API_URL must use https://")
        if self.video_quality and self.video_quality not in {"very_high", "high", "medium", "low"}:
            problems.append("LIVEAVATAR_VIDEO_QUALITY must be very_high, high, medium, or low")
        if not is_loopback_host(self.host):
            problems.append(
                "HOST is not loopback: this starter has no authentication and must not be "
                "exposed beyond 127.0.0.1 (see references/security-and-privacy.md)"
            )
        return problems

    def gradium_headers(self) -> dict[str, str]:
        return {"x-api-key": self.gradium_key}


def is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")


def is_loopback_url(url: str) -> bool:
    match = re.match(r"^https?://([^/:]+)", url)
    return bool(match) and is_loopback_host(match.group(1))


def load_prompt(path: Path, fallback: str, limit: int = 4000) -> str:
    """Persona text is untrusted creative data: strip control characters and cap the length."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return fallback
    text = CONTROL_CHARS.sub("", text).strip()
    return text[:limit] if text else ""


# ── small pure helpers (unit tested) ──────────────────────────────────────────

class SentenceSplitter:
    """Group streamed LLM tokens into sentences so TTS can start before the reply ends."""

    def __init__(self) -> None:
        self.buffer = ""

    def feed(self, delta: str) -> list[str]:
        self.buffer += delta
        out: list[str] = []
        while True:
            match = SENTENCE_END.search(self.buffer)
            if not match:
                return out
            sentence = self.buffer[: match.end()].strip()
            self.buffer = self.buffer[match.end():]
            if sentence:
                out.append(sentence)

    def flush(self) -> Optional[str]:
        tail, self.buffer = self.buffer.strip(), ""
        return tail or None


class TurnDetector:
    """Decide end-of-turn from Gradium's semantic VAD `step` messages.

    `inactivity_prob` at horizon H is the model's belief that the speaker is still silent
    H seconds from now; it stays low through a pause inside an unfinished sentence.
    """

    def __init__(self, threshold: float = 0.7, horizon: float = 2.0, consecutive: int = 2) -> None:
        self.threshold, self.horizon, self.consecutive = threshold, horizon, consecutive
        self.streak = 0

    def observe(self, vad: list[dict[str, Any]], has_pending_words: bool) -> bool:
        if not vad or not has_pending_words:
            self.streak = 0
            return False
        entry = next((v for v in vad if v.get("horizon_s") == self.horizon), vad[-1])
        if float(entry.get("inactivity_prob", 0.0)) > self.threshold:
            self.streak += 1
        else:
            self.streak = 0
        if self.streak >= self.consecutive:
            self.streak = 0
            return True
        return False


class BargeInPolicy:
    """A user word over the talking avatar is a candidate interruption; act once per utterance."""

    def __init__(self, min_words: int = BARGE_IN_WORDS) -> None:
        self.min_words = min_words
        self.words_over_speech = 0
        self.fired = False

    def reset(self) -> None:
        self.words_over_speech, self.fired = 0, False

    def on_user_word(self, avatar_talking: bool) -> bool:
        if not avatar_talking:
            return False
        self.words_over_speech += 1
        if self.fired or self.words_over_speech < self.min_words:
            return False
        self.fired = True
        return True


def parse_sse_line(line: str) -> Any:
    """Return the decoded JSON of a `data:` line, the string 'DONE', or None for other lines."""
    if not line or not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if payload == "[DONE]":
        return "DONE"
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


class ToolCallAccumulator:
    """Reassemble OpenAI-style streamed tool_calls deltas, keyed by index."""

    def __init__(self) -> None:
        self.calls: dict[int, dict[str, str]] = {}

    def feed(self, deltas: list[dict[str, Any]]) -> None:
        for delta in deltas:
            index = int(delta.get("index", 0))
            call = self.calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if delta.get("id"):
                call["id"] = str(delta["id"])
            function = delta.get("function") or {}
            if function.get("name"):
                call["name"] += str(function["name"])
            if function.get("arguments"):
                call["arguments"] += str(function["arguments"])

    def completed(self) -> list[dict[str, str]]:
        return [self.calls[i] for i in sorted(self.calls) if self.calls[i]["name"]]


def clamp_text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = CONTROL_CHARS.sub("", value).strip()
    return text[:limit] if text else None


def dispatch_tool(name: str, arguments: str) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    """Validate a model tool call. Returns (ui message or None, tool result for the model)."""
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return None, {"shown": False, "error": "arguments were not valid JSON"}
    if not isinstance(args, dict):
        return None, {"shown": False, "error": "arguments must be an object"}
    if name == "hide_card":
        return {"widget": "hide", "props": {}}, {"shown": False, "hidden": True}
    if name == "show_card":
        props = {k: clamp_text(args.get(k), limit) for k, limit in CARD_LIMITS.items()}
        props = {k: v for k, v in props.items() if v}
        if "title" not in props:
            return None, {"shown": False, "error": "title is required"}
        return {"widget": "card", "props": props}, {"shown": True}
    return None, {"shown": False, "error": "unknown tool; nothing was displayed"}


def pick_public_avatar(avatars: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    active = [a for a in avatars if a.get("status") == "ACTIVE" and a.get("id")]
    return next((a for a in active if a.get("type") == "VIDEO"), active[0] if active else None)


# ── LiveAvatar REST ───────────────────────────────────────────────────────────

class LiveAvatarError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"LiveAvatar API returned {status}: {body[:300]}")
        self.status = status


@dataclass
class StartedSession:
    session_id: str
    livekit_url: str
    livekit_client_token: str
    ws_url: str


def _la_post(cfg: Config, path: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    response = requests.post(
        f"{cfg.liveavatar_api_url}{path}", json=body,
        headers={"Content-Type": "application/json", **headers},
        timeout=HTTP_TIMEOUT, allow_redirects=False,
    )
    if response.status_code >= 300:
        raise LiveAvatarError(response.status_code, response.text or "")
    try:
        data = response.json().get("data")
    except ValueError as exc:
        raise LiveAvatarError(response.status_code, "response was not JSON") from exc
    return data if isinstance(data, dict) else {}


def resolve_avatar_id(cfg: Config) -> str:
    """Explicit LIVEAVATAR_AVATAR_ID, else the first active public avatar (no auth needed)."""
    if cfg.avatar_id:
        return cfg.avatar_id
    response = requests.get(
        f"{cfg.liveavatar_api_url}/v1/avatars/public", params={"page_size": 20},
        timeout=HTTP_TIMEOUT, allow_redirects=False,
    )
    if response.status_code != 200:
        raise LiveAvatarError(response.status_code, "could not list public avatars")
    results = (response.json().get("data") or {}).get("results") or []
    pick = pick_public_avatar(results)
    if not pick:
        raise LiveAvatarError(404, "no active public avatar; set LIVEAVATAR_AVATAR_ID")
    log.info("no LIVEAVATAR_AVATAR_ID set; using public avatar %r (%s)", pick.get("name"), pick["id"])
    return str(pick["id"])


def start_liveavatar_session(cfg: Config) -> StartedSession:
    """Mint a bare LITE token, then start it. Only a bare LITE start returns `ws_url`."""
    token_body: dict[str, Any] = {"mode": "LITE", "avatar_id": resolve_avatar_id(cfg)}
    if cfg.sandbox:
        token_body["is_sandbox"] = True
    if cfg.video_quality:
        token_body["video_settings"] = {"quality": cfg.video_quality}
    if cfg.max_session_s:
        token_body["max_session_duration"] = cfg.max_session_s
    token = _la_post(cfg, "/v1/sessions/token", token_body, {"X-API-KEY": cfg.liveavatar_key})
    session_id, session_token = str(token.get("session_id", "")), str(token.get("session_token", ""))
    if not session_id or not session_token:
        raise LiveAvatarError(502, "token mint returned no session_id/session_token")

    started = _la_post(cfg, "/v1/sessions/start", {}, {"Authorization": f"Bearer {session_token}"})
    result = StartedSession(
        session_id=session_id,
        livekit_url=str(started.get("livekit_url", "")),
        livekit_client_token=str(started.get("livekit_client_token", "")),
        ws_url=str(started.get("ws_url", "")),
    )
    if not (result.livekit_url and result.livekit_client_token and result.ws_url):
        # The session is billable from /start: release it before failing loudly.
        try:
            stop_liveavatar_session(cfg, session_id, "SERVER_ERROR")
        except Exception:  # noqa: BLE001 - best effort during cleanup
            pass
        raise LiveAvatarError(502, "LITE start did not return livekit_url, livekit_client_token and ws_url")
    return result


def stop_liveavatar_session(cfg: Config, session_id: str, reason: str = "USER_CLOSED") -> None:
    _la_post(cfg, "/v1/sessions/stop", {"session_id": session_id, "reason": reason},
             {"X-API-KEY": cfg.liveavatar_key})


# ── LiveAvatar media websocket (the avatar's ear) ─────────────────────────────

class MediaLeg:
    """Server-side connection to the LITE media server.

    Commands sent before `session.state_updated: connected` are silently dropped, so
    readiness means that event arrived, not that the socket opened.
    """

    def __init__(self, ws_url: str, on_state: Callable[[str], None] | None = None) -> None:
        self.ws_url = ws_url
        self.ws: Any = None
        self.connected = asyncio.Event()
        self.closed = False
        self.avatar_state = "idle"
        self.on_state = on_state
        self.bytes_sent = 0
        self._playback_end = 0.0

    @property
    def talking(self) -> bool:
        """Avatar state from the server, backed by a playback estimate for the queued tail."""
        return self.avatar_state == "talking" or time.monotonic() < self._playback_end

    async def run(self) -> None:
        attempts = 0
        while not self.closed and attempts < 3:
            try:
                async with ws_connect(self.ws_url, open_timeout=10, max_size=2 * 1024 * 1024) as ws:
                    self.ws = ws
                    attempts = 0
                    keep_alive = asyncio.create_task(self._keep_alive())
                    try:
                        async for raw in ws:
                            self.handle_event(raw)
                    finally:
                        keep_alive.cancel()
            except (OSError, websockets.exceptions.WebSocketException) as exc:
                if not self.closed:
                    log.warning("media server: %s", exc)
            finally:
                self.ws = None
                self.connected.clear()
            if not self.closed:
                attempts += 1
                await asyncio.sleep(min(8, 2 ** attempts))
        if not self.closed:
            log.error("media server: gave up reconnecting")

    async def _keep_alive(self) -> None:
        while True:
            await asyncio.sleep(MEDIA_KEEP_ALIVE_S)
            await self._send({"type": "session.keep_alive"})

    def handle_event(self, raw: str | bytes) -> None:
        try:
            event = json.loads(raw)
        except (TypeError, ValueError):
            return
        kind = event.get("type")
        if kind == "session.state_updated":
            state = event.get("state")
            log.info("media server: session %s", state)
            if state == "connected":
                self.connected.set()
            else:
                self.connected.clear()
        elif kind == "agent.state_updated":
            self.avatar_state = str(event.get("new_state") or "idle")
            if self.on_state:
                self.on_state(self.avatar_state)
        elif kind in {"error", "warning"}:
            detail = event.get(kind) or {}
            log.warning("media server %s: %s %s", kind, detail.get("type"), detail.get("message"))

    async def wait_ready(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self.connected.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return not self.closed

    async def speak(self, audio_b64: str) -> None:
        """Append one PCM16 24 kHz chunk to the current utterance, exactly as Gradium produced it."""
        if await self._send({"type": "agent.speak", "audio": audio_b64}):
            pcm_bytes = len(audio_b64) * 3 // 4
            self.bytes_sent += pcm_bytes
            now = time.monotonic()
            self._playback_end = max(self._playback_end, now) + pcm_bytes / 2 / SAMPLE_RATE

    async def speak_end(self) -> None:
        await self._send({"type": "agent.speak_end"})

    async def interrupt(self) -> None:
        self._playback_end = 0.0
        await self._send({"type": "agent.interrupt"})

    async def set_listening(self, listening: bool) -> None:
        if self.avatar_state == "talking":
            return
        await self._send({"type": "agent.start_listening" if listening else "agent.stop_listening"})

    async def _send(self, payload: dict[str, Any]) -> bool:
        if self.ws is None or not self.connected.is_set():
            return False  # the server would drop it silently anyway
        payload.setdefault("event_id", str(uuid.uuid4()))
        try:
            await self.ws.send(json.dumps(payload))
        except websockets.exceptions.WebSocketException:
            return False
        return True

    async def close(self) -> None:
        self.closed = True
        self.connected.set()  # unblock wait_ready on a session torn down early
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass


# ── Gradium STT leg ───────────────────────────────────────────────────────────

class SttLeg:
    """Long-lived Gradium ASR websocket; rotated before the 300 s session cap."""

    def __init__(self, cfg: Config, on_message: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self.cfg = cfg
        self.on_message = on_message
        self.ws: Any = None
        self.ready = asyncio.Event()
        self.closed = False
        self.opened_at = 0.0
        self.flush_id = 0
        self._rotate = False

    def setup_message(self) -> dict[str, Any]:
        json_config: dict[str, Any] = {
            "language": self.cfg.language,
            "delay_in_frames": self.cfg.stt_delay_frames,
        }
        if self.cfg.stt_keywords:
            json_config["keywords"] = {"words": self.cfg.stt_keywords, "boost": 3}
        return {"type": "setup", "model_name": "default", "input_format": "pcm_24000",
                "json_config": json_config}

    async def run(self) -> None:
        failures = 0
        while not self.closed and failures < 3:
            try:
                async with ws_connect(f"{GRADIUM_WS}/asr", additional_headers=self.cfg.gradium_headers(),
                                      open_timeout=10) as ws:
                    await ws.send(json.dumps(self.setup_message()))
                    ready = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    if ready.get("type") != "ready":
                        raise RuntimeError(f"STT setup rejected: {ready.get('type')} {ready.get('message', '')}")
                    log.info("stt: ready request_id=%s", ready.get("request_id"))
                    self.ws, self.opened_at, self._rotate = ws, time.monotonic(), False
                    self.ready.set()
                    failures = 0
                    async for raw in ws:
                        message = json.loads(raw)
                        if message.get("type") == "error":
                            log.warning("stt error: %s", message.get("message"))
                            break
                        await self.on_message(message)
                        if message.get("type") == "end_of_stream":
                            break
            except (OSError, websockets.exceptions.WebSocketException, RuntimeError,
                    asyncio.TimeoutError, ValueError) as exc:
                if not self.closed:
                    failures += 1
                    log.warning("stt: %s", exc)
            finally:
                self.ws = None
                self.ready.clear()
            if not self.closed and not self._rotate:
                await asyncio.sleep(min(4, 2 ** failures))
        if not self.closed:
            log.error("stt: gave up reconnecting")

    async def wait_ready(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self.ready.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return True

    def rotation_due(self) -> bool:
        return self.ready.is_set() and time.monotonic() - self.opened_at > STT_ROTATE_S

    async def rotate(self) -> None:
        """Close the current socket at a turn boundary; run() reopens it immediately."""
        if self.ws is not None:
            self._rotate = True
            await self.ws.send(json.dumps({"type": "end_of_stream"}))

    async def send_audio(self, audio_b64: str) -> None:
        if self.ws is not None and self.ready.is_set():
            try:
                await self.ws.send(json.dumps({"type": "audio", "audio": audio_b64}))
            except websockets.exceptions.WebSocketException:
                pass

    async def flush(self) -> int:
        self.flush_id += 1
        if self.ws is not None and self.ready.is_set():
            await self.ws.send(json.dumps({"type": "flush", "flush_id": self.flush_id}))
        return self.flush_id

    async def close(self) -> None:
        self.closed = True
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass


# ── LLM (OpenAI-compatible chat completions, streamed from a worker thread) ───

class LlmStream:
    """Stream one chat completion. Items on `queue`: ('text', str) | ('tools', list) |
    ('error', str) | None when finished."""

    def __init__(self, cfg: Config, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> None:
        self.cfg = cfg
        self.messages = messages
        self.tools = tools
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.stop = threading.Event()
        self._response: Any = None
        self.finish_reason: Optional[str] = None

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.cfg.llm_model, "messages": self.messages, "stream": True,
            "temperature": self.cfg.llm_temperature, "max_tokens": self.cfg.llm_max_tokens,
        }
        if self.tools:
            body["tools"] = self.tools
        return body

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        threading.Thread(target=self._run, args=(loop,), daemon=True).start()

    def cancel(self) -> None:
        self.stop.set()
        response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:  # noqa: BLE001
                pass

    def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        def put(item: Any) -> None:
            loop.call_soon_threadsafe(self.queue.put_nowait, item)

        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.cfg.llm_key:
            headers["Authorization"] = f"Bearer {self.cfg.llm_key}"
        try:
            with requests.post(f"{self.cfg.llm_base_url}/chat/completions", json=self.payload(),
                               headers=headers, stream=True, timeout=(10, 60), allow_redirects=False) as response:
                self._response = response
                if response.status_code != 200:
                    put(("error", f"LLM HTTP {response.status_code}"))
                    return
                response.encoding = response.encoding or "utf-8"
                for line in response.iter_lines(decode_unicode=True):
                    if self.stop.is_set():
                        break
                    event = parse_sse_line(line)
                    if event == "DONE":
                        break
                    if not isinstance(event, dict):
                        continue
                    for choice in event.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            put(("text", str(delta["content"])))
                        if delta.get("tool_calls"):
                            put(("tools", delta["tool_calls"]))
                        if choice.get("finish_reason"):
                            self.finish_reason = choice["finish_reason"]
        except requests.RequestException as exc:
            if not self.stop.is_set():
                put(("error", type(exc).__name__))
        finally:
            put(None)


# ── one browser session ───────────────────────────────────────────────────────

class Session:
    def __init__(self, cfg: Config, browser: Any, persona: str, greeting: str) -> None:
        self.cfg = cfg
        self.browser = browser
        self.persona = persona
        self.greeting = greeting
        self.id = uuid.uuid4().hex[:8]
        self.started_at = time.monotonic()
        self.last_mic_at = time.monotonic()
        self.history: list[dict[str, Any]] = []
        self.pending_words: list[str] = []
        self.user_turn_id: Optional[str] = None
        self.awaiting_flush: Optional[int] = None
        self.flush_sent_at = 0.0
        self.detector = TurnDetector(cfg.turn_threshold, cfg.turn_horizon, cfg.turn_consecutive)
        self.barge_in = BargeInPolicy()
        self.media: Optional[MediaLeg] = None
        self.stt: Optional[SttLeg] = None
        self.reply_task: Optional[asyncio.Task[None]] = None
        self.greeted = False
        self.stop_reason = "USER_CLOSED"
        self._tts_first_audio: Optional[float] = None

    def log(self, message: str, *args: Any) -> None:
        log.info("[%s] " + message, self.id, *args)

    async def emit(self, message: dict[str, Any]) -> None:
        try:
            await self.browser.send(json.dumps(message))
        except websockets.exceptions.WebSocketException:
            pass

    def system_prompt(self) -> str:
        return VOICE_RULES + "\n\nYour role:\n" + self.persona

    # ── lifecycle ──

    async def run(self, upstream: StartedSession) -> None:
        await self.emit({"type": "session", "session_id": upstream.session_id,
                         "livekit_url": upstream.livekit_url,
                         "livekit_client_token": upstream.livekit_client_token})
        self.media = MediaLeg(upstream.ws_url, on_state=self._on_avatar_state)
        media_task = asyncio.create_task(self.media.run())
        if not await self.media.wait_ready(MEDIA_READY_TIMEOUT_S):
            await self.emit({"type": "error", "message": "the avatar could not be reached; start a new session"})
            media_task.cancel()
            self.stop_reason = "SERVER_ERROR"
            return
        self.stt = SttLeg(self.cfg, self.on_stt_message)
        stt_task = asyncio.create_task(self.stt.run())
        watchdog = asyncio.create_task(self._watchdog())
        if not await self.stt.wait_ready(10):
            self.log("stt did not become ready; continuing, audio is dropped until it does")
        await self.emit({"type": "ready"})
        try:
            async for raw in self.browser:
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                kind = message.get("type")
                if kind == "mic_audio" and isinstance(message.get("audio"), str):
                    self.last_mic_at = time.monotonic()
                    self._maybe_greet()
                    await self.stt.send_audio(message["audio"])
                elif kind == "joined":
                    # The browser is attached to the LiveKit room: an opening line is heard now.
                    self._maybe_greet()
                elif kind == "stop":
                    break
        except websockets.exceptions.WebSocketException:
            self.stop_reason = "USER_DISCONNECTED"
        finally:
            for task in (watchdog, stt_task, media_task):
                task.cancel()
            await self.cancel_reply(notify=False)
            await self.stt.close()
            await self.media.close()

    def _maybe_greet(self) -> None:
        if self.greeted or not self.greeting:
            return
        self.greeted = True
        self.reply_task = asyncio.create_task(self.reply(None))

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(2)
            now = time.monotonic()
            if now - self.last_mic_at > self.cfg.idle_timeout_s:
                self.stop_reason = "IDLE_TIMEOUT"
                await self.emit({"type": "error", "message": "no microphone audio; the session ended"})
            elif now - self.started_at > self.cfg.max_session_s:
                self.stop_reason = "MAX_DURATION_REACHED"
                await self.emit({"type": "error", "message": "the session reached its time limit"})
            else:
                continue
            await self.browser.close()
            return

    def _on_avatar_state(self, state: str) -> None:
        asyncio.get_running_loop().create_task(self.emit({"type": "state", "avatar": state}))

    # ── speech in ──

    @property
    def avatar_talking(self) -> bool:
        return bool(self.media and self.media.talking)

    async def on_stt_message(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "text":
            word = str(message.get("text", "")).strip()
            if not word:
                return
            if not self.pending_words:
                self.user_turn_id = uuid.uuid4().hex[:8]
                if self.media:
                    await self.media.set_listening(True)
            self.pending_words.append(word)
            await self.emit({"type": "turn", "role": "user", "id": self.user_turn_id,
                             "text": " ".join(self.pending_words), "done": False})
            if self.barge_in.on_user_word(self.avatar_talking):
                self.log("barge-in: user spoke over the avatar")
                await self.cancel_reply(notify=True)
        elif kind == "step":
            if self.awaiting_flush is not None:
                if time.monotonic() - self.flush_sent_at > FLUSH_TIMEOUT_S:
                    self.log("flush %s never confirmed; finishing the turn anyway", self.awaiting_flush)
                    self.awaiting_flush = None
                    await self._finish_user_turn()
            elif self.detector.observe(message.get("vad") or [], bool(self.pending_words)):
                self.awaiting_flush = await self.stt.flush() if self.stt else None
                self.flush_sent_at = time.monotonic()
        elif kind == "flushed":
            if message.get("flush_id") != self.awaiting_flush:
                return
            self.awaiting_flush = None
            await self._finish_user_turn()

    async def _finish_user_turn(self) -> None:
        words, self.pending_words = self.pending_words, []
        transcript = " ".join(words).strip()
        turn_id = self.user_turn_id
        talking = self.avatar_talking
        if self.media:
            await self.media.set_listening(False)
        if not transcript:
            return
        await self.emit({"type": "turn", "role": "user", "id": turn_id, "text": transcript, "done": True})
        if len(words) < self.barge_in.min_words and talking:
            self.log("dropping a %d-word backchannel over the avatar", len(words))
            return
        if self.stt and self.stt.rotation_due():
            await self.stt.rotate()
        if self.cfg.log_transcripts:
            self.log("user: %s", transcript)
        await self.cancel_reply(notify=True)
        self.reply_task = asyncio.create_task(self.reply(transcript))

    # ── speech out ──

    async def cancel_reply(self, notify: bool) -> None:
        """Stop generation and clear the avatar's queued speech; a no-op when nothing is playing."""
        task, self.reply_task = self.reply_task, None
        running = task is not None and not task.done()
        if running:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - the reply owns its errors
                pass
        if not running and not self.avatar_talking:
            return
        if self.media:
            await self.media.interrupt()
        if notify:
            await self.emit({"type": "interrupted"})

    async def open_tts(self) -> Any:
        json_config: dict[str, Any] = {"rewrite_rules": self.cfg.language}
        if self.cfg.tts_padding_bonus is not None:
            json_config["padding_bonus"] = self.cfg.tts_padding_bonus
        ws = await ws_connect(f"{GRADIUM_WS}/tts", additional_headers=self.cfg.gradium_headers(), open_timeout=10)
        try:
            await ws.send(json.dumps({"type": "setup", "voice_id": self.cfg.voice_id,
                                      "model_name": self.cfg.tts_model, "output_format": "pcm_24000",
                                      "json_config": json_config}))
            ready = json.loads(await asyncio.wait_for(ws.recv(), 10))
        except BaseException:
            await ws.close()
            raise
        if ready.get("type") != "ready":
            await ws.close()
            raise RuntimeError(f"TTS setup rejected: {ready.get('type')} {ready.get('message', '')}")
        return ws

    async def reply(self, user_text: Optional[str]) -> None:
        """Stream LLM sentences into one Gradium TTS session and its audio into the avatar."""
        turn_id = uuid.uuid4().hex[:8]
        t0 = time.monotonic()
        marks: dict[str, float] = {}
        spoken: list[str] = []
        tts: Any = None
        pump: Optional[asyncio.Task[None]] = None
        llm: Optional[LlmStream] = None
        self.barge_in.reset()
        self._tts_first_audio = None
        # Open the TTS socket while the LLM thinks, so the handshake overlaps first-token latency.
        tts_task = asyncio.create_task(self.open_tts())

        async def ensure_tts() -> Any:
            nonlocal tts, pump
            if tts is None:
                tts = await tts_task
                pump = asyncio.create_task(self._pump_tts(tts))
            return tts

        try:
            messages = [{"role": "system", "content": self.system_prompt()}]
            if user_text is None:
                messages.append({"role": "system", "content": GREETING_PREAMBLE + self.greeting})
            else:
                self.history.append({"role": "user", "content": user_text})
            messages.extend(self.history[-24:])

            for tool_round in range(2):  # at most one tool round-trip per reply
                llm = LlmStream(self.cfg, messages, TOOLS)
                llm.start()
                splitter, tools = SentenceSplitter(), ToolCallAccumulator()
                text_parts: list[str] = []
                while True:
                    item = await llm.queue.get()
                    if item is None:
                        break
                    kind, value = item
                    if kind == "error":
                        self.log("llm: %s", value)
                        break
                    if kind == "tools":
                        tools.feed(value)
                        continue
                    marks.setdefault("llm_first_token", time.monotonic() - t0)
                    text_parts.append(value)
                    for sentence in splitter.feed(value):
                        await self._say(await ensure_tts(), sentence, spoken, turn_id)
                tail = splitter.flush()
                if tail:
                    await self._say(await ensure_tts(), tail, spoken, turn_id)
                calls = tools.completed()
                if not calls or tool_round == 1:
                    break
                messages.append({
                    "role": "assistant", "content": "".join(text_parts) or None,
                    "tool_calls": [{"id": c["id"] or f"call_{i}", "type": "function",
                                    "function": {"name": c["name"], "arguments": c["arguments"]}}
                                   for i, c in enumerate(calls)],
                })
                for i, call in enumerate(calls):
                    ui, result = dispatch_tool(call["name"], call["arguments"])
                    self.log("tool %s -> %s", call["name"], "shown" if ui else result.get("error"))
                    if ui:
                        await self.emit({"type": "ui", **ui})
                    messages.append({"role": "tool", "tool_call_id": call["id"] or f"call_{i}",
                                     "content": json.dumps(result)})
            if not spoken:
                self.log("empty model turn; speaking the fallback")
                await self._say(await ensure_tts(), FALLBACK_REPLY, spoken, turn_id)
            await tts.send(json.dumps({"type": "end_of_stream"}))
            assert pump is not None
            await asyncio.wait_for(pump, 60)
            if self._tts_first_audio:
                marks["tts_first_audio"] = self._tts_first_audio - t0
            if self.media:
                await self.media.speak_end()
            text = " ".join(spoken)
            await self.emit({"type": "turn", "role": "assistant", "id": turn_id, "text": text, "done": True})
            self.history.append({"role": "assistant", "content": text})
            self.log("reply done: llm_first_token=%.2fs tts_first_audio=%.2fs total=%.2fs",
                     marks.get("llm_first_token", -1), marks.get("tts_first_audio", -1), time.monotonic() - t0)
        except asyncio.CancelledError:
            if spoken:
                self.history.append({"role": "assistant", "content": " ".join(spoken) + " [interrupted]"})
            raise
        except Exception as exc:  # noqa: BLE001 - surface a restrained error, keep the session
            self.log("reply failed: %s", exc)
            await self.emit({"type": "error", "message": "the reply could not be generated"})
        finally:
            if llm is not None:
                llm.cancel()
            if pump is not None:
                pump.cancel()
            if not tts_task.done():
                tts_task.cancel()
            elif tts_task.exception() is None:
                try:
                    await tts_task.result().close()
                except Exception:  # noqa: BLE001
                    pass

    async def _say(self, tts: Any, sentence: str, spoken: list[str], turn_id: str) -> None:
        if spoken and spoken[-1].casefold() == sentence.casefold():
            return  # adjacent repeat, a known failure of small streamed models
        spoken.append(sentence)
        await tts.send(json.dumps({"type": "text", "text": sentence + " <flush> "}))
        await self.emit({"type": "turn", "role": "assistant", "id": turn_id, "text": " ".join(spoken), "done": False})
        if self.cfg.log_transcripts:
            self.log("assistant: %s", sentence)

    async def _pump_tts(self, tts: Any) -> None:
        """Forward TTS audio to the avatar as it arrives, until Gradium's end_of_stream."""
        async for raw in tts:
            message = json.loads(raw)
            kind = message.get("type")
            if kind == "audio" and self.media:
                if self._tts_first_audio is None:
                    self._tts_first_audio = time.monotonic()
                await self.media.speak(message["audio"])
            elif kind == "error":
                raise RuntimeError(f"TTS error: {message.get('message')}")
            elif kind == "end_of_stream":
                return


# ── HTTP + WebSocket server ───────────────────────────────────────────────────

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}
CSP = ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net blob:; worker-src blob:; "
       "connect-src 'self' ws: wss: https:; media-src 'self' blob: mediastream:; img-src 'self' data:; "
       "style-src 'self'; base-uri 'none'; frame-ancestors 'none'")


def http_response(status: HTTPStatus, body: bytes, content_type: str) -> Response:
    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    headers["Cache-Control"] = "no-store"
    headers["Content-Security-Policy"] = CSP
    headers["Permissions-Policy"] = "microphone=(self), camera=()"
    headers["Connection"] = "close"
    return Response(status.value, status.phrase, headers, body)


class Server:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.live: dict[str, str] = {}  # our session id -> LiveAvatar session id
        self.persona = load_prompt(cfg.prompts_dir / "instructions.md",
                                   "You are a friendly presenter in a live voice conversation.")
        self.greeting = load_prompt(cfg.prompts_dir / "greeting.md", "", limit=600)

    def process_request(self, connection: Any, request: Any) -> Optional[Response]:
        path = request.path.split("?", 1)[0]
        if path == "/ws":
            return None
        if path == "/healthz":
            return http_response(HTTPStatus.OK, b"ok", "text/plain")
        name = "index.html" if path == "/" else path.lstrip("/")
        static = self.cfg.static_dir.resolve()
        target = (static / name).resolve()
        if target.parent != static or not target.is_file() or target.suffix not in MIME:
            return http_response(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        return http_response(HTTPStatus.OK, target.read_bytes(), MIME[target.suffix])

    async def handle(self, browser: Any) -> None:
        async def fail(message: str) -> None:
            await browser.send(json.dumps({"type": "error", "message": message}))
            await browser.close()

        missing = self.cfg.missing()
        if missing:
            await fail("server is missing configuration: " + ", ".join(missing))
            return
        if len(self.live) >= self.cfg.max_sessions:
            await fail("too many live sessions; try again in a moment")
            return
        session = Session(self.cfg, browser, self.persona, self.greeting)
        self.live[session.id] = ""
        try:
            try:
                upstream = await asyncio.to_thread(start_liveavatar_session, self.cfg)
            except (LiveAvatarError, requests.RequestException) as exc:
                log.error("[%s] session start failed: %s", session.id, exc)
                # Upstream detail (out of credits, bad avatar id) reaches the browser only on
                # a loopback-bound local starter; a hosted deployment returns a generic error.
                await fail(str(exc) if is_loopback_host(self.cfg.host) else "could not start an avatar session")
                return
            self.live[session.id] = upstream.session_id
            log.info("[%s] LiveAvatar session %s started", session.id, upstream.session_id)
            await session.run(upstream)
        finally:
            upstream_id = self.live.pop(session.id, "")
            if upstream_id:
                try:
                    await asyncio.to_thread(stop_liveavatar_session, self.cfg, upstream_id, session.stop_reason)
                    log.info("[%s] LiveAvatar session stopped (%s)", session.id, session.stop_reason)
                except (LiveAvatarError, requests.RequestException) as exc:
                    log.warning("[%s] upstream stop failed: %s", session.id, exc)

    async def serve_forever(self) -> None:
        async with serve(self.handle, self.cfg.host, self.cfg.port, process_request=self.process_request,
                         max_size=512 * 1024) as server:
            log.info("listening on http://%s:%d", self.cfg.host, self.cfg.port)
            await server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gradium voice pipeline for a HeyGen LiveAvatar (LITE mode)")
    parser.add_argument("--env", default=str(HERE / ".env"), help="path to a .env file (default: next to this script)")
    parser.add_argument("--check", action="store_true", help="validate configuration and exit")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.from_env(load_env_file(Path(args.env)))
    problems = cfg.validate()
    for problem in problems:
        print(f"config: {problem}", file=sys.stderr)
    if args.check:
        print("configuration ok" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if any(p.startswith("HOST") or "must use https" in p for p in problems):
        return 1
    if cfg.missing():
        print("sessions will not start until the missing variables are set", file=sys.stderr)
    try:
        asyncio.run(Server(cfg).serve_forever())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
