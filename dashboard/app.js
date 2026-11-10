"use strict";
/* =====================================================================
   MAYERA - browser voice engine (voice-only, no chat, no transcript)

   Mic  -> getUserMedia -> resample to 16 kHz PCM16 -> WebSocket
   Spkr <- WebAudio scheduling <- PCM 24 kHz <- WebSocket
   Interruption: server sends {"type":"interrupted"} -> we instantly
   flush every scheduled AI audio buffer, so MAYERA stops talking the
   moment the user starts speaking.
   ===================================================================== */

const MIC_RATE = 16000;    // Gemini Live input format
const AI_RATE = 24000;     // Gemini Live output format

const $ = (id) => document.getElementById(id);
const statusText = $("statusText");
const connDot = $("connDot");
const connText = $("connText");
const btnStart = $("btnStart");
const btnMute = $("btnMute");
const btnEnd = $("btnEnd");

let ws = null;
let wsReconnectTimer = null;

let callActive = false;
let micMuted = false;

// Push-to-Talk (v3.15): when ON, the mic only sends while
// Ctrl+Space is held - held state comes from this page's own keys
// (window scope) or from the server (Windows-global via the
// `keyboard` package, forwarded as {"type":"ptt"} messages).
let pttEnabled = false;
let pttHeld = false;
window.addEventListener("keydown", (e) => {
  if (pttEnabled && e.ctrlKey && e.code === "Space") {
    e.preventDefault();
    pttHeld = true;
  }
});
window.addEventListener("keyup", (e) => {
  if (e.code === "Space") pttHeld = false;
});

// --- microphone graph ---
let micCtx = null, micStream = null, micProcessor = null, micSource = null, micSink = null;

// --- playback graph ---
let playCtx = null;
let playHead = 0;                 // next scheduled buffer start time
let duckUntilWall = 0;            // wall-clock (s) until which JARVIS's own voice is audible - mic echo duck window
const scheduled = new Set();      // live BufferSources (for interruption flush)

// --- adaptive jitter buffer + playback stats (v3.14) ---
// ROOT CAUSE of "beech me ruk-ruk kar bolta hai": chunks used to be
// scheduled with only a fixed 30 ms lookahead, so every network or
// main-thread jitter became an audible gap mid-sentence. Now the
// FIRST chunk of a turn waits adaptBufferMs (a small jitter cushion)
// and later chunks chain exactly on playHead. The cushion adapts:
// a starvation (chunk arriving after its slot passed) grows it,
// clean turns shrink it towards the floor.
let adaptBufferMs = 70;           // current jitter cushion (v3.19: was 120 - first sound sooner)
const BUFFER_MIN_MS = 40, BUFFER_MAX_MS = 300;
let turnHadStarvation = false;
const pbStats = {
  received: 0,        // AI audio chunks arrived from the server
  played: 0,          // chunks that actually finished playing
  starved: 0,         // chunks that arrived after their slot (gap!)
  droppedQueue: 0,    // chunks dropped by the overflow guard
  interruptedFlushes: 0,
};

// --- animation levels (0..1) ---
let micLevel = 0, speakLevel = 0;

/* ------------------------------------------------------------------ */
/* UI state                                                            */
/* ------------------------------------------------------------------ */
let _lastStateKey = "";
function setState(state, message) {
  // v3.0: identical repeat calls (one per audio chunk) skip DOM work.
  const key = state + "|" + (message || "");
  if (key === _lastStateKey) return;
  _lastStateKey = key;
  if (message) statusText.textContent = message;
  const visual = { speaking: "speaking", listening: "listening", connected: "listening",
                   muted: "listening", thinking: "thinking", error: "error" }[state] || "idle";
  document.body.dataset.state = visual;
  if (state === "error") { connDot.className = "conn-dot err"; }
  else if (state === "reconnecting" || state === "connecting") { connDot.className = "conn-dot busy"; }
  else if (callActive || state === "connected") { connDot.className = "conn-dot on"; }
}

