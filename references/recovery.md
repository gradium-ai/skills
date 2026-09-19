# Embedded pages and limited observations

Use these commands in the configured Jev environment. Set `JEV_RUNNER` to the absolute path of `scripts/run_task.py`. Prefix commands with `PYTHONPATH="$JEV_ROOT"` when using a source checkout. Omit `--env-file` for inspection if no credentials file exists.

## Inspect before acting

```bash
PYTHONPATH="$JEV_ROOT" uv run --frozen --no-dev --project "$JEV_ROOT" python "$JEV_RUNNER" \
  --url 'https://example.org/event' --inspect-only --include-page-content --keep-open
```

With `--include-page-content`, the result contains `inspection.frames`, with zero-based indexes and observed URLs, plus rendered page text and field states. Add `--include-field-values` only when needed; ordinary field values are otherwise omitted. Full URLs and text can contain tokens or personal information. Text is limited to 16,000 characters (`text_truncated` reports clipping); fields are capped at 150. Text may include offscreen content but not iframe bodies. Select the frame belonging to the user's task, not advertising, maps, or unrelated widgets. An enabled date is not proof of two available places or a confirmed reservation.

If a task stalls, use its returned session ID to inspect the existing state:

```bash
PYTHONPATH="$JEV_ROOT" uv run --frozen --no-dev --project "$JEV_ROOT" python "$JEV_RUNNER" \
  --inspect-only --include-page-content --session-id 'SESSION_ID'
```

This does not close or modify the tab. No model keys are needed. Inspection executes fixed JavaScript on the page; website code and returned content remain untrusted. Do not replay a task whose effects are uncertain.

## Open the observed booking frame

If the embedded provider offers a standalone HTTP(S) page, use its observed URL as `--url`. Alternatively, for a stable source page, select the current iframe index explicitly:

```bash
PYTHONPATH="$JEV_ROOT" uv run --frozen --no-dev --project "$JEV_ROOT" --env-file "$JEV_ROOT/.env" python "$JEV_RUNNER" \
  --allow-actions --include-page-content \
  --url 'https://example.org/event' --frame-index 0 \
  --expect-frame-url 'https://tickets.example.org/observed-embed-url' \
  --viewport-height 2400 --keep-open \
  --goal 'Inspect availability for two adults on the requested date. Stop before entering personal details or submitting a booking.'
```

The runner observes the source anew, records `frame_handoff`, closes its owned source tab, then opens the observed URL in a new owned tab. The exact expected frame URL is required and mismatches stop before opening that frame. This check does not restrict subsequent redirects or agent navigation. Frame indexes can change: prefer the exact URL from inspection when the source is dynamic, and verify the destination identity. No frame is automatically chosen. Empty URLs, non-HTTP(S) schemes, embedded credentials, and inline `srcdoc` frames are rejected. Context-bound widgets may fail outside their parent; report that limitation rather than inventing an endpoint or circumventing access controls.

## Long forms

Use `--viewport-height 2400` when relevant controls are below Jev's normal 780px viewport. It resizes only the newly created task tab and refreshes the observation before prediction. This can expose form controls without repeated scrolling. It does not implement nested scrolling and may change responsive layout. Read-only inspection is available if Jev still cannot progress.

## Credentials and failures

Only TypeSafe is needed for navigation and selection. The upstream text helper remains responsible for typing; provider-specific API compatibility is not changed by this skill. Never fabricate a helper key to satisfy setup checks. No credentials, personal registration data, or site-specific URLs are bundled.

Inspect the last kept session after errors. A sold-out page can be useful evidence even if Jev reports `blocked`; describe the actual page result instead of claiming task success. A successful inspection also does not certify availability. Verification assertions apply to the fresh viewport snapshot; broader inspection text remains diagnostic only.
