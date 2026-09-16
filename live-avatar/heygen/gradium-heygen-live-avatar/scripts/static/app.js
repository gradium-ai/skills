/*
 * Browser leg of the Gradium × LiveAvatar starter.
 *
 * One websocket to the orchestrator carries microphone audio up and transcripts,
 * cards, avatar state and errors down. The avatar's own audio and video never travel
 * on it: they arrive over LiveKit, already lip-synced, from the room LiveAvatar created.
 *
 * Order on the way up: open the socket → `session` (join the LiveKit room) → `ready`
 * (start the microphone). Audio sent before the server's speech pipeline exists would
 * be dropped, so the mic waits for `ready`.
 */
(() => {
  const { Room, RoomEvent, Track } = window.LivekitClient;

  const els = {
    video: document.getElementById("video"),
    audio: document.getElementById("audio"),
    stage: document.getElementById("stage"),
    start: document.getElementById("start"),
    stop: document.getElementById("stop"),
    mic: document.getElementById("mic"),
    micLabel: document.getElementById("mic-label"),
    status: document.getElementById("status"),
    loader: document.getElementById("loader-label"),
    transcript: document.getElementById("transcript"),
    card: document.getElementById("card"),
    cardTitle: document.getElementById("card-title"),
    cardSubtitle: document.getElementById("card-subtitle"),
    cardBody: document.getElementById("card-body"),
  };

  const TARGET_RATE = 24000; // Gradium STT input_format pcm_24000
  const FRAME_SAMPLES = 1920; // 80 ms: Gradium's native frame, one websocket message each
  const CARD_MS = 9000;

  let ws = null;
  let room = null;
  let mic = null;
  let active = false;
  let muted = false;
  let cardTimer = 0;
  let lastAssistantLine = null;
  const turnLines = new Map();

  // ── status and stage ──────────────────────────────────────────────────────

  function setStatus(text, kind = "idle") {
    els.status.textContent = text; // textContent: never markup
    els.status.dataset.kind = kind;
    if (els.stage.dataset.state === "connecting") els.loader.textContent = text;
  }

  function setStage(state) {
    els.stage.dataset.state = state;
  }

  els.video.addEventListener("playing", () => {
    if (els.stage.dataset.state === "connecting") setStage("live");
  });

  // ── transcript ────────────────────────────────────────────────────────────

  function upsertTurn(turn) {
    let entry = turnLines.get(turn.id);
    if (!entry) {
      const line = document.createElement("div");
      line.className = `turn ${turn.role}`;
      const who = document.createElement("span");
      who.className = "who";
      who.textContent = turn.role === "user" ? "You" : "Avatar";
      const text = document.createElement("span");
      text.className = "text";
      line.append(who, text);
      els.transcript.appendChild(line);
      entry = { line, text };
      turnLines.set(turn.id, entry);
    }
    entry.text.textContent = turn.text;
    if (turn.role === "assistant") lastAssistantLine = entry.line;
    els.transcript.scrollTop = els.transcript.scrollHeight;
  }

  function clearTranscript() {
    els.transcript.textContent = "";
    turnLines.clear();
    lastAssistantLine = null;
  }

  // ── cards (the visual channel) ────────────────────────────────────────────
  // Props come from a model, clamped by the server; they are rendered as text only.

  function showCard(props) {
    els.cardTitle.textContent = props.title || "";
    els.cardSubtitle.textContent = props.subtitle || "";
    els.cardBody.textContent = props.body || "";
    els.cardSubtitle.hidden = !props.subtitle;
    els.cardBody.hidden = !props.body;
    els.card.hidden = false;
    els.card.classList.remove("visible");
    void els.card.offsetWidth; // restart the entrance animation for a repeated card
    els.card.classList.add("visible");
    clearTimeout(cardTimer);
    cardTimer = setTimeout(hideCard, CARD_MS);
  }

  function hideCard() {
    clearTimeout(cardTimer);
    els.card.classList.remove("visible");
    els.card.hidden = true;
  }

  function renderUi(msg) {
    if (msg.widget === "card" && msg.props) showCard(msg.props);
    else if (msg.widget === "hide") hideCard();
  }

  // ── LiveKit: the avatar's face and voice ──────────────────────────────────

  async function joinRoom(url, token) {
    const r = new Room({ adaptiveStream: true, dynacast: true });
    const attach = (track) => {
      if (track.kind === Track.Kind.Video) track.attach(els.video);
      if (track.kind === Track.Kind.Audio) track.attach(els.audio);
    };
    r.on(RoomEvent.TrackSubscribed, attach);
    r.on(RoomEvent.TrackUnsubscribed, (track) => track.detach());
    await r.connect(url, token);
    // Tracks published before the join completes fire no TrackSubscribed.
    r.remoteParticipants.forEach((p) => {
      p.trackPublications.forEach((pub) => {
        if (pub.track) attach(pub.track);
      });
    });
    try {
      await r.startAudio(); // the session starts from a click, so autoplay normally passes
    } catch {
      /* audio unblocks on the next interaction */
    }
    return r;
  }

  // ── microphone → 24 kHz PCM16 base64, 80 ms frames ───────────────────────
  // No voice-activity detection here: Gradium's semantic VAD decides turns server-side,
  // and it needs the silence too. Muting disables the track, so silence keeps flowing.

  const WORKLET = `
    class Downsampler extends AudioWorkletProcessor {
      constructor(options) {
        super();
        const o = options.processorOptions || {};
        this.ratio = sampleRate / (o.targetRate || 24000);
        this.frame = o.frameSamples || 1920;
        this.pos = 0;
        this.out = new Int16Array(this.frame);
        this.filled = 0;
      }
      process(inputs) {
        const ch = inputs[0] && inputs[0][0];
        if (!ch) return true;
        for (; this.pos < ch.length; this.pos += this.ratio) {
          const start = Math.floor(this.pos);
          const end = Math.min(ch.length, Math.ceil(this.pos + this.ratio));
          let sum = 0, n = 0;
          for (let j = start; j < end; j++) { sum += ch[j]; n++; }
          const s = Math.max(-1, Math.min(1, n ? sum / n : 0));
          this.out[this.filled++] = s < 0 ? s * 0x8000 : s * 0x7fff;
          if (this.filled === this.frame) {
            this.port.postMessage(this.out.buffer, [this.out.buffer]);
            this.out = new Int16Array(this.frame);
            this.filled = 0;
          }
        }
        this.pos -= ch.length;
        return true;
      }
    }
    registerProcessor("downsampler", Downsampler);
  `;

  function base64FromBytes(bytes) {
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    }
    return btoa(binary);
  }

  async function startMic(onFrame) {
    // Echo cancellation is load-bearing: the avatar's voice plays out of the same machine
    // the microphone listens on, and without it the agent hears and answers itself.
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    const ctx = new AudioContext();
    if (ctx.state === "suspended") await ctx.resume();
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    try {
      await ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, "downsampler", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      processorOptions: { targetRate: TARGET_RATE, frameSamples: FRAME_SAMPLES },
    });
    node.port.onmessage = (e) => onFrame(base64FromBytes(new Uint8Array(e.data)));
    const sink = ctx.createGain();
    sink.gain.value = 0; // keeps the graph running without playing the mic back
    source.connect(node);
    node.connect(sink);
    sink.connect(ctx.destination);
    return {
      setMuted(m) {
        stream.getAudioTracks().forEach((t) => (t.enabled = !m));
      },
      stop() {
        node.port.onmessage = null;
        node.disconnect();
        sink.disconnect();
        source.disconnect();
        stream.getTracks().forEach((t) => t.stop());
        void ctx.close();
      },
    };
  }

  function setMuted(m) {
    muted = m;
    mic?.setMuted(m);
    if (m) els.mic.dataset.muted = "";
    else delete els.mic.dataset.muted;
    els.mic.setAttribute("aria-pressed", String(m));
    els.mic.setAttribute("aria-label", m ? "Unmute microphone" : "Mute microphone");
    els.micLabel.textContent = m ? "Muted" : "Mic on";
  }

  // ── session ───────────────────────────────────────────────────────────────

  function send(payload) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  }

  function start() {
    if (active) return;
    active = true;
    els.start.disabled = true;
    setStage("connecting");
    setStatus("starting session…", "busy");

    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onmessage = async (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      switch (msg.type) {
        case "session":
          setStatus("connecting to the avatar…", "busy");
          try {
            room = await joinRoom(msg.livekit_url, msg.livekit_client_token);
            send({ type: "joined" });
          } catch (err) {
            stop(err instanceof Error ? err.message : "could not reach the avatar", "error");
          }
          break;
        case "ready":
          els.stop.disabled = false;
          setStatus("listening — just start talking", "live");
          try {
            mic = await startMic((audio) => send({ type: "mic_audio", audio }));
            if (!active) {
              mic.stop();
              mic = null;
              return;
            }
            els.mic.disabled = false;
          } catch (err) {
            setStatus(err instanceof Error ? `microphone unavailable: ${err.message}` : "microphone unavailable", "error");
          }
          break;
        case "turn":
          upsertTurn(msg);
          break;
        case "ui":
          renderUi(msg);
          break;
        case "interrupted":
          lastAssistantLine?.classList.add("interrupted");
          break;
        case "state":
          els.stage.dataset.avatar = msg.avatar || "idle";
          break;
        case "error":
          setStatus(msg.message || "something went wrong", "error");
          break;
        default:
          break;
      }
    };
    ws.onerror = () => setStatus("lost connection to the server", "error");
    ws.onclose = () => {
      if (active) stop("the session ended");
    };
  }

  async function stop(reason = "idle", kind = "idle") {
    if (!active) return;
    active = false;
    els.stop.disabled = true;
    els.mic.disabled = true;
    setMuted(false);
    mic?.stop();
    mic = null;
    send({ type: "stop" });
    ws?.close();
    ws = null;
    if (room) {
      room.removeAllListeners();
      await room.disconnect();
      room = null;
    }
    els.video.srcObject = null;
    els.audio.srcObject = null;
    hideCard();
    clearTranscript();
    els.stage.dataset.avatar = "idle";
    setStage("idle");
    setStatus(reason, kind);
    els.start.disabled = false;
  }

  els.start.addEventListener("click", start);
  els.stop.addEventListener("click", () => stop());
  els.mic.addEventListener("click", () => {
    if (mic) setMuted(!muted);
  });
  // Closing the tab closes the socket, and the server ends the billable session on close.
  window.addEventListener("pagehide", () => ws?.close());

  // Dev hook: preview a card without burning session minutes.
  //   window.__ui({ widget: "card", props: { title: "Bonjour", subtitle: "bon-ZHOOR", body: "hello" } })
  window.__ui = renderUi;
})();
