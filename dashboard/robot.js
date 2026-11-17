"use strict";
/* =====================================================================
   JARVIS Robot Dost (v3.37) - robot hi JARVIS hai.

   Owner ka aakhiri faisla (v3.36.1 ke baad): "Agent RoBot
   Chaiye tha" - kone wala robot sirf chehra nahi, WAHI asal
   client hai. Is page me ab HUD (app.js) wala poora voice
   engine chalta hai: mic -> getUserMedia -> 16 kHz PCM ->
   /ws; Gemini Live ki awaaz <- 24 kHz PCM playback (jitter
   buffer + interruption flush ke saath). Bolne wali haalat
   status jhandon se nahi, ASAL scheduled playback se banti
   hai - muh tabhi hilega jab JARVIS ki awaaz sach me baj
   rahi hogi.

   Khud-bolna (v3.36.1 me jodi gayi browser-awaaz wali
   taiyaar-boli) POORI tarah hata di gayi hai - owner ne
   use seedha mana kiya tha ("apne se hi sab baat kar rha
   hai"). Robot ab SIRF JARVIS ki asal Gemini Live awaaz
   bolta hai; koi taiyaar line, koi bubble, koi apni alag
   awaaz nahi bachi.

   Ek-client niyam barkarar: /ws par ek hi client rehta
   hai. Gear button se badi HUD khule to uska socket is
   socket ki jagah le leta hai (server purane ko "Replaced
   by a new connection" keh kar band karta hai) - robot
   tab shaant "badi window khuli hai" haalat dikhata hai
   aur dobara connect ki daud NAHI lagata; is window ko
   band karke JARVIS dobara chalane se robot wapas jeevit
   hota hai.

   Controls: robot (ya mic button) par click = baat shuru /
   band. Gear button = badi HUD window on-demand (POST
   /open-hud). Confirmation card (Haan/Nahi) yahin aata hai,
   bilkul HUD ki tarah - bina iske gated kaam (trash_file,
   whatsapp_send, run_command) robot-only mode me kabhi
   pure hi nahi honge.
   ===================================================================== */

const MIC_RATE = 16000;    // Gemini Live input format
const AI_RATE = 24000;     // Gemini Live output format

const $ = (id) => document.getElementById(id);
const stage = $("stage");
const robotEl = $("robot");
const statusText = $("statusText");
const micBtn = $("btnMic");
const hudNote = $("hudNote");

let ws = null;
let wsReconnectTimer = null;
let hudTookOver = false;   // badi HUD ne socket le liya

let callActive = false;
let micMuted = false;

// Push-to-Talk (app.js jaisa hi): server Settings se aata hai,
// is page ki apni keys + server ke {"type":"ptt"} sandesh.
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
let duckUntilWall = 0;            // JARVIS ki awaaz sunai dene tak ki khidki (mic echo duck)
const scheduled = new Set();      // live BufferSources (interruption flush ke liye)

// --- adaptive jitter buffer + playback stats (app.js v3.14/v3.28) ---
let adaptBufferMs = 110;
const BUFFER_MIN_MS = 60, BUFFER_MAX_MS = 300;
let turnHadStarvation = false;
const pbStats = {
  received: 0, played: 0, starved: 0, droppedQueue: 0,
  interruptedFlushes: 0,
};

// --- animation levels (0..1) ---
let micLevel = 0, speakLevel = 0;

/* ------------------------------------------------------------------ */
/* Haalat -> robot ka chehra                                           */
/* ------------------------------------------------------------------ */
const VISUAL_CLASSES = ["is-idle", "is-listening", "is-speaking",
                        "is-thinking", "is-error", "is-hudopen"];
let visual = "is-idle";
let serverState = "idle";   // server se aayi aakhri haalat

function setVisual(next) {
  if (next === visual) return;
  for (const c of VISUAL_CLASSES) stage.classList.remove(c);
  stage.classList.add(next);
  visual = next;
}

function mapServerState(state) {
  switch (state) {
    case "speaking": return "is-speaking";
    case "listening": return "is-listening";
    case "muted": return "is-listening";
    case "connected": return callActive ? "is-listening" : "is-idle";
    case "thinking": return "is-thinking";
    case "connecting": return "is-thinking";
    case "reconnecting": return "is-thinking";
    case "error": return "is-error";
    default: return "is-idle";   /* idle / kuch bhi aur */
  }
}

