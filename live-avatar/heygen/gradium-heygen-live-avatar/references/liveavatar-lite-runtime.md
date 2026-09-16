# LiveAvatar LITE runtime

LITE mode is LiveAvatar with the conversation brain removed: you bring STT, LLM,
and TTS, and LiveAvatar renders a lip-synced face from the audio you send. It
costs 1 credit per minute (FULL mode costs 2). All shapes below were checked
against `https://docs.liveavatar.com/openapi.json` and the LITE events page
(`https://docs.liveavatar.com/docs/lite-mode/events.md`).

## Session lifecycle (REST)

Base URL `https://api.liveavatar.com`. Backend calls use the `X-API-KEY`
header; the start call uses the session token instead.

| Step | Call | Notes |
| --- | --- | --- |
| Mint | `POST /v1/sessions/token` with `X-API-KEY` | Body `{"mode": "LITE", "avatar_id": "<uuid>"}` plus optional `is_sandbox`, `video_settings: {"quality": "very_high\|high\|medium\|low"}`, `max_session_duration` (seconds, within your plan's limit). Returns `data.session_id`, `data.session_token`. |
| Start | `POST /v1/sessions/start` with `Authorization: Bearer <session_token>` and body `{}` | Returns `data.livekit_url`, `data.livekit_client_token`, `data.ws_url`, optional `livekit_agent_token`, `max_session_duration`. **Billing starts here.** |
| Keep alive | `POST /v1/sessions/keep-alive` `{"session_id"}` | REST twin of the websocket `session.keep_alive`. |
| Stop | `POST /v1/sessions/stop` `{"session_id", "reason"}` | Reasons: `USER_CLOSED`, `USER_DISCONNECTED`, `IDLE_TIMEOUT`, `MAX_DURATION_REACHED`, `SERVER_ERROR`, `AGENT_HANG_UP`, `UNKNOWN`. Use the API key form so teardown does not depend on the session JWT still being valid. |

Responses are wrapped: `{"code": 100, "message": "...", "data": {...}}`. Read
`data`. Errors come back with `code` 4xxx and a `message`; a 401 means the
API key, a 402/403-style message usually means credits or concurrency.

Rules that matter:

- **Bare LITE payload.** Do not send `livekit_config`: it means bring-your-own
  LiveKit and the response then has no `livekit_url`/`livekit_client_token`
  for the browser. `ws_url` is only returned for this custom LITE path, and
  without it there is no media leg. Treat a start response missing any of the
  three fields as a failure, stop the session, and surface an error.
- **Stop on every path.** Browser disconnect, idle timeout, max duration,
  provider failure, process shutdown. A one-legged session is a bill with
  nobody listening. The reference implementation's idle timeout counts
  microphone frames only, because the browser streams silence continuously and
  a browser that stopped sending audio is a session nobody can use.
- **Requests hygiene.** Finite timeouts, `allow_redirects=False`, never log or
  return the session token or API key. Upstream error bodies may be shown to
  the developer on a loopback-bound starter; a hosted deployment returns a
  generic error and keeps the body in server logs.

## Avatar selection

`GET /v1/avatars/public?page_size=20` needs no auth and returns
`data.results[]` with `id`, `name`, `type` (`VIDEO` or `IMAGE`), `status`
(`ACTIVE`, `INIT`, `DEPLOYING`, `FAILED`), `preview_url`, `is_1080p`. Prefer an
`ACTIVE` `VIDEO` avatar when the user has no preference and log the choice by
name. Custom avatars come from the user's LiveAvatar dashboard (IMAGE from a
photo, VIDEO from about two minutes of footage) and are referenced by ID.

Sandbox: `"is_sandbox": true` in the token body. Sessions are free, last about
one minute, and use the sandbox avatar regardless of `avatar_id`. Use it for
the first wiring test and for demos of the plumbing.

## Media websocket (the avatar's ear)

Connect to `ws_url` from the server. All frames are JSON text. Every event
carries `type`; commands may carry an `event_id` and the server echoes it as
`source_event_id` on acknowledgements.

