"use strict";
/* JARVIS Robot Dost (v3.36) - kone wale robot ki jaan.
 *
 * Haalat kahan se aati hai: backend har status badlav par
 * WebSocket se {type:"status", state, message} bhejta hai -
 * wahi protocol jo badi HUD (app.js) sunti hai. Lekin /ws par
 * EK hi client reh sakta hai (dusra judte hi pehla kat jata
 * hai, design hi aisa hai), isliye robot usi status ka
 * read-only mirror /robot-status se poll karta hai. Robot na
 * mic kholta hai, na audio bajata hai, na kuch bhejta hai -
 * awaaz sirf Gemini Live ki rehti hai.
 *
 * Caring andaaz (sirf visual): lagatar ~45s idle/connected
 * rahe to robot dil wali aankhon ke saath chhota bubble dikha
 * kar owner ki pasandeeda caring lines ghumata hai. Koi bhi
 * asal haalat (bolna/sunna/sochna) aate hi bubble turant
 * gayab ho jata hai. Koi text chat box nahi hai - voice-only
 * UI ka niyam yahan bhi lagu hai.
 */

var CARE_LINES = [
  "Tum kya kar rhe ho?",
  "Khana khaya tumne?",
  "Paani piya? Apna khayal rakha karo",
  "Thoda aaram bhi kar lo",
  "Thak to nahi gaye?"
];
var CARE_AFTER_MS = 45000;   /* itni der chup rahe to pyaar se poochhe */
var CARE_ROTATE_MS = 6000;   /* har itni der me agli caring line */
var POLL_MS = 400;

var stage = document.getElementById("stage");
var bubble = document.getElementById("bubble");
var bubbleText = document.getElementById("bubbleText");

var VISUAL_CLASSES = ["is-idle", "is-listening", "is-speaking",
                      "is-thinking", "is-caring", "is-error"];

var visual = "is-idle";      /* abhi dikh rahi haalat */
var idleSince = Date.now();  /* idle kab se chal raha hai */
var caring = false;
var careIndex = 0;
var careTimer = null;

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
  bubble.classList.remove("show");
}

function startCaring() {
  caring = true;
  careIndex = 0;
  bubbleText.textContent = CARE_LINES[careIndex];
  bubble.classList.add("show");
  setVisual("is-caring");
  careTimer = setInterval(function () {
    careIndex = (careIndex + 1) % CARE_LINES.length;
    bubbleText.textContent = CARE_LINES[careIndex];
  }, CARE_ROTATE_MS);
}

function applyState(state) {
  var next = mapState(state);
  if (next !== "is-idle") {
    /* Asal haalat aayi: caring turant band, ghadi reset. */
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