function setButtons() {
  btnStart.disabled = callActive;
  btnMute.disabled = !callActive;
  btnEnd.disabled = !callActive;
  btnMute.classList.toggle("active", micMuted);
  const micIc = btnMute.querySelector(".ic");
  const micCap = btnMute.querySelector(".cap");
  if (micIc) micIc.textContent = micMuted ? "🔇" : "🎙️";
  if (micCap) micCap.textContent = micMuted ? "OFF" : "MUTE";
}

/* ------------------------------------------------------------------ */
/* WebSocket (auto-reconnect, single connection)                       */
/* ------------------------------------------------------------------ */
function connectWS() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    connDot.className = "conn-dot on";
    connText.textContent = "Online";
    setState("idle", "JARVIS taiyaar hai");
  };
  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "status") setState(msg.state, msg.message);
      else if (msg.type === "interrupted") flushPlayback();
      else if (msg.type === "ptt") pttHeld = !!msg.active;
      else if (msg.type === "confirm") showConfirm(msg.id, msg.text);
    } else {
      playAiAudio(ev.data);
    }
  };
  ws.onclose = () => {
    connDot.className = "conn-dot err";
    connText.textContent = "Offline";
    ws = null;
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWS, 2000); // auto reconnect
  };
  ws.onerror = () => { try { ws.close(); } catch {} };
}
setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" })); }, 20000);

// Playback diagnostics for the /health dashboard (v3.14): the server
// cannot see what the speaker actually did, so the browser reports
// its counters every 5 s during a call.
setInterval(() => {
  if (!callActive) return;
  wsSend({ type: "stats", playback: {
    received: pbStats.received, played: pbStats.played,
    starved: pbStats.starved, droppedQueue: pbStats.droppedQueue,
    interruptedFlushes: pbStats.interruptedFlushes,
    bufferMs: adaptBufferMs,
    queuedAheadMs: playCtx ? Math.max(0, Math.round((playHead - playCtx.currentTime) * 1000)) : 0,
  }});
}, 5000);

