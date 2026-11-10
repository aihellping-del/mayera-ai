# JARVIS AI — Voice Companion (formerly MAYERA)

**v2.0** — MAYERA is now a true companion, not just a voice pipe:

- **Long-term memory (SQLite):** she remembers facts, preferences, plans
  and decisions across restarts. Say *"yaad rakho..."* and it is saved;
  say *"bhool jao"* and it is deleted. Passwords/keys are refused.
- **Conversation checkpoint:** when a call ends, where the talk stopped
  is saved. Next time she greets you and continues from there — after a
  long absence, with a proper welcome-back.
- **Proactive check-ins:** while the app is running, if you go quiet for
  a while (default 2 minutes), *she* starts talking — a gentle check-in,
  never during quiet hours (default 11 PM–7 AM), never twice in a row,
  and fully switchable in Settings.
- **Voice tools (function calling):** remember / forget / current time /
  open a website in your browser — plus Google Search grounding for
  fresh facts instead of guessing.
- **PC Control (v3.1):** by voice she can open/close apps ("Chrome
  kholo", "Notepad band karo"), change volume, type text you dictate
  into the front window, and take a screenshot (saved to Pictures).
  v3.4 adds voice mouse control (move/click/scroll/keys) and
  YouTube by voice: name any video/song to play it, or hear the
  top-5 results and pick a number.
  Safety: a fixed app allowlist only — Explorer and MAYERA herself can
  never be closed, and there is no shutdown/delete tool at all.
- **Emotional intelligence:** she reads your tone — happy, sad, angry,
  joking, confused — and adapts her voice and words to match.
- **STOP command:** say *"ruk jao"* / *"stop"* and she stops instantly.
- **Thinking face:** when you finish speaking, her eyes drift up while
  she thinks, then she answers.
- **Settings drawer (⚙️):** memory on/off, proactive on/off, inactivity
  timing, quiet hours, view + delete saved memories, clear all.
- v1.1's emotional personality, no-cutting-off voice tuning and premium
  UI are all included.

Honest limit: proactive check-ins work **while the app is running** —
a fully closed app cannot (and does not pretend to) start talking.

MAYERA is a real-time AI voice companion for Windows. You talk, she listens,
thinks and speaks back — in Hindi, English or Hinglish — through a futuristic
holographic robotic face. Voice-only: there is no chat box and no transcript,
just a natural two-way conversation powered by the **Google Gemini Live API**.

```
Microphone → Browser → Python (FastAPI/WebSocket) → Gemini Live → Speaker
```

---

## What you need

| Thing | Details |
|---|---|
| Windows | Windows 10 or 11 |
| Python | 3.10 or newer — [python.org/downloads](https://www.python.org/downloads/) (tick **"Add python.exe to PATH"** while installing) |
| Gemini API key | Free from [Google AI Studio](https://aistudio.google.com/apikey) — sign in with Google → *Create API key* |
| Hardware | Any microphone + speakers/headphones, internet connection |

---

## Install (one time)

1. Unzip this project.
2. Double-click **`INSTALL.bat`** — it creates a private Python environment
   (`.venv`) for MAYERA and installs all packages into it. Your system Python
   is untouched. (Needs internet, takes 1–2 minutes.)

Manual alternative:

```bat
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

## Run (every time)

1. Double-click **`START_MAYERA.bat`** — that's it.
2. **First run only:** paste your **Gemini API key** when asked (input
   stays hidden; paste with Ctrl+V or right-click) and press Enter.
   From the next run MAYERA starts directly — the key is remembered
   on this PC (see below).
3. The MAYERA window opens in your browser automatically
   (or open <http://127.0.0.1:8765> yourself).
4. Click **START**, allow microphone access, and just talk.
   - **MUTE** — mute/unmute your microphone.
   - **END** — end the voice session.
   - You can **interrupt MAYERA while she is speaking** — just start talking;
     she stops and listens (handled by Gemini Live VAD + instant playback flush).
5. Close with **Ctrl+C** in the MAYERA terminal window, or the ✕ button.

### API key security

- The key is **never** hardcoded in the code and **never printed in logs**.
- At your choice, it is saved on **this PC only** in `key.dat`, encrypted
  with **Windows DPAPI** — tied to your Windows account. The file holds
  only the encrypted blob (never plain text), and it cannot be opened
  on another PC or by another Windows user.
- To change or forget the key: run **`KEY_CHANGE.bat`** once, then start
  MAYERA — you will be asked for the new key, which then gets saved.
- The key is never sent anywhere except to Google's Gemini API when
  MAYERA talks.

### Auto-update

- Every start, `updater.py` first checks the update repo
  (`aihellping-del/mayera-ai` on GitHub, program code only — no key,
  no memories). A newer version downloads and applies itself;
  `key.dat`, `mayera_memory.db` and the `.venv` folder are never
  touched, and if the check fails MAYERA just starts as usual.
- If that repo is **private**, run **`GITHUB_TOKEN.bat`** once and
  paste a read-only GitHub token (fine-grained, only the mayera-ai
  repo, Contents = Read-only). It is saved DPAPI-encrypted in
  `gh_token.dat`, exactly like the API key. A public repo needs no
  token at all.

---

## How it works

| Piece | File(s) | Job |
|---|---|---|
| Server + WebSocket | `main.py` | FastAPI app; serves the UI, brokers audio between browser and Gemini |
| Gemini Live session | `mayera/gemini_live.py` | Connects via the official `google-genai` SDK, model fallback, streaming send/receive, interruption events, auto-reconnect with session resumption |
| Audio helpers | `mayera/audio_utils.py` | PCM16 conversion/resampling utilities (bytes end-to-end, no string encoding bugs) |
| Connection manager | `mayera/connection_manager.py` | Exactly one browser socket at a time — a second tab replaces the first, so no duplicate connections |
| Config | `mayera/config.py` | Model candidates, voice, language, sample rates, MAYERA's personality |
| Errors | `mayera/errors.py` | Turns API/network/model failures into short friendly messages |
| Memory | `mayera/memory_store.py` | SQLite store (`mayera_memory.db`, created on first run): saved facts, conversation checkpoint, settings. Secrets are refused |
| Voice tools | `mayera/tools.py` | Function calling: remember / forget / current time / open website, executed locally and reported back to the model |
| Proactive | `mayera/proactive.py` | Decides when MAYERA may start a check-in herself: inactivity, quiet hours, no repeat nagging |
| UI | `static/index.html`, `styles.css`, `app.js` | Holographic orb + robotic face (blinking neon eyes, small nose, smiling idle mouth, thinking expression), listening/speaking animations, mic capture (16 kHz), playback (24 kHz) with interruption flush, settings drawer + memory pill |

**Audio formats** (fixed by Gemini Live): mic → PCM 16-bit @ 16 kHz ·
AI voice → PCM 16-bit @ 24 kHz.

**Voice & language**: female prebuilt voice `Aoede`, language `hi-IN`
(Hindi-first; English and Hinglish are understood and matched automatically).
Change them with environment variables `MAYERA_VOICE`, `MAYERA_LANGUAGE`, or
force a model with `MAYERA_MODEL` (see `mayera/config.py`).

**Reconnection**: if the network drops, MAYERA retries with backoff and uses
Gemini session resumption, so the conversation continues instead of resetting.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Python nahi mila" | Install Python 3.10+ and tick *Add python.exe to PATH*, then rerun |
| "Gemini API key galat hai" | Create a fresh key in [Google AI Studio](https://aistudio.google.com/apikey) and paste it carefully (no spaces) |
| Mic permission error in UI | In the browser address bar, allow microphone for `127.0.0.1`, then press START TALKING again |
| Model error message | Gemini Live model names change over time; MAYERA already tries several models in order (list in `mayera/config.py`) |
| Quota error | The free tier has usage limits — wait a while and try again |
| Port 8765 already in use | Close the other MAYERA window, or set `MAYERA_PORT=9000` before running |
| No sound / echo | Use headphones; keep the mic a little away from speakers |

---

## Testing

See **[TEST_REPORT.md](TEST_REPORT.md)** for exactly what was verified during
development, what passed, and the short checklist to run once on your own PC
(real microphone + real API key tests can only happen on your machine).

## Notes

- MAYERA runs fully on **your** PC with **your** API key; conversations go
  between your browser, this local server and Google's Gemini Live API.
- Gemini Live free-tier limits apply to your key.

---

## Credits

From v3.17, several features of JARVIS are adapted from **Mark LVI**
by **FatihMakes** (licensed CC BY-NC 4.0 -
https://creativecommons.org/licenses/by-nc/4.0/): the project
folder structure, the shared undo stack, the UI-issued confirmation
gate, file operations with recoverable trash, self-describing
plugins, and the measured Gemini Live model ladder. Adaptations are
reimplemented for this codebase; the Gemini Live engine, DPAPI key
vault, memory store and auto-update are JARVIS's own.
