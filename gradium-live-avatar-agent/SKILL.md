---
name: gradium-live-avatar-agent
description: Build a minimal, extensible live avatar voice agent from an avatar image, a voice description, and an agent role or prompt. Use LiveKit for realtime orchestration, Gradium for Voice Design, STT, and TTS, and LemonSlice for the animated face. Use when creating or modifying this specific voice-avatar stack.
license: MIT
metadata: {"openclaw": {"requires": {"env": ["GRADIUM_API_KEY", "LEMONSLICE_API_KEY", "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]}, "primaryEnv": "GRADIUM_API_KEY"}}
---

# Gradium Live Avatar Agent

Create a working foundation that users can run immediately and later extend
with tools, function calling, memory, retrieval, or domain logic. Keep the base
agent deliberately small. Treat LemonSlice as the face layer over the LiveKit
voice pipeline. Gradium must supply Voice Design, streaming STT, and streaming
TTS in every generated project; do not substitute another speech provider.

## Required intake

Collect the creative inputs in this order, skipping anything the user already
provided:

1. **Reference image:** first ask the user to upload the image or provide a local
   path or public URL. Inspect it before discussing the voice. Do not substitute
   a sample face when no image was provided.
2. **Voice Design prompt:** ask how the character should sound, including useful
   qualities such as vocal age range, tone, accent, texture, energy, pacing, and
   language. Compare the description with the image's visible mood, styling,
   expression, and character archetype. Do not infer sensitive traits such as
   ethnicity, nationality, disability, or gender identity from appearance.
3. **Agent purpose:** after the image and voice are settled, ask what kind of
   live avatar voice agent the user wants—for example, a health coach, language
   teacher, concierge, tutor, or game character—and what it should do. Turn the
   answer into a focused system prompt without changing the user's intent.

The user's chosen voice remains authoritative. Only when the Voice Design
prompt is clearly and substantially at odds with the reference image, pause
once, explain the mismatch neutrally, offer two or three concise voice
directions grounded in the image, and ask whether the contrast is intentional.
If it is intentional, use the user's original prompt without asking again.
Otherwise use their selected or revised direction. Do not repeatedly challenge
an unusual creative choice.

An explicitly supplied permanent Gradium `voice_id` may replace new voice
generation, but otherwise require a Voice Design prompt and use Gradium Voice
Design.

Do not start with questions about LLMs, tools, hosting, frameworks, visual
styling, or advanced features. Settle the three creative inputs first, then
collect the service setup needed to build and run the agent.

## Credentials and LLM choice

After creative intake:

- Ask the user to configure `GRADIUM_API_KEY` and `LEMONSLICE_API_KEY` as
  server-side environment variables or deployment secrets. Give the exact file
  path or shell command appropriate to the generated project. Never ask them to
  paste keys into chat, source code, or the browser UI.
- Ask whether they have a linked LiveKit Cloud project with Inference credits.
  When they do, use LiveKit Inference with
  `google/gemma-4-31b-it`, LiveKit's recommended low-latency default for voice
  agents. Do not use LiveKit Inference for STT or TTS in this skill.
- When the user does not have LiveKit Inference credits, ask for their LLM setup:
  provider or OpenAI-compatible base URL, model ID, and the name of the
  server-side API-key variable if one is needed. Only the LLM changes; keep
  Gradium Voice Design, STT, and TTS.
- A local or self-hosted LLM is acceptable when the user provides a compatible
  endpoint. Verify `/models` and one small completion before wiring it into the
  realtime session.

## Default architecture

Unless the user specifies otherwise:

- Use Python LiveKit Agents.
- Use the LiveKit Gradium plugin for streaming STT and TTS.
- Use `inference.LLM(model="google/gemma-4-31b-it")` by default when LiveKit
  Inference credits are available; otherwise use the user-provided LLM setup.
- Use the LiveKit LemonSlice plugin with exactly one image source.
- Keep voice creation separate from runtime. Runtime receives a permanent
  Gradium `voice_id`; it must not create a new voice whenever the app starts.
- Make the browser a minimal call surface: remote avatar video, avatar audio,
  start/end call, microphone toggle, and a small connection state. Do not build
  a character editor, voice-design form, transcript panel, dashboard, or model
  playground unless explicitly requested.
- Prefer the LiveKit CLI (`lk`) for project linking, agent initialization,
  configuration, local development, simulations, deployment, secrets, status,
  versions, and logs. Use the LiveKit SDK for runtime sessions, room tokens, and
  explicit dispatch. If a LiveKit MCP integration is available in the current
  environment, use it for supported LiveKit operations that it can complete
  faster; otherwise continue with CLI or SDK. Do not add MCP to the generated
  agent merely because the build environment exposes it. Provider-specific
  provisioning still uses the Gradium and LemonSlice APIs.

## Build workflow

1. Complete the ordered creative intake and the one-time image/voice fit check.
   Save or reference the supplied avatar image inside the generated project
   without altering its appearance unless requested.
2. Read [references/livekit-runtime.md](references/livekit-runtime.md) before
   creating or changing the agent worker.
3. Read [references/voice-provisioning.md](references/voice-provisioning.md) and
   implement the voice description as a one-time provisioning flow. Generate
   an audition when credentials and authorization are available, and promote
   only the voice the user approves.
4. Read
   [references/avatar-only-frontend.md](references/avatar-only-frontend.md) and
   keep the web surface intentionally minimal.
5. Generate an independently runnable project with `.env.example`, concise
   setup instructions, and focused tests.
6. Use the fastest available LiveKit control surface: MCP when already available
   and suitable, otherwise `lk`, with the SDK for runtime application behavior.
   When LiveKit Cloud is in scope, use `lk cloud auth` (or a manually linked
   project), `lk agent config --id ...` for an existing agent, and
   `lk agent dockerfile` to create the deployment boundary. Do not create or
   deploy a hosted agent without the user's authorization.
7. Verify imports and mocked provider boundaries. Run a credentialed live call
   only when the user has supplied the necessary access and asked to exercise
   external services.

If provider credentials are not configured, still finish the project. Put only
variable names in `.env.example`, explain where the user should add secrets,
and verify provider boundaries with mocks. Never ask the user to paste secrets
into source code or the browser UI.

## Minimal product contract

The generated baseline should contain only:

- one LiveKit worker with the user's agent prompt;
- Gradium Voice Design, streaming STT, and the approved designed TTS voice;
- one LemonSlice avatar based on the supplied image;
- one server-side LiveKit token and agent-dispatch endpoint;
- one avatar-only browser call surface;
- one-time voice provisioning outside the browser UI;
- configuration, a short runbook, and focused tests.

Do not add example business tools, databases, accounts, transcripts, settings
screens, dashboards, or authentication unless requested. Preserve obvious
extension seams in the `Agent` class so users can add LiveKit tools and function
calling without replacing the speech/avatar pipeline. Document that seam with
one short example or pointer; do not implement speculative tools.

## Required runtime invariants

- Keep Gradium, LiveKit, and LemonSlice keys server-side.
- Never replace Gradium Voice Design, STT, or TTS with LiveKit Inference or a
  third-party speech provider; the LLM is the only provider-selectable layer.
- Pass the permanent Gradium `voice_id` to `gradium.TTS`.
- Set Gradium text rewriting to the conversation language.
- Start the LemonSlice avatar before starting the LiveKit `AgentSession`.
- Set LiveKit room output to `audio_output=False`; LemonSlice publishes the
  final synchronized avatar audio and video, and a second agent audio track
  would create doubled speech.
- Wait for the avatar participant before generating the first reply.
- Keep spoken responses short and interruption-friendly.
- When using a custom OpenAI-compatible LLM, guard against an empty completed
  generation and adjacent repeated sentence blocks before sending text to TTS;
  use a single retry and a short deterministic fallback.
- Prefer Gradium STT turn completion directly and configure a short bounded
  endpointing window. Do not stack an unnecessary long VAD wait after Gradium
  has already finalized the transcript.
- Preserve the user's domain role and behavioral instructions as the authority
  for the system prompt. Add only voice-conversation guidance such as concise
  responses, no markdown, and interruption-friendly phrasing.
- Use only one of `agent_image`, `agent_image_url`, or `agent_id` in each
  `lemonslice.AvatarSession`.
- Do not place image bytes in browser tokens. For a static agent, load the image
  in the worker. For per-session characters, pass a short-lived asset reference
  in dispatch metadata; use embedded compressed bytes only for a local demo.
- Do not create paid voices, rooms, deployments, or hosted resources merely to
  test generated code without the user's authorization.

## Expected project shape

Adapt names to the existing repository, but preserve these boundaries:

```text
agent.py                  LiveKit AgentSession + Gradium + LemonSlice
token_server.*            Server-side LiveKit token/dispatch creation
scripts/design_voice.py   Optional one-time Gradium voice provisioning
static/ or frontend/      Avatar-only call surface
.env.example              Variable names without secrets
tests/                    Profile, provisioning, and dispatch tests
README.md                 Setup, two-process run flow, and architecture
```

When modifying an existing app, integrate into its conventions instead of
forcing this exact layout.

## Completion checks

- The worker imports and constructs the installed Gradium and LemonSlice
  plugins successfully.
- The supplied image, voice description or explicit voice ID, and agent purpose
  are reflected in the generated configuration and agent instructions.
- A clearly mismatched image and Voice Design prompt triggers exactly one
  confirmation with image-grounded suggestions, while an intentional contrast
  is preserved.
- `LEMONSLICE_API_KEY` is documented as a required server-side secret.
- LiveKit Inference uses `google/gemma-4-31b-it` by default when credits are
  available, and lack of credits routes only the LLM to the user's setup.
- The chosen image input exists or is validated at the boundary.
- The web client attaches remote video and audio and does not render unrelated
  setup controls.
- Microphone capture uses echo cancellation, starts immediately after the room
  connects, and is not coupled to avatar video arrival. Monitor the published
  microphone track and recover it if the browser track unexpectedly ends.
- Voice provisioning cleans up rejected candidates and returns a permanent
  `voice_id`.
- Tests do not contact paid external APIs.
- Response-guard tests cover an empty model turn and repeated sentence blocks
  when a custom OpenAI-compatible endpoint is used.
- The runbook names every required environment variable and starts both the web
  service and named LiveKit worker.
- The runbook identifies where tools or function calling can be added without
  expanding the default implementation.