function wsSend(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

/* ------------------------------------------------------------------ */
/* Microphone capture -> PCM16 16 kHz -> WebSocket                     */
/* ------------------------------------------------------------------ */
function floatToPcm16(floats) {
  const out = new Int16Array(floats.length);
  for (let i = 0; i < floats.length; i++) {
    const s = Math.max(-1, Math.min(1, floats[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function resampleFloats(input, fromRate, toRate) {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const outLen = Math.floor(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio, lo = Math.floor(pos), hi = Math.min(lo + 1, input.length - 1);
    out[i] = input[lo] * (1 - (pos - lo)) + input[hi] * (pos - lo);
  }
  return out;
}

function rmsOf(floats) {
  let sum = 0;
  for (let i = 0; i < floats.length; i++) sum += floats[i] * floats[i];
  return floats.length ? Math.sqrt(sum / floats.length) : 0;
}

async function startMicrophone() {
  // Audio device picker (v3.15): the mic chosen in Settings, by
  // deviceId, when one is saved - otherwise the OS default.
  const savedMic = localStorage.getItem("jarvis_mic_device") || "";
  const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  if (savedMic) audio.deviceId = { exact: savedMic };
  micStream = await navigator.mediaDevices.getUserMedia({ audio });
  micCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: MIC_RATE });
  micSource = micCtx.createMediaStreamSource(micStream);
  // 1024 samples @16 kHz = 64 ms per chunk (v3.14; was 2048 = 128 ms,
  // originally 4096 = 256 ms): smaller chunks reach Gemini sooner at
  // every turn end, which trims the felt reply delay further.
  micProcessor = micCtx.createScriptProcessor(1024, 1, 1);
  micSink = micCtx.createGain(); micSink.gain.value = 0; // silent sink, no echo

  micProcessor.onaudioprocess = (e) => {
    const raw = e.inputBuffer.getChannelData(0);
    const r = rmsOf(raw);
    micLevel = Math.max(micLevel, Math.min(1, r * 3));
    if (!callActive || micMuted) return;
    if (pttEnabled && !pttHeld) return; // Push-to-Talk: key dabao tabhi mic
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    // Echo guard (v3.10): while JARVIS's own voice is still playing
    // from the speakers (+300 ms tail), send the mic SOFTLY (x0.35)
    // so he does not hear and answer himself - that self-hearing was
    // making him repeat lines. Golu's real voice up close is LOUD
    // (rms >= 0.22) and always passes at full volume, so barge-in
    // keeps working.
    let samples = raw;
    if (performance.now() / 1000 < duckUntilWall && r < 0.22) {
      samples = Float32Array.from(raw, (v) => v * 0.35);
    }
    const pcm = floatToPcm16(resampleFloats(samples, micCtx.sampleRate, MIC_RATE));
    ws.send(pcm.buffer);
  };
  micSource.connect(micProcessor);
  micProcessor.connect(micSink);
  micSink.connect(micCtx.destination);
}

function stopMicrophone() {
  try { micProcessor && micProcessor.disconnect(); } catch {}
  try { micSource && micSource.disconnect(); } catch {}
  try { micSink && micSink.disconnect(); } catch {}
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (micCtx) micCtx.close().catch(() => {});
  micCtx = micStream = micProcessor = micSource = micSink = null;
}

/* ------------------------------------------------------------------ */
/* AI audio playback (24 kHz PCM) with interruption flush              */
/* ------------------------------------------------------------------ */
function ensurePlayCtx() {
  if (!playCtx) {
    // Ask for a 24 kHz context so the browser does not resample
    // every AI buffer 24k -> device rate (v3.14); fall back plainly
    // where a fixed rate is refused - buffers carry their own rate
    // either way, so playback is correct in both cases.
    try { playCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: AI_RATE }); }
    catch { playCtx = new (window.AudioContext || window.webkitAudioContext)(); }
  }
  if (playCtx.state === "suspended") playCtx.resume();
  // Speaker picker (v3.15): route output to the chosen device when
  // the browser supports setSinkId; silently keep the default else.
  const savedSpk = localStorage.getItem("jarvis_speaker_device") || "";
  if (savedSpk && typeof playCtx.setSinkId === "function") {
    playCtx.setSinkId(savedSpk).catch(() => {});
  }
  return playCtx;
}

function playAiAudio(arrayBuffer) {
  const ctx = ensurePlayCtx();
  const pcm = new Int16Array(arrayBuffer);
  if (!pcm.length) return;
  pbStats.received++;
  const floats = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) floats[i] = pcm[i] / 32768;
  speakLevel = Math.max(speakLevel, Math.min(1, rmsOf(floats) * 2.4));

  const buffer = ctx.createBuffer(1, floats.length, AI_RATE);
  buffer.copyToChannel(floats, 0);
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(ctx.destination);

  const now = ctx.currentTime;
  // Overflow guard: if more than ~6 s of audio is already queued
  // (a stall burst dumped a backlog), drop the backlog instead of
  // speaking stale audio for seconds - restart cleanly at "now".
  if (playHead - now > 6) {
    const dropped = scheduled.size;
    scheduled.forEach((s) => { try { s.stop(); } catch {} });
    scheduled.clear();
    pbStats.droppedQueue += dropped;
    playHead = 0;
  }
  let startAt;
  const gap = now - playHead;
  if (playHead === 0 || gap > 0.25) {
    // New turn: hold the first chunk for the adaptive jitter
    // cushion so the next chunks can chain gaplessly behind it.
    startAt = now + adaptBufferMs / 1000;
    turnHadStarvation = false;
  } else if (gap > 0.005) {
    // Starvation MID-TURN: the queue drained only a moment ago
    // (<250 ms) but the next chunk is already late - this is the
    // audible mid-sentence gap. Restart immediately and grow the
    // cushion so following turns absorb this much jitter.
    pbStats.starved++;
    turnHadStarvation = true;
    adaptBufferMs = Math.min(BUFFER_MAX_MS, Math.round(adaptBufferMs * 1.3) + 10);
    startAt = now + 0.02;
  } else {
    startAt = playHead; // mid-turn: chain exactly, no gap, no overlap
  }
  src.start(startAt);
  playHead = startAt + buffer.duration;
  // wall-clock end of everything scheduled so far (+300 ms tail):
  // the mic duck uses this to know JARVIS is still audible.
  duckUntilWall = performance.now() / 1000 + (playHead - ctx.currentTime) + 0.30;
  scheduled.add(src);
  src.onended = () => { scheduled.delete(src); pbStats.played++; };
  if (callActive) setState("speaking", "JARVIS bol raha hai...");
}

function flushPlayback() {
  // User interrupted: stop everything already scheduled, immediately.
  if (scheduled.size) pbStats.interruptedFlushes++;
  scheduled.forEach((s) => { try { s.stop(); } catch {} });
  scheduled.clear();
  playHead = 0;
  speakLevel = 0;
  duckUntilWall = 0;
}

/* ------------------------------------------------------------------ */
/* Animation loop: mouth + orb energy                                  */
/* ------------------------------------------------------------------ */
function tick() {
  micLevel *= 0.86;
  speakLevel *= 0.88;
  const speaking = document.body.dataset.state === "speaking";
  const level = speaking ? speakLevel : micLevel;
  document.documentElement.style.setProperty("--energy", level.toFixed(3));
  const mouth = speaking ? 4 + speakLevel * 24 : 4 + micLevel * 6;
  document.documentElement.style.setProperty("--mouth", mouth.toFixed(1) + "px");
  // If scheduled audio has run out, MAYERA finished speaking.
  if (speaking && playCtx && playCtx.currentTime > playHead + 0.05 && scheduled.size === 0) {
    // A turn that drained with NO starvation earns a smaller
    // cushion next time (faster first audio); floor 40 ms (v3.19).
    if (!turnHadStarvation && adaptBufferMs > BUFFER_MIN_MS) {
      adaptBufferMs = Math.max(BUFFER_MIN_MS, Math.round(adaptBufferMs * 0.9));
      turnHadStarvation = true; // shrink at most once per drained turn
    }
    setState("listening", "JARVIS sun raha hai...");
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

/* ------------------------------------------------------------------ */
/* Controls                                                            */
/* ------------------------------------------------------------------ */
btnStart.addEventListener("click", async () => {
  try {
    ensurePlayCtx();
    await startMicrophone();
  } catch (err) {
    setState("error", "Microphone ki permission nahi mili. Browser me mic Allow karke dobara try karein.");
    return;
  }
  callActive = true;
  micMuted = false;
  setButtons();
  setState("connecting", "Gemini se connect ho raha hai...");
  wsSend({ type: "start" });
});

btnMute.addEventListener("click", () => {
  micMuted = !micMuted;
  setButtons();
  wsSend({ type: "mute", muted: micMuted });
});

btnEnd.addEventListener("click", () => {
  wsSend({ type: "stop" });
  callActive = false;
  micMuted = false;
  flushPlayback();
  stopMicrophone();
  setButtons();
  setState("idle", "Call khatm. Phir milenge!");
});

/* starfield background */
(function makeStars() {
  const box = document.getElementById("stars");
  if (!box) return;
  for (let i = 0; i < 80; i++) {
    const s = document.createElement("span");
    const size = (Math.random() * 2 + 1).toFixed(1);
    s.style.left = (Math.random() * 100).toFixed(2) + "%";
    s.style.top = (Math.random() * 100).toFixed(2) + "%";
    s.style.width = size + "px";
    s.style.height = size + "px";
    s.style.animationDelay = (Math.random() * 3.4).toFixed(2) + "s";
    box.appendChild(s);
  }
})();

/* neon theme: pad the waveform to 36 thin bars + dotted side waves */
(function padWave() {
  const w = $("wave");
  if (!w) return;
  while (w.children.length < 36) {
    const i = document.createElement("i");
    i.style.animationDelay = (w.children.length * 0.07).toFixed(2) + "s";
    w.appendChild(i);
  }
})();

(function sideWaves() {
  const mk = (id, flip) => {
    const box = document.getElementById(id);
    if (!box) return;
    const cols = ["#22d3ee", "#38bdf8", "#818cf8", "#a855f7", "#d946ef", "#ec4899"];
    for (let strand = 0; strand < 2; strand++) {
      for (let k = 0; k <= 110; k++) {
        const t = k / 110;
        const d = document.createElement("span");
        const y = 50 + Math.sin(t * 5.4) * 17 + Math.sin(t * 11.5) * 4.5
                  + (strand ? 3.4 : -3.4) + (Math.random() - 0.5) * 2.4;
        d.style.left = ((flip ? 1 - t : t) * 100).toFixed(1) + "%";
        d.style.top = y.toFixed(1) + "%";
        const s = (Math.random() * 1.8 + 1.3).toFixed(1);
        d.style.width = s + "px";
        d.style.height = s + "px";
        d.style.background = cols[Math.min(cols.length - 1, Math.floor(t * cols.length))];
        d.style.animationDelay = (t * 1.6).toFixed(2) + "s";
        box.appendChild(d);
      }
    }
  };
  mk("swLeft", false);
  mk("swRight", true);
})();

setButtons();
connectWS();

/* ------------------------------------------------------------------ */
/* v2: memory pill, settings drawer, exit                              */
/* ------------------------------------------------------------------ */
const drawer = $("drawer"), scrim = $("scrim");

async function refreshMemPill() {
  try {
    const h = await (await fetch("/health")).json();
    $("memText").textContent = h.memory_enabled
      ? `Memory ON • ${h.memories}` : "Memory OFF";
  } catch {}
}
refreshMemPill();
setInterval(refreshMemPill, 15000);

// Push-to-Talk state must be right from page load, not only after
// the drawer is opened once.
(async () => {
  try {
    const s = await (await fetch("/api/settings")).json();
    pttEnabled = s.push_to_talk === "1";
  } catch {}
})();

async function refreshDiag() {
  const box = $("diagBox");
  if (!box) return;
  try {
    const h = await (await fetch("/health")).json();
    const c = h.client_playback || {};
    const a = h.audio || {}, t = h.tools || {};
    box.textContent =
      `Connection: ${h.connection_state} • Reconnects: ${h.reconnect_count}` +
      `\nJawab latency: last ${h.last_reply_latency_s ?? "-"}s • avg ${h.avg_reply_latency_s ?? "-"}s (${h.replies_measured} replies)` +
      `\nAudio out: ${a.ai_chunks_sent} chunks bheje • Mic in: ${a.mic_chunks_received} chunks` +
      `\nSpeaker (browser): played ${c.played ?? "-"} • gap (starved) ${c.starved ?? "-"} • dropped ${c.droppedQueue ?? "-"} • buffer ${c.bufferMs ?? "-"} ms` +
      `\nTools: ${t.calls} calls • last ${t.last_seconds ?? "-"}s • avg ${t.avg_seconds ?? "-"}s • deduped ${t.deduped}`;
  } catch { box.textContent = "Diagnostics abhi uplabdh nahi."; }
}

async function openDrawer() {
  drawer.classList.add("open");
  scrim.classList.add("show");
  drawer.setAttribute("aria-hidden", "false");
  refreshDiag();
  try {
    const s = await (await fetch("/api/settings")).json();
    $("setMemory").checked = s.memory_enabled === "1";
    $("setProactive").checked = s.proactive_enabled === "1";
    $("setInactivity").value = s.inactivity_seconds || "120";
    $("setReplySpeed").value = s.reply_speed || "fast";
    $("setWebSearch").checked = s.web_search === "1";
    $("setPTT").checked = s.push_to_talk === "1";
    pttEnabled = s.push_to_talk === "1";
    populateDevices();
    $("setQuietStart").value = s.quiet_start || "23:00";
    $("setQuietEnd").value = s.quiet_end || "07:00";
    await renderMemList();
  } catch {}
}
function closeDrawer() {
  drawer.classList.remove("open");
  scrim.classList.remove("show");
  drawer.setAttribute("aria-hidden", "true");
  refreshMemPill();
}
$("btnSettings").addEventListener("click", openDrawer);
$("btnCloseDrawer").addEventListener("click", closeDrawer);
scrim.addEventListener("click", closeDrawer);

async function saveSettings() {
  const payload = {
    memory_enabled: $("setMemory").checked ? "1" : "0",
    proactive_enabled: $("setProactive").checked ? "1" : "0",
    inactivity_seconds: $("setInactivity").value,
    reply_speed: $("setReplySpeed").value,
    web_search: $("setWebSearch").checked ? "1" : "0",
    push_to_talk: $("setPTT").checked ? "1" : "0",
    quiet_start: $("setQuietStart").value || "23:00",
    quiet_end: $("setQuietEnd").value || "07:00",
  };
  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {}
  refreshMemPill();
}
["setMemory", "setProactive", "setInactivity", "setQuietStart", "setQuietEnd", "setReplySpeed", "setWebSearch", "setPTT"]
  .forEach((id) => $(id).addEventListener("change", () => {
    saveSettings();
    pttEnabled = $("setPTT").checked;
    if (pttEnabled) setState("listening", "Push-to-Talk ON - Ctrl+Space dabakar rakho aur bolo");
  }));

/* Audio device picker (v3.15): list the devices the OS/browser
   actually exposes; names appear only after mic permission, which
   is the browser's own privacy rule. Choices persist locally and
   apply from the next START (mic) / immediately (speaker). */
async function populateDevices() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const fill = (selectId, kind, savedKey, fallbackLabel) => {
      const sel = $(selectId);
      if (!sel) return;
      const saved = localStorage.getItem(savedKey) || "";
      sel.innerHTML = "";
      const def = document.createElement("option");
      def.value = "";
      def.textContent = fallbackLabel;
      sel.appendChild(def);
      let n = 0;
      devices.filter((d) => d.kind === kind).forEach((d) => {
        n++;
        const opt = document.createElement("option");
        opt.value = d.deviceId;
        opt.textContent = d.label || `${fallbackLabel} ${n}`;
        sel.appendChild(opt);
      });
      sel.value = saved;
    };
    fill("setMicDevice", "audioinput", "jarvis_mic_device", "Default mic");
    fill("setSpeakerDevice", "audiooutput", "jarvis_speaker_device", "Default speaker");
  } catch {}
}
$("setMicDevice").addEventListener("change", () => {
  localStorage.setItem("jarvis_mic_device", $("setMicDevice").value);
});
$("setSpeakerDevice").addEventListener("change", () => {
  localStorage.setItem("jarvis_speaker_device", $("setSpeakerDevice").value);
  if (playCtx) ensurePlayCtx();
});

/* Real confirmation (v3.17, Mark LVI's rule): irreversible actions
   wait for THIS card. The model asked; only your tap answers. No
   tap within the server's timeout counts as Nahi. */
let confirmId = null;
function showConfirm(id, text) {
  confirmId = id;
  $("confirmText").textContent = text || "Pakka karu?";
  $("confirmBox").style.display = "flex";
}
async function answerConfirm(approved) {
  $("confirmBox").style.display = "none";
  if (!confirmId) return;
  const id = confirmId;
  confirmId = null;
  try {
    await fetch("/api/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, approved }),
    });
  } catch {}
}
$("confirmYes").addEventListener("click", () => answerConfirm(true));
$("confirmNo").addEventListener("click", () => answerConfirm(false));