function audioPlaying() {
  // Muh asal playback se: kuch scheduled hai aur playHead
  // abhi aane wala hai (thoda sa tail bhi chal raha mana).
  return !!(playCtx && scheduled.size > 0 &&
            playCtx.currentTime <= playHead + 0.05);
}

function refreshVisual() {
  if (hudTookOver) { setVisual("is-hudopen"); return; }
  if (serverState === "error") { setVisual("is-error"); return; }
  if (audioPlaying()) { setVisual("is-speaking"); return; }
  setVisual(mapServerState(serverState));
}

function setState(state, message) {
  serverState = state;
  if (message) statusText.textContent = message;
  refreshVisual();
}

/* ------------------------------------------------------------------ */
/* WebSocket (ek connection; HUD le le to shaant haar)                 */
/* ------------------------------------------------------------------ */
function connectWS() {
  if (hudTookOver) return;   // badi window ke hote hue daud nahi
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    setState("idle", "JARVIS taiyaar hai — robot ko chhu kar baat shuru karo");
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
  ws.onclose = (ev) => {
    ws = null;
    if (ev && ev.reason && ev.reason.indexOf("Replaced") === 0) {
      // Badi HUD khul gayi - socket usi ka hai. Robot shaant
      // rahega; dobara connect karne ki koshish bhi ladai hai.
      hudTookOver = true;
      callActive = false;
      flushPlayback();
      stopMicrophone();
      if (hudNote) hudNote.hidden = false;
      statusText.textContent = "Badi window khuli hai";
      refreshVisual();
      return;
    }
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWS, 2000); // auto reconnect
  };
  ws.onerror = () => { try { ws.close(); } catch {} };
}
setInterval(() => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" })); }, 20000);

// Playback diagnostics (app.js jaisa): server /health ke liye
// is client ke counters har 5 s me, sirf call ke dauraan.
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
/* Microphone capture -> PCM16 16 kHz -> WebSocket (app.js se)         */
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
  // Settings me chuna mic (HUD ke saath shared localStorage).
  const savedMic = localStorage.getItem("jarvis_mic_device") || "";
  const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  if (savedMic) audio.deviceId = { exact: savedMic };
  micStream = await navigator.mediaDevices.getUserMedia({ audio });
  micCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: MIC_RATE });
  micSource = micCtx.createMediaStreamSource(micStream);
  micProcessor = micCtx.createScriptProcessor(1024, 1, 1);
  micSink = micCtx.createGain(); micSink.gain.value = 0; // silent sink, no echo

  micProcessor.onaudioprocess = (e) => {
    const raw = e.inputBuffer.getChannelData(0);
    const r = rmsOf(raw);
    micLevel = Math.max(micLevel, Math.min(1, r * 3));
    if (!callActive || micMuted) return;
    if (pttEnabled && !pttHeld) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    // Echo guard (app.js v3.10): JARVIS ki apni awaaz bajte
    // samay mic naram bhejta hai taaki wo khud ko sun kar
    // dohrata na rahe; zor ki asal awaaz hamesha full jati hai.
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
    try { playCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: AI_RATE }); }
    catch { playCtx = new (window.AudioContext || window.webkitAudioContext)(); }
  }
  if (playCtx.state === "suspended") playCtx.resume();
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
  // Overflow guard (app.js v3.31): ~10 s se zyada queued ho
  // to purana backlog girakar saaf shuru - basi awaaz nahi.
  if (playHead - now > 10) {
    const dropped = scheduled.size;
    scheduled.forEach((s) => { try { s.stop(); } catch {} });
    scheduled.clear();
    pbStats.droppedQueue += dropped;
    playHead = 0;
  }
  let startAt;
  const gap = now - playHead;
  if (playHead === 0 || gap > 0.25) {
    startAt = now + adaptBufferMs / 1000;   // nayi baari: jitter cushion
    turnHadStarvation = false;
  } else if (gap > 0.005) {
    pbStats.starved++;
    turnHadStarvation = true;
    adaptBufferMs = Math.min(BUFFER_MAX_MS, Math.round(adaptBufferMs * 1.3) + 10);
    startAt = now + 0.02;
  } else {
    startAt = playHead; // beech me: bilkul chipka kar, koi gap nahi
  }
  src.start(startAt);
  playHead = startAt + buffer.duration;
  duckUntilWall = performance.now() / 1000 + (playHead - ctx.currentTime) + 0.30;
  scheduled.add(src);
  src.onended = () => { scheduled.delete(src); pbStats.played++; };
  refreshVisual();   // bolne ki haalat turant (asal playback se)
}

