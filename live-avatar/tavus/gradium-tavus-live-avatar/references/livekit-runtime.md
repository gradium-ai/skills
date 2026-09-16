# LiveKit runtime assembly (Tavus)

## Contents

- Dependencies
- Canonical worker order
- Tavus specifics
- Turn and media diagnostics
- Configuration and LLM routing
- OpenAI-compatible LLM fallback
- Local LiveKit limitation
- LiveKit CLI, SDK, and MCP workflow
- Static and per-session characters
- Agent prompt and extension seam
- Security and privacy boundaries

Use the first-party LiveKit plugins when building the standard Python runtime:

```python
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    inference,
    room_io,
)
from livekit.plugins import gradium, tavus, openai
```

## Dependencies

A compatible dependency declaration (checked against `livekit-agents` 1.8.2,
where `livekit.plugins.tavus.AvatarSession` and `AvatarSession.wait_for_join`
exist) is:

```toml
dependencies = [
  "livekit-agents[gradium,tavus,openai]>=1.8.2,<1.9",
  "livekit-api>=1.2,<2",
  "python-dotenv>=1,<2",
]
```

Resolve and commit a lockfile for the generated project. Version ranges describe
compatibility; the lockfile records the exact reviewed build. Update dependencies
deliberately and rerun the mocked provider and dispatch tests.

## Canonical worker order

Keep this lifecycle order. It makes the Tavus avatar participant the
published audio/video output for the voice agent and prevents a duplicate audio
track.

```python
max_completion_tokens = int(os.getenv("LLM_MAX_COMPLETION_TOKENS", "256"))
if not 128 <= max_completion_tokens <= 1024:
    raise ValueError("LLM_MAX_COMPLETION_TOKENS must be between 128 and 1024")

session = AgentSession(
    llm=inference.LLM(
        model=os.getenv("LIVEKIT_LLM", "google/gemma-4-31b-it"),
        extra_kwargs={
            "temperature": 0.3,
            "max_completion_tokens": max_completion_tokens,
        },
    ),
    stt=gradium.STT(language=language),
    tts=gradium.TTS(
        voice_id=voice_id,
        model_name=os.getenv("GRADIUM_TTS_MODEL_NAME", "gradium-tts-beta"),
        json_config={"rewrite_rules": language, "speed": speed},
    ),
    turn_handling={
        "turn_detection": "stt",
        "endpointing": {"min_delay": 0.15, "max_delay": 0.8},
        "interruption": {"resume_false_interruption": False},
    },
    transcription_timeout=3.0,
)

await ctx.connect()
await ctx.wait_for_participant()   # a human must be in the room before paying for an avatar

face_id = os.getenv("TAVUS_FACE_ID")
pal_id = os.getenv("TAVUS_PAL_ID")
avatar_kwargs = {}
if face_id:
    avatar_kwargs["face_id"] = face_id
if pal_id:
    avatar_kwargs["pal_id"] = pal_id   # must be an echo-mode PAL with a livekit transport layer
avatar = tavus.AvatarSession(**avatar_kwargs)

try:
    await asyncio.wait_for(avatar.start(session, room=ctx.room), timeout=30)
    await avatar.wait_for_join(timeout=45)   # video track is live before the first word
except Exception:
    await session.aclose()
    raise  # surface a small provider-unavailable error to the client

# The base AvatarSession already registers avatar.aclose() as a shutdown callback.
# Register provider-specific teardown (see the provider section) only once, and stop
# the job when the human leaves so an avatar never talks to an empty, billing room.
@ctx.room.on("participant_disconnected")
def _on_left(participant: rtc.RemoteParticipant) -> None:
    if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD:
        ctx.shutdown(reason="participant left")

if not any(p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD
           for p in ctx.room.remote_participants.values()):
    ctx.shutdown(reason="participant left before avatar start")
    return

await session.start(
    room=ctx.room,
    agent=CharacterAgent(instructions=character_prompt),
    room_options=room_io.RoomOptions(audio_output=False),
)
session.generate_reply()
```

