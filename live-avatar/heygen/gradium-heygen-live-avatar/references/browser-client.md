# Browser client

The page exists to show and control one conversation. It is not a
configuration product: no character editor, voice picker, or model selector
unless the user asks for them.

## Visible surface

- the avatar's LiveKit video filling a 16:9 stage, `object-fit: contain` so the
  head is never cropped;
- the avatar's audio element;
- start and end call, a mute toggle, a small status line;
- a transcript panel (this demo is about seeing what was said and shown);
- the card overlay, a lower-third over the untouched video.

The stage carries `data-state` (`idle`, `connecting`, `live`) and
`data-avatar` (`idle`, `listening`, `talking`, mirrored from the server's
`state` messages) so CSS handles the hero, loader, and speaking glow.

## Wire protocol with the orchestrator

One websocket at `/ws`. Everything is JSON text.

| Direction | Message | Meaning |
| --- | --- | --- |
| ← | `{"type": "session", "session_id", "livekit_url", "livekit_client_token"}` | Join the LiveKit room now. |
| → | `{"type": "joined"}` | Room attached; the server may speak the greeting. |
| ← | `{"type": "ready"}` | Speech pipeline is up; start the microphone. |
| → | `{"type": "mic_audio", "audio": "<base64 PCM16 24 kHz>"}` | 80 ms frames, continuously, silence included. |
| ← | `{"type": "turn", "role": "user"\|"assistant", "id", "text", "done"}` | Streaming transcript; same `id` rewrites the line. |
| ← | `{"type": "ui", "widget": "card", "props": {"title", "subtitle?", "body?"}}` | Show a card. `{"widget": "hide"}` removes it. |
| ← | `{"type": "interrupted"}` | The rest of the last assistant line was never heard. |
| ← | `{"type": "state", "avatar": "idle"\|"listening"\|"talking"}` | Avatar pose from the media server. |
| ← | `{"type": "error", "message"}` | Restrained, text-only error. |
| → | `{"type": "stop"}` | End the call. Closing the socket has the same effect. |

Avatar audio and video never travel on this socket. They arrive over LiveKit,
already lip-synced. Order on the way up matters: join the room on `session`,
start the microphone only on `ready`, because audio sent before the speech
pipeline exists is dropped.

## LiveKit join

```javascript
const room = new Room({ adaptiveStream: true, dynacast: true });
room.on(RoomEvent.TrackSubscribed, (track) => {
  if (track.kind === Track.Kind.Video) track.attach(videoEl);
  if (track.kind === Track.Kind.Audio) track.attach(audioEl);
});
await room.connect(livekitUrl, clientToken);
room.remoteParticipants.forEach((p) => p.trackPublications.forEach((pub) => pub.track && attach(pub.track)));
await room.startAudio().catch(() => {});
```

Tracks published before the join completes fire no `TrackSubscribed`, hence
the second pass. The session starts from a click, so autoplay normally passes.

The reference page loads `livekit-client` as a pinned UMD bundle from
jsdelivr and the server sends a Content Security Policy that allows only that
host plus same-origin assets. For a hosted deployment, bundle the library
locally (Vite or esbuild) and drop the CDN from the policy.

## Microphone capture

- `getUserMedia` with `echoCancellation`, `noiseSuppression`,
  `autoGainControl`, one channel. Echo cancellation is load-bearing: the
  avatar's voice plays out of the same machine and without it the agent hears
  and answers itself.
- An AudioWorklet averages 48 kHz samples down to 24 kHz PCM16 and posts one
  buffer per 1920 samples (80 ms). Resume the `AudioContext` explicitly; it
  starts suspended when created after `await getUserMedia`.
- No voice-activity detection in the browser. Gradium's semantic VAD needs the
  silence too, and a second gate double-fires turns.
- Mute disables the track (`track.enabled = false`) so silence keeps streaming
  and the server's idle watchdog still sees a live browser. Never restart
  capture after an intentional mute, a permission denial, hangup, device
  removal, or page teardown.
- Closing the tab closes the socket; the server stops the billable session on
  close.

## Cards

Props come from a model, clamped by the server, and are rendered with
`textContent` only. Staging is decided by the client per widget, never by a
model argument: the card is a lower-third and the avatar stays full-frame. A
card auto-hides after nine seconds or on `hide`. Preview without a session:

```javascript
window.__ui({ widget: "card", props: { title: "Bonjour", subtitle: "bon-ZHOOR", body: "hello" } })
```

Insert every status, error, transcript, and card string as text. The page has
no inline scripts or styles so the policy can stay strict.
