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

// --- microphone graph ---
let micCtx = null, micStream = null, micProcessor = null, micSource = null, micSink = null;

// --- playback graph ---
let playCtx = null;
let playHead = 0;                 // next scheduled buffer start time
const scheduled = new Set();      // live BufferSources (for interruption flush)

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
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  micCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: MIC_RATE });
  micSource = micCtx.createMediaStreamSource(micStream);
  // 2048 samples @16 kHz = 128 ms per chunk (was 4096 = 256 ms):
  // his speech reaches Gemini up to ~128 ms sooner at every turn end.
  micProcessor = micCtx.createScriptProcessor(2048, 1, 1);
  micSink = micCtx.createGain(); micSink.gain.value = 0; // silent sink, no echo

  micProcessor.onaudioprocess = (e) => {
    const raw = e.inputBuffer.getChannelData(0);
    micLevel = Math.max(micLevel, Math.min(1, rmsOf(raw) * 3));
    if (!callActive || micMuted) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const pcm = floatToPcm16(resampleFloats(raw, micCtx.sampleRate, MIC_RATE));
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
  if (!playCtx) playCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (playCtx.state === "suspended") playCtx.resume();
  return playCtx;
}

function playAiAudio(arrayBuffer) {
  const ctx = ensurePlayCtx();
  const pcm = new Int16Array(arrayBuffer);
  if (!pcm.length) return;
  const floats = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) floats[i] = pcm[i] / 32768;
  speakLevel = Math.max(speakLevel, Math.min(1, rmsOf(floats) * 2.4));

  const buffer = ctx.createBuffer(1, floats.length, AI_RATE);
  buffer.copyToChannel(floats, 0);
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(ctx.destination);
  const startAt = Math.max(playHead, ctx.currentTime + 0.03);
  src.start(startAt);
  playHead = startAt + buffer.duration;
  scheduled.add(src);
  src.onended = () => scheduled.delete(src);
  if (callActive) setState("speaking", "JARVIS bol raha hai...");
}

function flushPlayback() {
  // User interrupted: stop everything already scheduled, immediately.
  scheduled.forEach((s) => { try { s.stop(); } catch {} });
  scheduled.clear();
  playHead = 0;
  speakLevel = 0;
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

async function openDrawer() {
  drawer.classList.add("open");
  scrim.classList.add("show");
  drawer.setAttribute("aria-hidden", "false");
  try {
    const s = await (await fetch("/api/settings")).json();
    $("setMemory").checked = s.memory_enabled === "1";
    $("setProactive").checked = s.proactive_enabled === "1";
    $("setInactivity").value = s.inactivity_seconds || "120";
    $("setReplySpeed").value = s.reply_speed || "fast";
    $("setWebSearch").checked = s.web_search === "1";
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
["setMemory", "setProactive", "setInactivity", "setQuietStart", "setQuietEnd", "setReplySpeed", "setWebSearch"]
  .forEach((id) => $(id).addEventListener("change", saveSettings));

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
      txt.textContent = m.content;
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