async function renderMemList() {
  const box = $("memList");
  box.innerHTML = "";
  try {
    const data = await (await fetch("/api/memory")).json();
    if (!data.items.length) {
      box.innerHTML = '<div class="mem-empty">Abhi kuch yaad nahi rakha gaya.</div>';
      return;
    }
    data.items.forEach((m) => {
      const row = document.createElement("div");
      row.className = "mem-item";
      const txt = document.createElement("span");
      // Memory panel (v3.15): show WHEN each fact was learned too.
      const when = m.created_at
        ? new Date(m.created_at * 1000).toLocaleDateString("en-IN",
            { day: "numeric", month: "short" })
        : "";
      txt.textContent = when ? `${m.content}  ·  ${when}` : m.content;
      const del = document.createElement("button");
      del.textContent = "Mita do";
      del.addEventListener("click", async () => {
        await fetch(`/api/memory/${m.id}`, { method: "DELETE" });
        renderMemList();
      });
      row.appendChild(txt);
      row.appendChild(del);
      box.appendChild(row);
    });
  } catch {}
}
$("btnClearMem").addEventListener("click", async () => {
  await fetch("/api/memory/clear", { method: "POST" });
  renderMemList();
  refreshMemPill();
});

$("btnExit").addEventListener("click", async () => {
  if (callActive) btnEnd.click();
  setState("idle", "JARVIS band ho gaya. Dhanyavaad, Golu! 👋");
  try { await fetch("/api/exit", { method: "POST" }); } catch {}
  connDot.className = "conn-dot err";
  connText.textContent = "Band";
});