Catch startup timeouts at the job boundary, close any started session, and expose
only a small provider-unavailable error to the client. Do not leave a worker job
waiting indefinitely or include upstream response bodies in browser errors.

Avatar startup takes several seconds and starts billing. Wait for the human
participant before starting the avatar, and stop the job when the last human
leaves; without this a browser that fails during setup leaves the avatar
greeting an empty room until the room's departure timeout closes it (observed:
about 30 seconds on LiveKit Cloud). Also enforce a worker-side maximum call
duration as a spend cap. `python agent.py dev` still works on `livekit-agents`
1.8.x but the CLI marks it deprecated in favour of `lk agent dev`; either is fine.

Gradium already supplies streaming speech boundaries and final transcripts.
Using `turn_detection="stt"` avoids adding a second long endpointing wait after
Gradium finalizes a turn. Treat `0.15` and `0.8` seconds as low-latency baseline
values: raise them for agents whose users naturally pause mid-sentence.

## Tavus specifics

The plugin mints a room-scoped LiveKit token for the avatar participant
(identity `tavus-avatar-agent` by default, kind `agent`, attribute
`lk.publish_on_behalf` set to the worker's identity), asks Tavus to join the room
with it, and replaces the session's audio output with a data stream to that
participant. The avatar then publishes synchronized audio and video. Agent audio
reaches Tavus at 24 kHz.

- The plugin reads `TAVUS_API_KEY` from the environment. `replica_id` and
  `persona_id` still work as deprecated aliases for `face_id` and `pal_id`; use
  the new names.
- Each `avatar.start()` creates a Tavus conversation (`POST /v2/conversations`)
  that joins the LiveKit room. The conversation id is exposed as
  `avatar.conversation_id`; log it so a stuck session can be ended from the
  Tavus dashboard.
- Agent audio is streamed to Tavus at 24 kHz and republished by the avatar
  participant. Gradium's 24 kHz output is passed through without resampling.
- The plugin waits for the avatar's video track before releasing audio, so the
  first sentence is not spoken against a black frame. Still wrap `wait_for_join`
  in a finite timeout.
- A conversation keeps billing until it ends. The plugin's `aclose()` only
  removes the avatar participant from the room; Tavus then ends the conversation
  when its participant is gone, but the plugin never calls the end endpoint
  itself. Call `POST
  https://tavusapi.com/v2/conversations/{conversation_id}/end` with a finite
  timeout on every shutdown path (verified live: it returns 200 and the
  conversation leaves the active list immediately), then `aclose()`. The base
  `AvatarSession.start()` already registers `aclose` as a job shutdown callback,
  so register one combined idempotent callback rather than a second `aclose`.
- With the stock PAL there is no Tavus-side call cap, so enforce a worker-side
  maximum call duration (for example 600 seconds, then `ctx.shutdown()`).
- Conversations are limited by your plan's concurrent-stream count (1 on Free, 3
  on Starter, 10 on Growth). Surface a restrained "busy" error rather than
  retrying in a loop.

Avatar movement, expression, and identity belong to the Tavus configuration.
Character knowledge and conversational behavior belong in the LiveKit `Agent`
instructions.

## Turn and media diagnostics

Log the room name and lifecycle stage for `user_state_changed`,
`user_input_transcribed`, `agent_state_changed`, `conversation_item_added`,
`error`, and `close`. Include `ChatMessage.metrics` on committed messages so a
slow turn can be separated into endpointing, LLM first-token/first-sentence,
TTS first-byte, and avatar playback latency. Do not log transcript contents by
default.

Also log remote audio publication, mute/unmute, and participant disconnect
events, plus the Tavus session or conversation identifier the plugin exposes.
These signals distinguish an STT/provider stall from a browser that stopped
publishing microphone audio, and let you end a stuck session upstream.

## Configuration

Required environment variables:

