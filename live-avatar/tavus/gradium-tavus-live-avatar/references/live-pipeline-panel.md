# Live pipeline panel

Every generated project includes this panel. It was built and checked against
`livekit-agents` 1.8.2 with the Tavus plugin: the worker streams small events
over the room's data channel and the call page renders them as one vertical
pipeline beside the avatar, so the user can see what is happening without
reading logs. The avatar remains the primary surface; the panel sits beside it
and can be hidden with a button or the `L` key.

## Design rule: one sentence per stage

Cognitive load is the failure mode. The panel is a single vertical flow in the
order audio travels, with one plain sentence per stage about what it is doing
right now, and one number under it. Nothing else is visible by default.

```text
You                 ●  You are speaking.                     (microphone level meter)
Gradium hears you   ●  Heard "…" · knew you had finished 320 ms later.
Celine thinks       ●  "…reply…" (first words in 186 ms)
Gradium speaks      ●  Voice ready in 440 ms, 4.1 s of speech.
Tavus shows Celine  ●  Celine is speaking.

Celine started answering 546 ms after you stopped talking.
▸ Details
```

- The active stage pulses; finished stages turn green and the connector line
  fills behind them; an error turns the stage red with a sentence saying what
  the user can do.
- The summary sentence is end-of-turn delay + LLM first-token time + TTS
  first-byte time. Word the greeting differently ("Her first words took … to
  prepare") because the user had not spoken yet.
- A blocked microphone is shown on the You, hearing, and avatar rows in plain
  words; the call stays up.
- Raw events with timestamps, the room name, and the Tavus conversation id sit
  behind a collapsed Details disclosure for debugging.
- No stats grid, no per-turn history list, no colour-coded event tags, no
  always-visible timeline. Those were tried and removed for being too dense.

## Worker side: publish events on the data channel

Publish JSON on the room data channel with topic `diagnostics`, reliable
delivery, from a small helper that never raises (telemetry must not break the
call). Emit from synchronous event handlers with `loop.create_task`.

```python
await room.local_participant.publish_data(payload, reliable=True, topic="diagnostics")
```

Event shape: `{"seq": n, "t": epoch_ms, "src": ..., "kind": ..., ...fields}`.
Keep each payload well under 15 KB and cap transcript text at a few hundred
characters.

Sources and kinds that the panel understands:

| src | kind | fields | from |
| --- | --- | --- | --- |
| `job` | `start` | `room`, `face_id`, `pal_id` | job entry |
| `job` | `shutdown` | `reason` | participant left, max call duration |
| `job` | `session_close` | `reason` | `session.on("close")` |
| `avatar` | `creating` | `face_id`, `pal_id` | before `avatar.start()` |
| `avatar` | `created` | `conversation_id`, `ms` | after `avatar.start()` |
| `avatar` | `joined` | `ms` | after `avatar.wait_for_join()` |
| `avatar` | `failed` | `error` (type name only) | startup exception |
| `avatar` | `ended` | `conversation_id`, `ok` | after the Tavus end call |
| `user` | `state` | `old`, `new` | `session.on("user_state_changed")` |
| `agent` | `state` | `old`, `new` | `session.on("agent_state_changed")` |
| `stt` | `transcript` | `text` or `chars`, `final`, `language` | `session.on("user_input_transcribed")` |
| `agent` / `user` | `message` | `role`, `text` or `chars`, `interrupted` | `session.on("conversation_item_added")` |
| `stt` | `metrics` | `metric="EOUMetrics"`, `end_of_utterance_delay`, `transcription_delay`, `speech_id` | `session.on("metrics_collected")` |
| `llm` | `metrics` | `metric="LLMMetrics"`, `ttft`, `duration`, `completion_tokens`, `tokens_per_second`, `cancelled`, `speech_id` | same |
| `tts` | `metrics` | `metric="TTSMetrics"`, `ttfb`, `audio_duration`, `characters_count`, `cancelled`, `speech_id` | same |
| `agent` | `error` | `error` (type name), `recoverable` | `session.on("error")` |
| `room` | `track_published`, `track_subscribed`, `track_muted`, `track_unmuted`, `participant_connected`, `participant_disconnected` | `identity`, `track` | room events |

Forward only the listed metric fields; whole metric objects and `metadata`
stay in server logs. `speech_id` ties the end-of-turn, LLM, and TTS metrics of
one reply together. Metric values are seconds; convert to milliseconds in the
browser.

Transcript text may be included for a local demo the caller is watching. Make
it switchable (`DIAGNOSTICS_TRANSCRIPTS=0` sends character counts only) and
state the choice in the runbook. Never include API keys, upstream response
bodies, or exception messages; send exception type names only.

## Browser side: render the flow

```javascript
room.on(RoomEvent.DataReceived, (payload, participant, kind, topic) => {
  if (topic !== "diagnostics") return;
  handle(JSON.parse(new TextDecoder().decode(payload)));
});
```

Map events to the five rows:

- `user.state` speaking: start a new turn; You is active; hearing is active.
- `stt.transcript`: show the words as they arrive; on `final`, mark hearing
  done. `EOUMetrics` adds "knew you had finished N ms later".
- `agent.state` thinking: thinking is active. `LLMMetrics.ttft` adds "first
  words in N ms". The assistant `message` fills in the reply text and marks
  thinking done.
- `agent.state` speaking: speaking is active and the avatar row says the
  avatar is speaking. `TTSMetrics.ttfb` and `audio_duration` fill the sentence.
- `agent.state` listening: mark thinking and speaking done, avatar row back to
  "on screen, listening", show the summary sentence.
- `avatar.*`: creating, joining, live, failed, ended on the avatar row.
- Browser-side facts the worker cannot know (microphone denied, tracks
  attached) go straight to the rows and to Details.

Insert all text with `textContent`. The microphone level meter uses a Web Audio
analyser on the published microphone track and is the only continuously
animating element besides the active-stage pulse.

## Why the browser participant needs nothing extra

The participant token already grants subscription, and data-channel messages
arrive with the media over the same encrypted connection. The browser does not
need `can_publish_data`; it only receives. The stream reaches only participants
in that room.

## Known limit

When the caller hangs up from the browser, the worker's final `avatar.ended`
event is published after the browser has left the room, so it appears in the
worker log rather than the panel. Everything up to the hangup is visible.

## Tests

Keep the worker tests provider-free: a fake room whose `local_participant`
lacks `publish_data` must not break the job (the helper swallows publish
errors). Add one test that the event sequence for a normal call is `job.start`,
`avatar.creating`, `avatar.created`, `avatar.joined`, and that the shutdown
path emits `avatar.ended` exactly once.
