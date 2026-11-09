# MAYERA — Test Report

Honest record of what was verified while building MAYERA, and what still
needs one verification run on your own Windows PC. **Nothing is claimed
as working unless it was actually run.**

Test environment: Linux development machine, Python 3.12, the exact
`requirements.txt` of this project. Windows-only and real-key tests are
listed separately below — they cannot be faked and were not faked.

---

## ✅ Tested and PASSED here

| # | Test | Result |
|---|---|---|
| 1 | Python syntax compile — `main.py` + all `mayera/*.py` modules | ✅ Pass |
| 2 | Dependencies install from `requirements.txt` (fastapi, uvicorn, google-genai, websockets) and import | ✅ Pass |
| 3 | Audio utils unit tests — PCM16 round-trip, clipping clamp, 16 kHz→24 kHz resample length, silence/loudness (RMS), chunking, and **audio passed as `str` is rejected with a clear error** (the classic `.encode()`-on-bytes bug cannot happen) | ✅ Pass |
| 4 | Error-mapping unit tests — auth / model / network / quota / session failures all map to the correct friendly message | ✅ Pass — **one real bug was found by this test and fixed** (a boolean sneaked into a match list in `errors.py`) |
| 5 | Server startup with **no API key** — starts, serves the UI at `/`, `/health` answers correctly | ✅ Pass |
| 6 | WebSocket connect — browser channel opens, initial status received, stray binary audio before session start is ignored safely | ✅ Pass |
| 7 | START with **no key** → UI receives the friendly key error (no crash, no traceback in the UI) | ✅ Pass |
| 8 | START with a **fake key** — the app really called Google, Google rejected the key, the app showed the friendly *"API key galat hai"* message **and kept running**; `/health` shows the key only as `<set, hidden>` | ✅ Pass (proves auth-error handling + no key leakage) |
| 9 | UI JavaScript syntax check (`node --check static/app.js`) | ✅ Pass |
| 10 | Duplicate-connection guard, interruption flush, auto-reconnect with session resumption, model fallback list | ⚠️ Implemented and code-reviewed, but a **live proof needs a real key + real mic** — see checklist below |

## ⏳ Verify once on YOUR Windows PC (needs your key + your mic)

These were **not** run here — a development VM has no Windows, no
microphone and (on purpose) none of your API keys:

1. `INSTALL.bat` and `START_MAYERA.bat` execution on Windows.
2. A real Gemini Live conversation: speak Hindi/Hinglish → hear MAYERA reply.
3. Voice quality and delay on your microphone/speakers.
4. Interruption: start talking while MAYERA is mid-sentence — she should stop.
5. Reconnection: during a call, switch Wi-Fi off for ~10 seconds and back on —
   MAYERA should reconnect and continue the same conversation.
6. Mic permission prompt in your browser.

### Your 5-minute checklist