```dotenv
GRADIUM_API_KEY=
GRADIUM_VOICE_ID=
TAVUS_API_KEY=
TAVUS_FACE_ID=
TAVUS_PAL_ID=
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
AGENT_NAME=gradium-tavus-live-avatar
LLM_MAX_COMPLETION_TOKENS=256
```

`TAVUS_API_KEY` is required for an end-to-end avatar session. Tell the user
where to add it as a server-side secret; never request its value in chat or put
it in a browser-facing configuration.

`TAVUS_FACE_ID` and `TAVUS_PAL_ID` are optional. Omit both for the stock
LiveKit PAL and face. A custom PAL must have `pipeline_mode: echo` and a
`livekit` transport layer or the conversation will not attach to the room.

Optional variables:

```dotenv
GRADIUM_TTS_MODEL_NAME=gradium-tts-beta
LIVEKIT_LLM=google/gemma-4-31b-it
```

Both `gradium-tts-beta` and the plugin default `default` are accepted by the
live API (checked September 2026); use the same model for auditions and runtime.

Use a named `AgentServer` session and dispatch the same `AGENT_NAME` from the
token server. Never send `LIVEKIT_API_SECRET` to the browser.

For token issuance, dispatch authorization, input validation, and production
deployment rules, follow
[security-and-privacy.md](security-and-privacy.md). An unauthenticated endpoint
must bind to loopback and must not be exposed through a tunnel.

## LLM routing

When the user has LiveKit Inference credits, use the Inference `LLM` class with
`google/gemma-4-31b-it`. This is the default LLM only. Continue using Gradium
for both STT and TTS.

If the user says they do not have LiveKit Inference credits, ask for their LLM
provider or OpenAI-compatible endpoint, model identifier, and required
server-side credential variable. Do not silently choose another paid provider.
Changing the LLM must not change the Gradium speech pipeline or Tavus avatar setup.

## OpenAI-compatible LLM endpoints

When the user supplies an OpenAI-compatible endpoint as the no-credits fallback,
use the Chat Completions adapter rather than LiveKit Inference:

```python
llm = openai.LLM(
    model=os.environ["LLM_MODEL"],
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.getenv("LLM_API_KEY", "not-needed"),
    temperature=0.3,
    max_completion_tokens=int(os.getenv("LLM_MAX_COMPLETION_TOKENS", "256")),
)
```

Normalize a discovery URL such as `https://host/v1/models` to the API root
`https://host/v1`. Query `/models` once to confirm the model identifier, then
make a small Chat Completions request before integrating it. Keep the API key
server-side. `openai.LLM` preserves the normal LiveKit tool/function-calling
extension seam for compatible models.

Treat the base URL as trusted administrator configuration, not a browser or
per-session field. Prefer HTTPS for non-loopback endpoints and tell the user that
the configured service receives the system prompt, conversation context, and
transcribed speech. Put finite connect/read timeouts on discovery and completion
requests and cap response sizes.

OpenAI-compatible endpoints vary in streaming reliability. For a short-form
voice agent, validate the completed model turn before handing it to TTS:

- Retry once when a request completes without text or tool calls. For the retry,
  replace the long primary instruction with a compact safety-preserving
  instruction and include only the latest few user/assistant messages. Then
  speak a brief deterministic fallback instead of leaving the caller in silence.
- Remove adjacent repeated sentences or repeated sentence blocks before TTS.
- Log only the guard action and character counts by default, not transcript
  contents.

This guard may buffer a short answer until generation completes. Keep the spoken
response short, but leave enough completion budget for models that emit internal
reasoning before visible text; `256` is the baseline and should remain
configurable. Preserve tool-call chunks and their ordering if the agent later
gains tools; do not turn the guard into a text-only abstraction that breaks
LiveKit's normal function-calling seam. Test text, empty, repeated, and tool-call
turns independently.

## Local LiveKit limitation

For local transport development, `livekit-server --dev` exposes
`ws://127.0.0.1:7880` with the development key `devkey` and secret `secret`.
Use these credentials only for local development.

