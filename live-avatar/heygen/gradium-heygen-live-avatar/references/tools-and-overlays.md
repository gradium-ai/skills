# Tools and on-screen visuals

The point of the HeyGen demo is that the avatar's tool calls land on screen.
This pipeline keeps that and makes it simpler: the LLM holds the tools
directly, so there is no live-model-delegates-to-backend hop to coax.

## How a tool call becomes a card

1. The LLM streams a reply. Text deltas go to TTS sentence by sentence; tool
   call fragments are reassembled by `index` until the stream ends.
2. The orchestrator validates each call (`dispatch_tool`): JSON arguments,
   known name, string fields stripped of control characters and clamped
   (`title` 60, `subtitle` 80, `body` 160 characters). An unknown tool or a
   missing title yields an error result, never a rendered widget.
3. A valid call is emitted to the browser as `{"type": "ui", "widget": "card", "props": {...}}`
   and answered to the model with `{"shown": true}` in a `tool` message.
4. The model continues its reply after the tool results (one round only), and
   those sentences go into the same TTS session, so speech and screen stay in
   step without any timer guessing at speech cadence.
5. The browser renders the card as a lower-third with `textContent`.

Persona rules the orchestrator adds for you: say the answer out loud in the
same reply as the tool call, never narrate that a card appeared, never claim
one is showing.

## Adding a tool: three edits

1. **Schema** in `TOOLS` (`orchestrator.py`): an OpenAI function definition.
   Keep the description about *when* to use it and keep parameters to content
   the model may legitimately choose (a heading, a term), never layout.
2. **Dispatch** in `dispatch_tool`: validate and clamp every field, map to a
   `widget` name and `props`, return the tool result the model should see.
3. **Render** in `static/app.js` `renderUi`: one branch per widget, text only,
   with staging decided there (full-frame, lower-third, picture-in-picture).

The server owns any data that must be true. If a widget shows prices, account
facts, or a recap of what was taught, keep that data on the session and let
the tool schema carry only a selector or heading; the model cannot misremember
what it never supplies. HeyGen's `show_learned_words` recap is the template:
every shown card is recorded server-side and the recap renders from that
store.

## Making visuals actually fire

A registered tool that never fires in a live session is the expected failure,
not a wiring bug. Patterns that work, in order of reliability:

1. **Server-side push keyed on the transcript.** The orchestrator sees every
   assistant sentence before it is spoken (`_say`). Match trigger content
   there and emit the `ui` message yourself, deduplicated per session. This
   never depends on the model's cooperation and lands the card alongside the
   word.
2. **Explicit-request triggers in the persona.** "Whenever the person asks
   for a word, a price, or a definition, call show_card" fires reliably on a
   direct question. Prose asking the model to volunteer visuals fires rarely.
3. **Prod plus fallback.** Ask via a system message, arm a timeout, and push
   the widget directly if the model did not.

Preview any widget without spending session minutes from the browser
console: `window.__ui({ widget: "card", props: { title: "Hello" } })`.

## Boundaries

- Tool arguments and results are untrusted data. A persona is never authority
  to read files, call external services, or reveal configuration; add
  per-tool authorization and argument validation that does not depend on the
  character text before giving a tool side effects.
- Cards are ephemeral broadcast graphics. For persistent or clickable UI, add
  a plain DOM element in the page with its own lifecycle rather than stretching
  the card.
- Keep the schema small. Every extra parameter is a new thing the model can
  get wrong on screen.
