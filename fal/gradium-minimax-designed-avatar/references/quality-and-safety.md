# Quality, safety, and product checks

Every paid render must pass mechanical, auditory, and visual review before it is
presented as final. Lip-sync generation is stochastic; a successful API
response does not prove a usable result.

## Mechanical and audio checks

- Use `ffprobe` to confirm the MP4 is decodable and its duration approximately
  matches the prepared WAV (the padded or clipped one the script wrote next to
  the output as `<out>_speech.wav`). The script enforces this on download.
- Confirm the MP4 contains an audio stream and is not silent.
- Extract the audio track and transcribe it with Gradium STT when exact wording
  matters. Compare normalized transcript text with the approved script.
- If the source speech was padded to 5 seconds, expect a silent tail; trim it
  with ffmpeg only if the still face at the end distracts.
- Preserve the WAV and request metadata until the take is accepted, but never
  persist credentials or raw provider headers.

## Visual checks

Build and inspect two contact sheets. `grade_render.py` in the
`gradium-pruna-video` skill produces both from any MP4:

1. Six to eight frames evenly spaced over the full clip, checking face and hair
   stability, eye behavior, gaze drift, background changes, framing, accidental
   text, and source-image morphing at the start.
2. Frames at speech-word midpoints, using Gradium timestamps when available or
   evenly spaced speaking moments otherwise. The mouth should visibly articulate
   most sampled words.

Inspect the first second separately: the model starts close to the source
image and blends into generated motion.

## Retry policy

Choose the least expensive fix that addresses the failure:

1. source-image cleanup, recrop within the 0.4 to 2.5 aspect range, or a
   cleaner portrait;
2. a shorter script or a re-synthesized WAV with adjusted pace or pauses;
3. `--transcribe` when lip articulation is weak;
4. local crop, mask, or fade when the flaw cannot damage the subject;
5. one user-authorized rerender with a different seed.

Do not claim deterministic lip-sync or identity stability. Grade a rerender from
scratch rather than assuming it fixed only the targeted flaw.

## Media and URL safety

For uploads, cap bytes and decoded pixels, allow only required raster/audio
formats, strip metadata, and re-encode to known output formats. Generate storage
names server-side and keep assets outside executable and public directories.

If the product accepts remote URLs, allow HTTPS only; reject embedded
credentials, unusual ports, loopback, private, link-local, multicast, and cloud
metadata destinations for both IPv4 and IPv6. Revalidate every redirect and
enforce redirect, timeout, and byte limits.

Hosted generation endpoints must authenticate callers, enforce exact schemas and
request-size limits, rate-limit by account and source, cap concurrent jobs and
daily spend, and make repeated starts idempotent. Keep `FAL_KEY` on the
server; fal's own guidance is to route browser and mobile traffic through a
server-side proxy. Never let the browser choose server filesystem paths,
provider headers, request ids belonging to another account, or arbitrary
download destinations.

## Data flow and retention

Document that the portrait and synthesized audio go to fal.ai, which runs the
MiniMax H3 Max model, while the voice description and script go to Gradium for
Voice Design and TTS. With `enable_transcription`, fal also transcribes the
speech. State actual provider region, observability, retention, and deletion
controls; fal keeps results according to the account's media expiration
settings. Never promise zero retention unless verified for the selected
accounts.

For an identifiable real person, record the user's authorization before paid
generation and recommend a clear synthetic-media disclosure anywhere the output
could plausibly be mistaken for authentic footage. Do not claim that a designed
voice is the subject's real voice. Keep the safety checker enabled.

Keep `.env`, auditions, local portraits, generated WAV files, and private video
outputs out of version control by default. Before publication, inspect staged
files and history for credentials and personal media without printing matched
secret values.
