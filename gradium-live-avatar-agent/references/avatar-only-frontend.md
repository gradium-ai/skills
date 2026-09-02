# Avatar-only frontend

The web client exists to show and control the live conversation. It is not a
configuration product.

## Visible surface

Include only:

- the remote LemonSlice video filling the primary viewport;
- remote avatar audio;
- a start/end call control;
- a microphone mute/unmute control;
- a restrained connecting, ready, listening, or speaking state.

Before the video arrives, the same reference portrait may fill the stage as a
placeholder. A compact error message is acceptable. Do not add transcript,
character fields, voice controls, model selectors, debug panels, provider
branding, or setup steps unless the user explicitly requests them.

## LiveKit browser behavior

The server returns a participant token and `LIVEKIT_URL`. The browser connects
with `livekit-client`, subscribes to remote tracks, and attaches them:

```javascript
room.on(RoomEvent.TrackSubscribed, (track) => {
  if (track.kind === Track.Kind.Video) track.attach(videoElement);
  if (track.kind === Track.Kind.Audio) audioRoot.appendChild(track.attach());
});
```

Enable the microphone immediately after the LiveKit room connects. Do not put
microphone startup inside the avatar `TrackSubscribed` callback: video arrival
and microphone publication are independent lifecycles, and coupling them can
produce a visually connected call with no input audio. Request echo
cancellation, noise suppression, and automatic gain control.

Keep a lightweight microphone health check while the call is active. Observe
whether the local publication exists and its underlying media track is enabled
and `live`; republish the microphone once if the track unexpectedly ends. Send
connection and microphone health events to a server-side diagnostic endpoint,
but do not include transcripts, device labels, tokens, or other sensitive data.
This telemetry is background-only and must not add a debug panel to the avatar
surface.

On hangup, stop the health check, disconnect the room, detach tracks, remove
generated audio elements, and restore the still portrait.

The token endpoint must remain server-side and grant only the room permissions
the participant needs. Never place provider secrets in HTML, JavaScript bundles,
query strings, or browser storage.

## Visual direction

Let the avatar dominate. Prefer a full-bleed stage with small floating call
controls. Preserve consistent framing when switching from the reference portrait
to the live track: default the remote video to `object-fit: contain` and center it
so the face and head are never cropped. Letterboxing is preferable to changing
the character's apparent framing. Use `cover` only when the user explicitly
wants an edge-to-edge crop or the generated video has a known matching aspect
ratio. Status copy should remain secondary and disappear when the avatar is
ready. The user should perceive a conversation with a character, not an API
dashboard.