This does not provide a complete Tavus test by itself. Tavus's avatar worker joins
the room from its hosted service, so a loopback or private-LAN LiveKit URL is
not reachable by the avatar participant. Use LiveKit Cloud or a properly
self-hosted public LiveKit deployment with TLS and WebRTC media ports for an
end-to-end conversation. Do not suggest a simple HTTP tunnel as a complete
substitute for LiveKit's signaling and WebRTC networking.

## LiveKit CLI, SDK, and MCP workflow

Use the current `lk` CLI for LiveKit-owned operations. Install it on macOS with
`brew install livekit-cli`, then link a Cloud project with `lk cloud auth` or,
when credentials are already stored locally, `lk project add` and
`lk project set-default`.

Prefer these control surfaces by responsibility:

- Use an already-configured LiveKit MCP integration for operations it explicitly
  exposes when that is faster than shell orchestration. Do not assume one exists
  and do not invent unsupported tools.
- Use `lk agent` for scaffolding, local `dev`/`console`, simulations, Cloud agent
  configuration, deployment, secrets, status, versions, rollback, and logs.
- Use the LiveKit Python SDK inside the application for access tokens, rooms,
  dispatch, and realtime agent behavior.
- MCP support inside LiveKit Agents is an optional way to give the finished
  avatar agent tools. Do not enable that runtime feature unless the user asks
  for tools or function calling.

For a pre-existing Cloud agent, bind the source directory once:

```bash
lk agent config --id CA_xxx .
lk agent dockerfile .
```

This creates `livekit.toml`, `Dockerfile`, and `.dockerignore`. Commit the
deployment files but never `.env`. For a new agent, use `lk agent create`; for
the bound existing agent, use `lk agent deploy`. Pass provider settings through
`--secrets-file .env`; LiveKit Cloud automatically supplies its own
`LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` at runtime and ignores
those entries in the secrets file.

```bash
lk agent deploy --secrets-file .env
lk agent status
lk agent logs
lk agent secrets
```

Use `lk agent dev` for local hot-reload when the installed CLI recognizes the
project entrypoint; otherwise use the Python worker command
(`uv run python agent.py dev`). The CLI manages the Cloud deployment, but it
does not replace Gradium Voice Design or the Tavus API.

## Static versus per-session characters

For one fixed agent, read `GRADIUM_VOICE_ID`, the character prompt, and the
Tavus identifier in the worker. This is the simplest and preferred skill output.

For per-session agents, send only a compact validated profile in explicit
LiveKit dispatch metadata and resolve it server-side to an allowlisted Tavus
identifier and Gradium `voice_id`. Never accept a raw provider identifier,
image URL, or filesystem path from the participant, and do not embed image data
in the participant JWT.

Parse metadata with an exact schema, reject unknown keys and control characters,
and cap every string and the serialized payload. The server—not the browser—must
choose the dispatched agent and deployment.

## Agent prompt

Treat the user's description of what the agent should do as the source of truth.
Turn it into a focused system prompt that states the role, conversation goal,
behavior, and relevant domain boundaries. Add only presentation rules useful to
a spoken interaction: default to one or two short sentences, avoid markdown and
stage directions, and make answers easy to interrupt. Do not invent a persona,
workflow, or expertise the user did not request.

## Extension seam

Keep the initial `Agent` subclass free of speculative tools. Users should be
able to extend it through LiveKit's normal tool/function-calling mechanism
without changing Gradium STT/TTS, Tavus startup, room output, or token
dispatch. Point to the `Agent` subclass and its tool registration as the place
to extend behavior; avoid adding an abstraction layer solely for future use.

Before adding tools, define per-tool authorization and argument validation that
does not depend on the character prompt. A user-authored persona is never
authority to read secrets, access unrelated files, or perform external actions.

## Security and privacy boundaries

Use [security-and-privacy.md](security-and-privacy.md) for the required trust
boundaries around creative input, image handling, token issuance, dispatch,
microphone recovery, telemetry, provider data flows, secrets, and dependencies.
