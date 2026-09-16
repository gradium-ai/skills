# Voice pipeline: Gradium STT → LLM → Gradium TTS

HeyGen's demo pairs the avatar with a full-duplex speech model and has to
project turns out of transcript deltas. This pipeline is turn-based by
construction, which fits LiveAvatar's turn-based protocol directly: one TTS
session per reply, `agent.speak_end` when it ends, `agent.interrupt` when the
user cuts in.

## Speech in: Gradium STT websocket

Connect to `wss://api.gradium.ai/api/speech/asr` with the `x-api-key` header
and send the setup first:

```json
{"type": "setup", "model_name": "default", "input_format": "pcm_24000",
 "json_config": {"language": "en", "delay_in_frames": 8,
                 "keywords": {"words": ["Gradium", "HeyGen"], "boost": 3}}}
```

- The browser downsamples to 24 kHz PCM16 in an AudioWorklet and sends 80 ms
  frames (1920 samples); the server forwards each as
  `{"type": "audio", "audio": "<base64>"}` unchanged.
- `delay_in_frames` is the latency knob: 7 to 10 for conversation. Keyword
  boosting matters more at low values. Words are single tokens, case and
  accent sensitive, `boost` 3 is the strong default.
- `text` messages are single words without separators; join with spaces.
- Sessions cap at 300 seconds. Rotate the socket at a turn boundary once it is
  older than about 240 seconds: send `end_of_stream`, let the read loop exit,
  reconnect immediately. Never rotate mid-utterance.

### Turn-taking from semantic VAD

Every 80 ms the server sends `{"type": "step", "vad": [{"horizon_s", "inactivity_prob"}, ...]}`.
`inactivity_prob` at horizon H is the probability the speaker is still silent
H seconds from now; it stays low through a pause inside an unfinished sentence.

Policy used by the reference implementation:

1. Only consider steps while there are pending words.
2. Read the entry whose `horizon_s` equals `TURN_HORIZON_S` (default 2.0).
3. End the turn when `inactivity_prob > TURN_THRESHOLD` (default 0.7) on
   `TURN_CONSECUTIVE_STEPS` steps in a row (default 2).
4. Send `{"type": "flush", "flush_id": N}` and take the transcript only after
   the matching `flushed` arrives; a flush releases the last one or two words.
   If no `flushed` arrives within 3 seconds, finish the turn anyway so
   turn-taking cannot wedge.

Tune per persona: lower threshold or shorter horizon for a snappy assistant,
higher and longer for tutors whose learners pause to think. Do not add a
second VAD in front of Gradium; it gates the audio the model needs and
double-fires turns.

### Barge-in and backchannels

Echo cancellation in the browser keeps the avatar's own voice out of the
microphone, so a `text` word arriving while the avatar is talking is the user.
Not every such word is an interruption: "mm-hmm" is a backchannel.

- First word over the talking avatar: start watching, do nothing audible.
- Second word (`BARGE_IN_WORDS`): cancel the LLM stream, close the TTS socket,
  send `agent.interrupt`, notify the browser (`interrupted`), and record the
  partial reply in history with an `[interrupted]` marker so the model knows
  what was actually heard.
- When a turn ends with fewer than two words and the avatar was still talking,
  drop it as a backchannel instead of answering "mm-hmm".

"Talking" is `agent.state_updated: talking` from the media server, extended
by a playback estimate for audio already queued there.

## Words: OpenAI-compatible chat completions

`POST {LLM_BASE_URL}/chat/completions` with `stream: true`, `tools`, `max_tokens`
(128 to 1024, default 256), and a low temperature. Parse server-sent events:
`data: {...}` lines with `choices[0].delta.content` text and
`choices[0].delta.tool_calls` fragments keyed by `index`; `data: [DONE]` ends
the stream. Cancellation closes the HTTP response.

Message assembly:

1. Fixed platform layer: voice rules (one or two short sentences, no markdown
   or lists, easy to interrupt, never narrate cards) followed by the persona
   from `prompts/instructions.md`, control characters stripped and length
   capped.
2. For the greeting, a second system message: "the session just started,
   open with ..." plus `prompts/greeting.md`. An empty greeting file means the
   user speaks first.
3. The last 24 history messages.

Guards, all tested without a network:

- Split streamed text into sentences (`.!?…` followed by whitespace, or a
  newline) and hand each to TTS immediately.
- Drop a sentence identical to the previous one.
- If a completion ends with no text and no tool call, speak a short
  deterministic fallback rather than leaving the caller in silence.
- At most one tool round-trip per reply; answer every tool call with a `tool`
  message even when invalid, then continue the same TTS session with the
  model's follow-up sentences.
- Log the guard action and timing marks, not transcript contents, unless
  `LOG_TRANSCRIPTS=1`.

## Speech out: Gradium TTS websocket

Connect to `wss://api.gradium.ai/api/speech/tts` and send:

```json
{"type": "setup", "voice_id": "<GRADIUM_VOICE_ID>", "model_name": "default",
 "output_format": "pcm_24000", "json_config": {"rewrite_rules": "en"}}
```

- `pcm_24000` is 16-bit mono at 24 kHz: exactly LiveAvatar's input format, so
  every `audio` message is forwarded to `agent.speak` unchanged. Do not use
  `wav` (a header would be spoken as noise) or the 48 kHz `pcm` default.
- `rewrite_rules` set to the conversation language expands numbers,
  abbreviations, and currency the way a speaker would say them. Optional
  `padding_bonus` adjusts pace (negative is faster).
- Open the socket as soon as the LLM request starts so the handshake overlaps
  first-token latency; wait for `ready` before sending text.
- Send each sentence as `{"type": "text", "text": "<sentence> <flush> "}`.
  The `<flush>` tag makes the model emit audio for everything so far instead
  of waiting for more context.
- After the last sentence send `{"type": "end_of_stream"}`, drain `audio`
  messages until the server's `end_of_stream`, then send `agent.speak_end`.
- Interrupt by closing the socket; `end_of_stream` is a graceful finish that
  still delivers the remaining audio.
- One socket per reply keeps the code simple. For higher call volume reuse a
  socket with `close_ws_on_eos: false` and per-request `client_req_id` as
  described in the `gradium-text-to-speech` streaming reference.

## Latency budget

Log per reply: turn end (`flushed`) → first LLM token → first TTS audio →
first `agent.speak`. Typical targets on a good connection: first token under
one second, first audio within a few hundred milliseconds of the first
sentence, avatar audible about half a second after that. If the avatar starts
late but the transcript is on time, look at TTS; if both are late, look at the
LLM or the STT flush; if the face lags the voice, LiveAvatar reported
`video_starvation` and chunks are arriving too slowly.