function flushPlayback() {
  // Owner ne beech me bola: scheduled sab kuch turant roko.
  if (scheduled.size) pbStats.interruptedFlushes++;
  scheduled.forEach((s) => { try { s.stop(); } catch {} });
  scheduled.clear();
  playHead = 0;
  speakLevel = 0;
  duckUntilWall = 0;
  refreshVisual();
}

/* ------------------------------------------------------------------ */
/* Animation loop: muh asal awaaz ke level se                          */
/* ------------------------------------------------------------------ */
const mouthTalk = document.querySelector(".mouth-talk");
function tick() {
  micLevel *= 0.86;
  speakLevel *= 0.88;
  refreshVisual();
  if (mouthTalk) {
    // Bolte samay muh ka khulna speakLevel (asal audio ki
    // taakat) se chalta hai - flag se nahi.
    const open = visual === "is-speaking" ? 0.35 + speakLevel * 1.1 : 0.35;
    mouthTalk.style.transform = `scaleY(${open.toFixed(2)})`;
  }
  // Turn khatm (queue khaali) par cushion ka hisaab (app.js):
  if (visual === "is-speaking" && playCtx &&
      playCtx.currentTime > playHead + 0.05 && scheduled.size === 0) {
    if (!turnHadStarvation && adaptBufferMs > BUFFER_MIN_MS) {
      adaptBufferMs = Math.max(BUFFER_MIN_MS, Math.round(adaptBufferMs * 0.9));
      turnHadStarvation = true;
    }
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

/* ------------------------------------------------------------------ */
/* Controls: robot/mic = baat shuru-band, gear = badi window           */
/* ------------------------------------------------------------------ */
async function toggleCall() {
  if (hudTookOver) return;   // socket badi window ke paas hai
  if (callActive) {
    wsSend({ type: "stop" });
    callActive = false;
    micMuted = false;
    flushPlayback();
    stopMicrophone();
    setState("idle", "Call khatm. Phir milenge!");
    return;
  }
  try {
    ensurePlayCtx();
    await startMicrophone();
  } catch (err) {
    setState("error", "Microphone ki permission nahi mili. Chrome me mic Allow karke dobara chhuo.");
    return;
  }
  callActive = true;
  micMuted = false;
  setState("connecting", "Gemini se connect ho raha hai...");
  wsSend({ type: "start" });
}
if (robotEl) robotEl.addEventListener("click", toggleCall);
if (micBtn) micBtn.addEventListener("click", toggleCall);

$("btnHud").addEventListener("click", async () => {
  // Badi HUD on-demand: backend open_ui() chalata hai. Uska
  // socket is robot ka socket le lega (ek-client niyam) -
  // onclose usi ko sambhalega.
  try { await fetch("/open-hud", { method: "POST" }); } catch {}
});

/* Confirmation card (app.js jaisa): gated kaam sirf is tap
   se Haan hota hai; bina tap = Nahi (server timeout). */
let confirmId = null;
function showConfirm(id, text) {
  confirmId = id;
  $("confirmText").textContent = text || "Pakka karu?";
  $("confirmBox").hidden = false;
}
async function answerConfirm(approved) {
  $("confirmBox").hidden = true;
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

// Push-to-Talk setting page load par hi sahi rahe (Settings
// badi window me badli jati hai, lagu yahin se hoti hai).
(async () => {
  try {
    const s = await (await fetch("/api/settings")).json();
    pttEnabled = s.push_to_talk === "1";
  } catch {}
})();

connectWS();