Client → server:

| Event | Payload | Meaning |
| --- | --- | --- |
| `agent.speak` | `{"audio": "<base64 PCM16 24 kHz mono>"}` | Append to the current utterance. The first chunk after `speak_end` or `interrupt` opens a new utterance. Keep chunks under 1 MB; about one second is the documented sweet spot, smaller is fine. |
| `agent.speak_end` | optional `{"audio": ...}` | Seal the utterance. Send it once the TTS stream ended. |
| `agent.interrupt` | none | Drop queued audio and pending video, seal the utterance, return to idle. |
| `agent.start_listening` / `agent.stop_listening` | none | Pose changes while the user talks. Skip them while the avatar is talking. |
| `session.keep_alive` | none | Extends the 5 minute idle window. Send every 2 to 3 minutes even when the conversation is active. |

Server → client:

| Event | Meaning |
| --- | --- |
| `session.state_updated` `{"state": "new"\|"connected"\|"disconnected"}` | **Readiness is `connected`, not socket open.** Commands sent earlier are silently dropped; a missing greeting is the symptom. |
| `agent.state_updated` `{"previous_state", "new_state"}` with `idle`, `listening`, `talking` | The authoritative "is the avatar speaking" signal. Use it for barge-in decisions and the speaking glow. |
| `agent.speak_started`, `agent.speak_ended`, `agent.speak_interrupted` | Utterance lifecycle. |
| `agent.audio_buffer_appended`, `agent.audio_buffer_committed`, `agent.audio_buffer_cleared` | Acknowledgements. |
| `error` `{"error": {"type", "message", "event_id"}}` | Types include `invalid_request_error`, `server_error`, `video_starvation` (audio arrived too slowly for the renderer). |
| `warning` `{"warning": {"type", "message"}}` | Non-fatal. Log it. |

Audio arrives faster than it plays, so the media server can hold several
seconds of speech the model has already abandoned. Track a playback estimate
(bytes sent ÷ 48 000 bytes per second) in addition to `agent.state_updated`, so
"the avatar is still talking" stays true through the queued tail.

Reconnect with bounded backoff if the socket drops. Audio produced during the
gap is lost; do not replay it, that would desynchronize the face further.

## Teardown order

1. Cancel the LLM stream and close the TTS socket.
2. Send `agent.interrupt` if anything might still be queued, or let the last
   utterance finish when the user simply ended the call.
3. Close the media websocket and the Gradium STT socket.
4. `POST /v1/sessions/stop` with the reason.

## Why not the LiveAvatar web SDK

The SDK expects the browser to hold the session token and call start itself.
Here the server must call start because the response is the only place
`ws_url` comes back, and the audio leg cannot exist without it. After a
server-side start the browser only needs to join the LiveKit room and attach
two tracks, which is about fifty lines of `livekit-client`.

## Alternative: LiveKit Agents plugin

If the project already runs LiveKit Agents, keep that runtime and swap the
face: install `livekit-agents[gradium,liveavatar]~=1.5`, keep `gradium.STT`
and `gradium.TTS` exactly as in the `gradium-live-avatar-agent` skill, and
replace the LemonSlice avatar with:

```python
from livekit.plugins import liveavatar

avatar = liveavatar.AvatarSession(avatar_id=os.environ["LIVEAVATAR_AVATAR_ID"])
await avatar.start(session, room=ctx.room)   # before session.start(...)
await session.start(room=ctx.room, agent=agent,
                    room_options=room_io.RoomOptions(audio_output=False))
```

`LIVEAVATAR_API_KEY` is read from the environment; `is_sandbox=True` gives free
test sessions. That path needs a LiveKit Cloud project of your own and gives
you LiveKit's tool-calling seam instead of the card channel described in
[tools-and-overlays.md](tools-and-overlays.md). The Pipecat equivalent is
`pipecat-ai[heygen]` with `HeyGenVideoService`.
