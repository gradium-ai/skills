# Pruna avatar rendering: verified quirks and the iteration playbook

Everything below was learned the expensive way across ~20 live
`p-video-avatar` renders (2026-08/09). Read this before promising a
client-ready video in one shot: avatar generation is a diffusion
lottery, and the winning strategy is *verify frames, then iterate the
cheapest lever* — usually ffmpeg, not another render.

## The prompt levers (and their limits)

- **Lead the `video_prompt` with mouth articulation.** The single most
  reliable instruction is "lips and jaw move vigorously and precisely
  with every syllable, clearly opening and closing in sync with the
  audio". Without it, quiet voices produce near-closed mouths.
- **Keep `negative_prompt` SHORT.** An over-stuffed negative list
  (especially "eye movement", "head movement") suppresses *all* facial
  motion — verified: a long negative froze lip-sync completely while
  the audio played. 5–8 terms max.
- **`negative_prompt_strength` is documented but rejected** (400:
  "additional properties forbidden"). Don't send it.
- **Explain physics instead of prohibiting.** "The eyes are stone, so
  they cannot blink or move" outperforms "no blinking, no eye
  movement" — diffusion models respond to reasons.
- **Seeds are pure variance.** The same inputs produce visibly
  different eye behavior and artifacts per seed. Re-rolling and
  cherry-picking is a legitimate, expected part of the workflow
  (~$0.025/s per attempt at 720p).

## Known failure modes (all observed repeatedly)

1. **Text hallucination on alphanumeric-heavy audio.** Speech full of
   IDs, serial numbers, or phone numbers (worst in French) makes the
   model burn gibberish pseudo-captions into the frame. Negative
   prompts reduce but do NOT reliably prevent it (4 of 6 attempts on
   one clip had text). The text usually lives in the top ~15% and
   bottom ~13% bands but *drifts vertically between frames* — measure
   before cropping, and check several timestamps. If text overlaps the
   subject at any time, re-roll; masking can't win.
2. **The first frame ≈ the source image.** Any flaw in the source
   (edited eyes, artifacts) is fully visible at t=0 before the model's
   own treatment blends in over ~0.5–1s. Fixes: repair the source, or
   hide the morph with a short fade-in
   (`ffmpeg -vf "fade=t=in:st=0:d=0.7"`).
3. **Eyes get re-animated no matter what.** Statues/characters with
   carved or painted eyes acquire human-like pupils, blinks, or gaze
   drift in most takes; deeply carved eye sockets are worst. Prompting
   reaches ~80% stillness, never 100%. If the eyes must not move:
   pre-edit the source (see p-image-edit below), expect residual
   motion, and grade densely.
4. **Closed eyes are achievable and stable** when the *source image*
   has closed lids — harvest a closed-lids frame from a previous
   render and use it as the new source. Prompt-only "closed eyes" on
   an open-eyed source blinks open intermittently.
5. **Head/framing size varies with the source crop.** A tight
   head-and-shoulders source renders the face much larger than a
   floating-head-with-margins source at the same output size. When
   mixing sources across a series, normalize by *face height*
   (brow→chin), not by frame or content-bbox height — big hair breaks
   bbox math. Expect one calibration iteration.

## Source-image prep with `p-image-edit`

Same `/v1/predictions` endpoint, header `Model: p-image-edit`, input
`{"images": ["<file-url>"], "prompt": "...", "aspect_ratio": "3:4"}`.
Useful for: blanking or closing a character's eyes, cleaning
artifacts, reframing. Two cautions (both observed):
- The edit can introduce its own artifacts (e.g. blank eyes rendered
  as glowing white, or amber-tinted eyeballs) — inspect the edited
  image at full size before spending on video renders.
- An edited source does NOT prevent the video model's text
  hallucination or eye re-animation; it only changes the starting
  point.

## The grading workflow (do this before showing anyone)

For every render, build two frame montages with ffmpeg and *look at
them*:
1. **Eye sweep** — 6–8 frames evenly spaced across the full duration.
   Sparse 3-frame checks miss blinks (verified: a render passed a
   3-frame check, then showed open human eyes at a timestamp between
   samples).
2. **Mouth-at-speech-midpoints** — frames at the midpoints of words
   taken from Whisper/STT timestamps. The mouth must be visibly shaped
   or open at most of them; a closed mouth at speech midpoints means
   the render's lip-sync failed even if the file plays audio fine.

Plus the mechanical checks: `ffprobe` duration ≈ audio duration, and
an STT round-trip of the extracted audio track against the script.

## Cheap fixes beat re-renders

In order of preference when a take is imperfect:
1. `crop` — text bands, dead margins (only when the artifact zone
   never overlaps the subject in ANY frame).
2. `drawbox`/`fade` — static junk regions; source-image morph at t=0.
3. Composite-level tricks — overlay position/scale changes.
4. Re-roll with a new seed — last resort, and grade the new take just
   as strictly.
