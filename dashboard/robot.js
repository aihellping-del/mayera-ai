"use strict";
/* JARVIS Robot Dost (v3.36, awaaz v3.36.1) - kone wale robot
 * ki jaan.
 *
 * Haalat kahan se aati hai: backend har status badlav par
 * WebSocket se {type:"status", state, message} bhejta hai -
 * wahi protocol jo badi HUD (app.js) sunti hai. Lekin /ws par
 * EK hi client reh sakta hai (dusra judte hi pehla kat jata
 * hai, design hi aisa hai), isliye robot usi status ka
 * read-only mirror /robot-status se poll karta hai. Robot na
 * mic kholta hai, na kuch bhejta hai - JARVIS ki asal awaaz
 * sirf Gemini Live ki rehti hai.
 *
 * Caring andaaz (v3.36.1, owner ki order: "baat karne bole,
 * likhne ni"): lagatar ~45s idle/connected rahe to robot dil
 * wali aankhon ke saath apni caring lines BOLTA hai - Chrome
 * ki apni Hindi awaaz (window.speechSynthesis) se, koi naya
 * package ya backend TTS nahi. Likha hua bubble hata diya
 * gaya hai; dil wali aankhein, gulabi gaal aur udte dil waisa
 * hi rehte hain. Har caring cycle me EK line boli jati hai.
 * Koi bhi asal haalat (bolna/sunna/sochna/error) aate hi
 * robot ki awaaz turant band (speechSynthesis.cancel()).
 * Robot par click = robot ki awaaz band/chalu (pasand
 * localStorage me yaad rehti hai). Awaaz default ON hai.
 * Koi text chat box nahi hai - voice-only UI ka niyam yahan
 * bhi lagu hai.
 */

var CARE_LINES = [
  "Tum kya kar rhe ho?",
  "Khana khaya tumne?",
  "Paani piya? Apna khayal rakha karo",
  "Thoda aaram bhi kar lo",
  "Thak to nahi gaye?"
];
/* Bolne ke liye wahi lines Devanagari me - Hindi awaaz inhe
 * sahi uchcharan se bolti hai. */
var CARE_SPEECH_LINES = [
  "तुम क्या कर रहे हो?",
  "खाना खाया तुमने?",
  "पानी पिया? अपना ख़याल रखा करो",
  "थोड़ा आराम भी कर लो",
  "थक तो नहीं गए?"
];
var CARE_AFTER_MS = 45000;   /* itni der chup rahe to pyaar se bole */
var CARE_ROTATE_MS = 6000;   /* har cycle me agli caring line */
var POLL_MS = 400;

var stage = document.getElementById("stage");
var robotEl = document.getElementById("robot");

var VISUAL_CLASSES = ["is-idle", "is-listening", "is-speaking",
                      "is-thinking", "is-caring", "is-error"];

var visual = "is-idle";      /* abhi dikh rahi haalat */
var idleSince = Date.now();  /* idle kab se chal raha hai */
var caring = false;
var careIndex = 0;
var careTimer = null;

/* ---------- Robot ki apni awaaz (Chrome speechSynthesis) ---------- */
var voiceOn = true;
try {
  voiceOn = window.localStorage.getItem("jarvisRobotVoice") !== "off";
} catch (e) { /* storage na mile to default ON */ }

function pickHindiVoice() {
  if (!("speechSynthesis" in window)) return null;
  try {
    var voices = window.speechSynthesis.getVoices();
    for (var i = 0; i < voices.length; i++) {
      if ((voices[i].lang || "").toLowerCase().indexOf("hi") === 0) {
        return voices[i];
      }
    }
  } catch (e) { /* awaaz list na mile to default awaaz */ }
  return null;
}
if ("speechSynthesis" in window) {
  try {
    /* Awaazein aksar der se aati hain; list badle to phir try */
    window.speechSynthesis.onvoiceschanged = function () {
      pickHindiVoice();
    };
  } catch (e) { /* koi baat nahi */ }
}

function speakCareLine() {
  if (!voiceOn || !("speechSynthesis" in window)) return;
  try {
    window.speechSynthesis.cancel();
    var line = CARE_SPEECH_LINES[careIndex % CARE_SPEECH_LINES.length];
    var utter = new SpeechSynthesisUtterance(line);
    utter.lang = "hi-IN";
    var hindi = pickHindiVoice();
    if (hindi) utter.voice = hindi;
    window.speechSynthesis.speak(utter);
  } catch (e) { /* awaaz na bane to robot chup rahe */ }
}

function stopSpeech() {
  if ("speechSynthesis" in window) {
    try { window.speechSynthesis.cancel(); } catch (e) { /* ignore */ }
  }
}

/* Robot par click: robot ki awaaz band/chalu (yaad ke saath) */
if (robotEl) {
  robotEl.addEventListener("click", function () {
    voiceOn = !voiceOn;
    try {
      window.localStorage.setItem("jarvisRobotVoice",
                                  voiceOn ? "on" : "off");
    } catch (e) { /* yaad na rahe to bhi toggle chalega */ }
    if (!voiceOn) stopSpeech();
  });
}

/* Window band ho to bolti awaaz wahi ruk jaye */
window.addEventListener("beforeunload", stopSpeech);
window.addEventListener("pagehide", stopSpeech);

/* ---------- Haalat aur caring cycle ---------- */
function mapState(state) {
  switch (state) {
    case "speaking": return "is-speaking";
    case "listening": return "is-listening";
    case "muted": return "is-listening";
    case "thinking": return "is-thinking";
    case "error": return "is-error";
    default: return "is-idle";   /* idle / connected / kuch bhi aur */
  }
}

function setVisual(next) {
  if (next === visual) return;
  for (var i = 0; i < VISUAL_CLASSES.length; i++) {
    stage.classList.remove(VISUAL_CLASSES[i]);
  }
  stage.classList.add(next);
  visual = next;
}

function stopCaring() {
  if (careTimer !== null) {
    clearInterval(careTimer);
    careTimer = null;
  }
  caring = false;
  stopSpeech();
}

function startCaring() {
  caring = true;
  setVisual("is-caring");
  speakCareLine();               /* is cycle ki ek line */
  careTimer = setInterval(function () {
    careIndex = (careIndex + 1) % CARE_SPEECH_LINES.length;
    speakCareLine();             /* har naye cycle ki ek line */
  }, CARE_ROTATE_MS);
}

function applyState(state) {
  var next = mapState(state);
  if (next !== "is-idle") {
    /* Asal haalat aayi: caring + robot ki awaaz turant band. */
    stopCaring();
    idleSince = Date.now();
    setVisual(next);
    return;
  }
  /* Idle parivar (idle/connected): */
  if (caring) return;                    /* caring chalu hai, rehne do */
  setVisual("is-idle");
  if (Date.now() - idleSince >= CARE_AFTER_MS) startCaring();
}

function poll() {
  fetch("/robot-status", { cache: "no-store" })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (data && typeof data.state === "string") applyState(data.state);
    })
    .catch(function () {
      /* Server band/milta nahi: robot chup-chaap idle rehta hai. */
    });
}

setInterval(poll, POLL_MS);
poll();