1. Install Python 3.10+ from python.org (tick **Add python.exe to PATH**).
2. Double-click **INSTALL.bat** — wait for "Install ho gaya!".
3. Get a free key: [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
   → *Create API key* → copy it.
4. Double-click **START_MAYERA.bat** → paste the key (Ctrl+V) → Enter.
5. Browser opens → **START TALKING** → Allow mic → say:
   *"Namaste MAYERA, tum kaisi ho?"*
6. While she answers, start speaking over her — she should stop and listen.
7. (Optional) Toggle Wi-Fi off/on mid-call to see her reconnect.

If any step fails, note the exact message shown in the UI and the step
number — that is enough to diagnose it.

---

## Addendum — v1.1 (after first live run on the user's PC)

The first live run succeeded on the user's own Windows laptop with his
real API key: the terminal log showed `MAYERA connected hai` (Gemini Live
session established) and `MAYERA sun rahi hai` (listening). User feedback
asked for (a) better conversation quality with emotions, (b) a nicer UI.

v1.1 changes, verified here:
- New system instruction (emotional, curious, friend-like personality,
  deeper answers when asked) — config loads cleanly.
- VAD tuning added to the Live config (start HIGH / end LOW sensitivity,
  900 ms end-of-speech silence) and context-window compression —
  `LiveConnectConfig` constructs successfully with the installed SDK and
  reports the expected values.
- UI upgrade rendered and screenshot-verified in a real browser
  (starfield, halo, idle smile, glass status pill, animated START button).
- Live conversation quality with the new personality can only be judged
  on the user's PC with his key and mic — pending his feedback.

---

## Addendum — v2.0 (master-spec build)

Tested IN THIS ENVIRONMENT (automated, all passing):

- MemoryStore unit tests: add/list/delete-matching/clear, checkpoint
  save/load, settings round-trip and clamping, and secret refusal
  (passwords, Google-key-shaped strings, card numbers are NOT saved).
- ToolExecutor unit tests: remember -> saved; forget -> deleted count;
  get_current_time; open_website opens https URLs and rejects
  non-URL input (e.g. javascript:) - with a fake opener, no real
  browser was launched.
- ProactiveWatcher unit tests: quiet-hours math (incl. past-midnight
  wrap), inactivity threshold, no double-nudging, disabled setting,
  rotating check-in instructions that include the last topic.
- Session config: dynamic system instruction provably contains saved
  memories + checkpoint topic; Live config carries Google Search +
  the 4 function declarations, both transcriptions, and the no-tools
  fallback config builds cleanly.
- STOP command: 11 true cases trigger ("ruk jao", "Mayera stop",
  "stop talking"...), 7 look-alike sentences do NOT ("stop wali
  kahani sunao", "band kamra ki kahani..."). The first matcher version
  had a false positive here - found by test, fixed, re-tested.
- HTTP APIs on the running server: /health (memory fields), /api/memory
  (list/clear), /api/settings (read/update/restore) - all correct.
- UI v2 screenshot-verified: memory pill shows "Memory ON - 0",
  settings drawer renders with all controls and quiet-hours fields.

Still only testable on the user's PC (needs his key + mic): the spoken
quality of memory recall and emotional replies, a real proactive
check-in firing mid-silence, the spoken greeting/checkpoint restore,
tool calls spoken end-to-end (e.g. "YouTube kholo"), and the STOP
command against live transcription.

## Addendum — v2.1 (reply-speed fix)

User feedback: replies felt late. Main cause: the anti-interruption
tuning waited ~0.9 s of silence before MAYERA treated his turn as
finished. v2.1 adds a Reply Speed setting (Settings drawer):
  fast (new default) = 450 ms end-of-speech silence, HIGH end
  sensitivity; patient = the old 900 ms / LOW behaviour.
Verified here: Live config builds with exactly 450 ms/HIGH in fast
mode and 900 ms/LOW in patient mode; the setting round-trips through
/api/settings; the drawer serves the new control. Real-world reply
latency still also depends on the user's internet and Gemini itself.

## Addendum — v2.2 (NEON ORB theme, from the user's own reference image)

The user supplied a reference design (neon orb interface) and asked for
the same UI with the "AI" text removed from the orb's centre. Built as
a full new default theme (static/styles.css): swirling two-layer conic
plasma orb with an empty dark core, broken arc rings, JS-generated
dotted side waves, waveform strip (padded to 36 bars), circular call
controls (MUTE / big START / END), glowing floor ellipses and a neon
corner frame. The face markup remains in the page but is hidden by this
theme. Previous themes are kept in static/ as styles-classic.css (the
robotic face) and styles-aurora.css; switch by renaming one of them to
styles.css. Screenshot-verified idle + speaking states in a browser.
All v2.1 behaviour (memory, tools, proactive, reply speed) is unchanged.

## Addendum — v2.3 (latency, second pass)

User still reported late replies after v2.1. Root cause found by
reviewing the v2 changes: the Google Search grounding tool made the
model deliberate (and often actually search) before speaking on
ordinary turns. v2.3: search grounding is now OFF by default and
behind a Settings toggle ("Web search - jawab thoda slow hoga");
fast-mode end-of-speech silence cut 450 -> 350 ms; the system
instruction was tightened ~36% (2900 -> 1858 chars, same behaviours).
Verified here: default Live config carries only the 4 function tools
(no google_search) with 350 ms VAD; enabling the setting adds the
grounding tool back; /api/settings exposes web_search=0; the drawer
serves the new toggle. Real-world latency remains partly dependent on
the user's internet and Gemini's own first-audio time.

## Addendum — v2.4 (save the API key once, DPAPI-encrypted)

At the user's choice, the Gemini key is now saved on his PC in key.dat,
encrypted with Windows DPAPI (mayera/key_vault.py, ctypes/CryptProtect
Data): the blob is tied to his Windows account, is never plain text,
and cannot be decrypted on another PC/user. ensure_api_key() order:
environment -> saved vault -> one hidden prompt (which then saves).
KEY_CHANGE.bat deletes key.dat to forget/change the key.
Verified here (Linux): the vault fails soft off Windows; with a fake
DPAPI honouring the same contract, save->load round-trips, no part of
the key appears in key.dat, and corrupt or foreign blobs load as None
without crashing; the env->save->silent-load flow ran end to end.
Real DPAPI encryption itself can only execute on his Windows PC.

## Addendum — v2.5 (auto-update, public or private repo)

updater.py runs from START_MAYERA.bat before the server: it fetches
version.txt + manifest.txt from the user's own GitHub repo
(aihellping-del/mayera-ai), downloads the listed files to a temp dir
first and copies them over only on full success, writing version.txt
last. .venv, mayera_memory.db, key.dat and gh_token.dat are hard-
excluded; any failure prints one short line and startup continues.
Private repos are supported too: the updater sends a read-only GitHub
token from MAYERA_GH_TOKEN or from gh_token.dat (DPAPI-encrypted,
saved once via GITHUB_TOKEN.bat / github_token_setup.py); a public
repo needs no token. Verified here against a local auth-required
HTTP server: without a token the check fails soft and nothing
changes; with the token a fake v2.4 install updated itself to
v2.5.0, and the mayera_memory.db / key.dat / gh_token.dat sentinels
stayed byte-identical.
