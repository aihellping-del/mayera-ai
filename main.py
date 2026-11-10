"""MAYERA AI - main server (v2).

Run it through START_MAYERA.bat (recommended) or directly:

    python main.py

Architecture:

    Browser mic --(WebSocket, PCM 16 kHz)--> this server
    this server --(Gemini Live API)--> Google Gemini
    Google Gemini --(PCM 24 kHz)--> this server --(WebSocket)--> speaker

v2 wiring:
  * MemoryStore (SQLite) - long-term memories, conversation checkpoint,
    settings. Injected into every Gemini session.
  * ToolExecutor - MAYERA's voice tools (remember / forget / time /
    open website), called through Gemini function calling.
  * ProactiveWatcher - while a session is live, MAYERA herself starts a
    gentle check-in when Golu is quiet for a while (settings + quiet
    hours respected).
  * Server-side transcription powers the STOP command and checkpoints.
    Transcripts are NEVER sent to the UI - the experience stays
    voice-only, exactly as designed.

The API key comes from the GEMINI_API_KEY environment variable only
(START_MAYERA.bat asks for it and keeps it in memory). It is never
written to disk, never printed in logs, never stored in memory DB.
"""

import asyncio
import getpass
import json
import logging
import os
import re
import signal
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import settings as config
from core.audio_utils import rms_level, should_forward_mic
from core.connection_manager import ConnectionManager
from core.errors import MayeraError, friendly_error
from core.gemini_live import GeminiLiveSession
from memory.memory_store import MemoryStore
from actions.pc_control import PcController
from core.proactive import ProactiveWatcher
from actions.screen_vision import ScreenVision
from actions.tools import ToolExecutor
from actions.youtube_play import YoutubePlayer

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "dashboard"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
)
log = logging.getLogger("jarvis")

manager = ConnectionManager()
# One START may build a session at a time (v3.7): a double START
# (double-click / app.js retry) must never create two Gemini
# sessions that then talk over each other.
start_lock = asyncio.Lock()
store = MemoryStore()
_pc = PcController()

# v3.17 (Mark LVI port): file kaam + the UI-issued confirmation
# gate. The gate's notify is attached below once `manager` exists;
# a trash_file call can only proceed on the user's own tap.
from actions.browser_agent import BrowserAgent  # noqa: E402
from actions.file_ops import FileOps  # noqa: E402
from core.confirm import ConfirmGate  # noqa: E402

confirm_gate = ConfirmGate()


async def _confirm_notify(cid, question):
    await manager.send_json(
        {"type": "confirm", "id": cid, "text": question})


confirm_gate.notify = _confirm_notify
tool_executor = ToolExecutor(
    store, pc=_pc, yt=YoutubePlayer(),
    vision=ScreenVision(pc=_pc),  # v3.12: JARVIS can actually SEE the screen
    files=FileOps(), confirm=confirm_gate,
    browser=BrowserAgent(),  # v3.20: JARVIS's own personal browser
)
watcher = ProactiveWatcher(store)

live_session: GeminiLiveSession | None = None
mic_muted = False

# v3.0 speed: the Gemini session is pre-warmed in the background as
# soon as the browser connects, so pressing START TALKING no longer
# waits for the whole connect. `in_call` is True only between START
# and END - it gates UI status announcements, the greeting and the
# proactive watcher, so a pre-warmed session stays silent until the
# user actually starts the call.
in_call = False
prewarm_task: asyncio.Task | None = None

# v3.0 response-time monitoring: felt latency per reply = the gap
# between Golu finishing speaking (last loud mic chunk) and the first
# reply audio arriving. Printed in the terminal, kept for /health.
latency_samples: list[float] = []

# v3.14 performance dashboard counters (shown in /health and in the
# Settings drawer's Diagnostics section).
audio_stats = {"mic_chunks_received": 0, "interruptions": 0,
               "mic_chunks_gated": 0}
client_playback: dict = {}


def _record_latency(seconds: float, end_wait=None):
    latency_samples.append(seconds)
    if len(latency_samples) > 50:
        del latency_samples[:-50]
    avg = sum(latency_samples) / len(latency_samples)
    # v3.22: the second number is the honest wait - from the moment
    # he had clearly STOPPED speaking (the 0.6 s-of-quiet mark,
    # voice_state['speech_end']) to the first reply sound. (v3.19's
    # 'mic band' segment used the last chunk of ANY kind, but the
    # mic streams silence chunks continuously, so it always read
    # ~0.03 s - his 2026-11-10 screenshot proved it useless.)
    seg = (f", chup -> jawab: {end_wait:.2f}s"
           if end_wait is not None else "")
    print(f"  [latency] Jawab ka pehla sound: {seconds:.2f}s{seg} "
          f"(average {avg:.2f}s, {len(latency_samples)} replies)",
          flush=True)


# Consecutive duplicate statuses are not re-sent: the AI-audio path
# used to send one JSON status per audio chunk (many per second),
# which wasted socket and browser work on every single reply.
_last_ui_status = {"key": None}


async def send_ui_status(state: str, message: str = ""):
    key = (state, message)
    if _last_ui_status["key"] == key:
        return
    _last_ui_status["key"] = key
    await manager.send_status(state, message)


# voice-activity state (drives 'thinking' face + proactive timing)
voice_state = {"last_voice": 0.0, "last_ai": 0.0, "talking": False,
               "thinking_sent": False, "awaiting_reply": False,
               "last_chunk": 0.0, "speech_end": 0.0}

# ---------------------------------------------------------------------------
# Mood memory (v3.2): MAYERA "samajhti" hai - she notices how Golu
# sounded and carries it into the NEXT conversation, where the system
# instruction gently reminds her ("pichhli baar wo udaas tha, pehle
# pyar se haal puchhna"). Simple keyword scoring on the server-side
# transcription; only a clear signal is stored, neutral talk changes
# nothing.
# ---------------------------------------------------------------------------
_MOOD_SAD = ("udaas", "dukh", "pareshan", "pareshaan", "thak gaya",
             "thak gya", "thaka hua", "akela", "akele", "rona",
             "tension", "chinta", "bura lag", "mann nahi", "man nahi",
             "neend nahi", "beemar", "bimar", "dard", "mushkil",
             "gussa", "naraz", "naaraaz", "bor ho raha")
_MOOD_HAPPY = ("khush", "maza aa", "mazaa", "badhiya", "bahut acha",
               "bahut achha", "mast", "happy", "kamaal", "jeet gaya",
               "pass ho gaya", "bahut khush")


def detect_mood(text: str):
    """'udaas' / 'khush' / None from one transcribed user turn."""
    t = " " + (text or "").lower() + " "
    sad = sum(1 for w in _MOOD_SAD if w in t)
    happy = sum(1 for w in _MOOD_HAPPY if w in t)
    if sad > happy:
        return "udaas"
    if happy > sad:
        return "khush"
    return None


STOP_SINGLE = {"stop", "chup", "cancel"}           # must be the whole command
STOP_PHRASES = (                                     # may lead a short command
    "stop talking", "stop karo", "ruk jao", "ruk ja", "chup karo",
    "chup ho jao", "band karo", "bas karo", "cancel karo",
)
_FILLER_PREFIXES = ("mayera", "jarvis", "hey", "please", "ab", "tum")


def is_stop_command(text: str) -> bool:
    """True only when the user is clearly TELLING Mayera to stop -
    not when 'stop'/'ruk' merely appears inside a longer sentence
    (e.g. 'stop wali kahani mat sunao' must NOT trigger)."""
    words = re.sub(r"[^a-z ]", " ", (text or "").lower()).split()
    while words and words[0] in _FILLER_PREFIXES:
        words.pop(0)
    while words and words[-1] in ("please", "mayera", "jarvis"):
        words.pop()
    cmd = " ".join(words)
    if not cmd or len(cmd) > 40:
        return False
    if cmd in STOP_SINGLE:
        return True
    return any(cmd == p or cmd.startswith(p + " ") for p in STOP_PHRASES)


# ---------------------------------------------------------------------------
# Gemini callbacks -> browser / brain
# ---------------------------------------------------------------------------
async def on_ai_audio(pcm_bytes: bytes):
    now = time.monotonic()
    if voice_state["awaiting_reply"]:
        # First reply audio after Golu finished speaking: this gap is
        # the latency he actually feels. Measure it, once per turn.
        voice_state["awaiting_reply"] = False
        end_wait = (now - voice_state["speech_end"]
                    if voice_state.get("speech_end") else None)
        _record_latency(now - voice_state["last_voice"], end_wait)
    voice_state["last_ai"] = now
    voice_state["thinking_sent"] = False
    watcher.mark_activity()
    await manager.send_audio(pcm_bytes)
    await send_ui_status("speaking", "JARVIS bol raha hai...")


async def on_status(state: str, message: str):
    log.info("status: %s - %s", state, message)
    if not in_call:
        # Pre-warmed session connecting/reconnecting in the
        # background: stay silent until the user presses START.
        return
    await send_ui_status(state, message)


async def on_interrupted():
    audio_stats["interruptions"] += 1
    await manager.send_interrupted()


async def on_user_text(text: str):
    """Server-side only: STOP command + activity tracking + mood."""
    watcher.mark_activity()
    mood = detect_mood(text)
    if mood:
        try:
            store.set_setting("last_mood", mood)
            store.set_setting("last_mood_at", str(int(time.time())))
        except Exception:  # noqa: BLE001 - mood is a bonus, never fatal
            pass
    if is_stop_command(text):
        log.info("STOP command heard - flushing playback.")
        await manager.send_interrupted()
        await send_ui_status("listening", "JARVIS sun raha hai...")


async def on_ai_text(text: str):
    watcher.mark_activity()


# ---------------------------------------------------------------------------
# Background watchdog: 'thinking' face + proactive check-ins
# ---------------------------------------------------------------------------
async def watchdog():
    while True:
        await asyncio.sleep(0.3)
        session = live_session
        if session is None or not session.is_connected or not in_call:
            continue
        now = time.monotonic()
        # user just finished speaking, MAYERA has not answered yet
        # v3.0.1 fix: v3.0 flipped "talking" off at 0.6 s, so the old
        # condition (talking AND >0.8 s) could never fire and the
        # 'thinking' face never appeared. "awaiting_reply" is the exact
        # state for this: he finished a turn, no reply audio yet - and
        # unlike a bare not-talking check it can never fire while
        # MAYERA is simply idle after a finished reply.
        if (voice_state["awaiting_reply"]
                and now - voice_state["last_voice"] > 0.8
                and now - voice_state["last_ai"] > 1.5
                and not voice_state["thinking_sent"]):
            voice_state["thinking_sent"] = True
            await send_ui_status("thinking", "JARVIS soch raha hai...")
        # Dead-session detector (v3.7): he finished speaking 25s ago
        # and not a sound came back. A healthy session NEVER takes
        # this long (his worst real tool turn was ~13s); the socket
        # has died silently, so reconnect instead of waiting forever.
        # awaiting_reply is cleared so this fires once per stuck turn.
        if (voice_state["awaiting_reply"]
                and now - voice_state["last_voice"] > 25):
            voice_state["awaiting_reply"] = False
            print("  [stuck] 25s se koi jawab nahi aaya - "
                  "connection dead lagta hai", flush=True)
            session.force_reconnect("25s se koi jawab nahi")
        # due reminders (v3.17): spoken once, then marked done.
        # Checked on wall-clock time, independent of the proactive
        # check-in's silence rules - a reminder is a promise.
        for _rem in store.due_reminders(time.time()):
            store.mark_reminder_done(_rem["id"])
            print(f"  [reminder] {_rem['text']}", flush=True)
            await session.nudge(
                "REMINDER ka samay ho gaya hai. Golu ko abhi ye yaad "
                f"dilao, ek chhoti line me: \"{_rem['text']}\". "
                "Bas itna hi bolo, aur kuch mat jodo.")
        # proactive check-in
        if watcher.should_nudge():
            cp = store.get_checkpoint() if store.memory_enabled() else None
            topic = (session.last_user_text
                     or (cp or {}).get("topic", ""))
            await session.nudge(watcher.next_instruction(topic))
            watcher.mark_nudged()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
def _install_global_ptt(loop):
    """Windows-global Push-to-Talk (v3.15): while the Push-to-Talk
    setting is ON, holding Ctrl+Space ANYWHERE in Windows tells the
    browser page 'mic open', releasing it closes the mic - the
    `keyboard` package hears the keys, the page does the gating.
    Soft-fails like the stop hotkey when unavailable."""
    try:
        import keyboard
    except Exception:  # noqa: BLE001 - optional dependency
        return
    state = {"held": False}

    def _send(active):
        if store.get_setting("push_to_talk", "0") != "1":
            return
        asyncio.run_coroutine_threadsafe(
            manager.send_json({"type": "ptt", "active": active}), loop)

    def _press(_event):
        if not state["held"] and keyboard.is_pressed("ctrl"):
            state["held"] = True
            _send(True)

    def _release(_event):
        if state["held"]:
            state["held"] = False
            _send(False)

    try:
        keyboard.on_press_key("space", _press)
        keyboard.on_release_key("space", _release)
        print("  Push-to-Talk taiyaar hai (Settings me ON karne par "
              "Ctrl+Space se chalega).")
    except Exception:  # noqa: BLE001
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("JARVIS server ready at http://%s:%s", config.HOST, config.PORT)
    task = asyncio.create_task(watchdog())
    _install_global_ptt(asyncio.get_running_loop())
    yield
    task.cancel()
    global live_session
    if live_session is not None:
        await live_session.stop()
        live_session = None


app = FastAPI(title="JARVIS AI", lifespan=lifespan)


@app.middleware("http")
async def _no_cache(request, call_next):
    # After every auto-update the browser must load the FRESH page -
    # a cached old page once kept showing the old name/design (v3.5).
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response
import ui as ui_mod  # noqa: E402

ui_mod.mount_dashboard(app)


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
async def health():
    return {
        "ok": True,
        "gemini_connected": bool(live_session and live_session.is_connected),
        "api_key": config.mask_key(config.get_api_key()),
        "memory_enabled": store.memory_enabled(),
        "memories": store.count_memories(),
        "proactive_enabled": store.proactive_enabled(),
        "connection_state": (live_session.state
                             if live_session is not None
                             else "DISCONNECTED"),
        "reconnect_count": (live_session.reconnect_count
                            if live_session is not None else 0),
        "last_reconnect_s": (live_session.last_reconnect_seconds
                             if live_session is not None else None),
        "last_reply_latency_s": (round(latency_samples[-1], 2)
                                 if latency_samples else None),
        "avg_reply_latency_s": (round(sum(latency_samples)
                                      / len(latency_samples), 2)
                                if latency_samples else None),
        "replies_measured": len(latency_samples),
        "audio": {
            "mic_chunks_received": audio_stats["mic_chunks_received"],
            "ai_chunks_sent": manager.audio_sent,
            "ai_chunks_dropped_queue": manager.audio_dropped,
            "interruptions": audio_stats["interruptions"],
        },
        "tools": _tool_stats(),
        "client_playback": dict(client_playback),
    }


def _tool_stats():
    if live_session is None:
        return {"calls": 0, "deduped": 0, "last_seconds": None,
                "avg_seconds": None}
    ts = live_session.tool_stats
    avg = (round(ts["total_seconds"] / ts["calls"], 2)
           if ts["calls"] else None)
    return {"calls": ts["calls"], "deduped": ts["deduped"],
            "last_seconds": ts["last_seconds"], "avg_seconds": avg}


# ---------------------------------------------------------------------------
# Memory + settings APIs (used by the Settings panel; local only)
# ---------------------------------------------------------------------------
@app.get("/api/memory")
async def api_memory():
    return {
        "enabled": store.memory_enabled(),
        "count": store.count_memories(),
        "items": store.list_memories(limit=100),
        "checkpoint": store.get_checkpoint(),
    }


@app.delete("/api/memory/{memory_id}")
async def api_memory_delete(memory_id: int):
    return {"deleted": store.delete_memory(memory_id)}


@app.post("/api/memory/clear")
async def api_memory_clear():
    store.clear_checkpoint()
    return {"cleared": store.clear_memories()}


@app.get("/api/settings")
async def api_settings_get():
    return store.all_settings()


@app.post("/api/settings")
async def api_settings_post(payload: dict):
    allowed = {"memory_enabled", "proactive_enabled", "inactivity_seconds",
               "quiet_start", "quiet_end", "reply_speed", "web_search",
               "push_to_talk"}
    for key, value in (payload or {}).items():
        if key in allowed:
            store.set_setting(key, value)
    return store.all_settings()


@app.post("/api/confirm")
async def api_confirm(payload: dict):
    """The user's tap on the Haan/Nahi card (v3.17): this - and only
    this - can approve a gated action like trash_file."""
    cid = str((payload or {}).get("id", ""))
    approved = bool((payload or {}).get("approved"))
    return {"resolved": confirm_gate.resolve(cid, approved)}


@app.post("/api/exit")
async def api_exit():
    def _bye():
        os.kill(os.getpid(), signal.SIGINT)

    threading.Timer(0.6, _bye).start()
    return {"bye": True}


# ---------------------------------------------------------------------------
# Session construction + background pre-warming (v3.0)
# ---------------------------------------------------------------------------
def _build_session() -> GeminiLiveSession:
    return GeminiLiveSession(
        api_key=config.get_api_key(),
        on_audio=on_ai_audio,
        on_status=on_status,
        on_interrupted=on_interrupted,
        store=store,
        tool_executor=tool_executor,
        on_user_text=on_user_text,
        on_ai_text=on_ai_text,
    )


async def _prewarm():
    """Connect to Gemini in the background, before START is pressed,
    so the first reply has no connect wait at all. Silent by design:
    no greeting and no UI status until the call actually starts."""
    global live_session, prewarm_task
    try:
        session = _build_session()
        await session.start(greet=False)
        live_session = session
        print("  [speed] Gemini session pehle se taiyaar hai - "
              "START dabate hi baat shuru hogi.", flush=True)
    except Exception as exc:  # noqa: BLE001
        log.info("Prewarm nahi ho paya (%s); START par connect hoga.",
                 exc.__class__.__name__)
        live_session = None
    finally:
        prewarm_task = None


# ---------------------------------------------------------------------------
# WebSocket: the voice channel
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global live_session, mic_muted, in_call, prewarm_task
    await ws.accept()
    await manager.register(ws)
    await send_ui_status("idle", "Connected. START TALKING dabayein.")
    log.info("Browser connected.")
    if live_session is None and prewarm_task is None \
            and config.get_api_key():
        prewarm_task = asyncio.create_task(_prewarm())

    try:
        while True:
            message = await ws.receive()

            # --- binary = microphone audio -------------------------------
            if message.get("bytes") is not None:
                chunk = message["bytes"]
                audio_stats["mic_chunks_received"] += 1
                voice_state["last_chunk"] = time.monotonic()
                level = rms_level(chunk)
                if level > 0.03:
                    now = time.monotonic()
                    # New speech cancels any pending reply measurement:
                    # he was not finished after all.
                    voice_state["awaiting_reply"] = False
                    if not voice_state["talking"]:
                        voice_state["talking"] = True
                        if live_session is not None:
                            await send_ui_status(
                                "listening", "JARVIS sun raha hai...")
                    voice_state["last_voice"] = now
                    watcher.mark_activity()
                elif voice_state["talking"] and \
                        time.monotonic() - voice_state["last_voice"] > 0.6:
                    # He finished speaking: the next AI audio is timed
                    # against last_voice (latency monitoring, v3.0).
                    voice_state["talking"] = False
                    voice_state["awaiting_reply"] = True
                    voice_state["speech_end"] = time.monotonic()
                if live_session is not None and not mic_muted:
                    # v3.23 noise gate: while JARVIS himself is
                    # speaking, quiet background sounds no longer
                    # reach Gemini (they were cutting him off
                    # mid-sentence); only clearly loud speech -
                    # a real barge-in - gets through.
                    if should_forward_mic(level, voice_state["last_ai"],
                                          time.monotonic()):
                        await live_session.send_audio(chunk)
                    else:
                        audio_stats["mic_chunks_gated"] += 1
                continue

            # --- text = control messages ---------------------------------
            text = message.get("text")
            if not text:
                continue
            try:
                control = json.loads(text)
            except json.JSONDecodeError:
                continue

            ctype = control.get("type")

            if ctype == "start":
                if start_lock.locked():
                    continue  # a START is already being handled
                async with start_lock:
                    in_call = True
                    # Fresh call, fresh voice state (v3.0.1): no stale
                    # 'thinking'/latency state may leak across calls.
                    voice_state.update({
                        "talking": False, "thinking_sent": False,
                        "last_voice": 0.0, "last_ai": 0.0,
                        "awaiting_reply": False})
                    # v3.0 warm path: a pre-warmed session is already
                    # connected, so START is instant - just greet + listen.
                    if live_session is not None and live_session.is_connected:
                        mic_muted = False
                        watcher.reset()
                        voice_state["awaiting_reply"] = False
                        await send_ui_status(
                            "listening", "JARVIS sun raha hai... boliye!")
                        await live_session.greet()
                        continue
                    # Pre-warm still running: wait for it, then go warm.
                    if prewarm_task is not None:
                        await send_ui_status(
                            "connecting", "Gemini se connect ho raha hai...")
                        try:
                            await asyncio.shield(prewarm_task)
                        except Exception:  # noqa: BLE001
                            pass
                        if live_session is not None \
                                and live_session.is_connected:
                            mic_muted = False
                            watcher.reset()
                            voice_state["awaiting_reply"] = False
                            await send_ui_status(
                                "listening", "JARVIS sun raha hai... boliye!")
                            await live_session.greet()
                            continue
                    # Cold path (same as before v3.0): connect now.
                    await send_ui_status(
                        "connecting", "Gemini se connect ho raha hai...")
                    try:
                        if live_session is not None:
                            try:
                                await live_session.stop()
                            except Exception:  # noqa: BLE001
                                pass
                            live_session = None
                        live_session = _build_session()
                        await live_session.start()
                        mic_muted = False
                        watcher.reset()
                        await send_ui_status(
                            "listening", "JARVIS sun raha hai... boliye!")
                    except MayeraError as err:
                        live_session = None
                        in_call = False
                        await send_ui_status("error", err.message)
                    except Exception as exc:  # noqa: BLE001
                        live_session = None
                        in_call = False
                        _, friendly = friendly_error(exc)
                        await send_ui_status("error", friendly)

            elif ctype == "stop":
                in_call = False
                voice_state["awaiting_reply"] = False
                if live_session is not None:
                    await live_session.stop()
                    live_session = None
                await send_ui_status("idle", "Call khatm. Phir milenge!")

            elif ctype == "mute":
                mic_muted = bool(control.get("muted", False))
                await send_ui_status(
                    "muted" if mic_muted else "listening",
                    "Mic band hai." if mic_muted else "JARVIS sun raha hai...",
                )

            elif ctype == "ping":
                await manager.send_json({"type": "pong"})

            elif ctype == "stats":
                # Browser playback counters for the dashboard (v3.14).
                pb = control.get("playback")
                if isinstance(pb, dict):
                    client_playback.update(pb)

    except WebSocketDisconnect:
        log.info("Browser disconnected.")
    except Exception as exc:  # noqa: BLE001
        # Starlette raises a DIFFERENT class, WebSocketDisconnected
        # (a RuntimeError), when code touches a socket the browser
        # already closed - a normal tab-close race, not a fault.
        # It used to land here and look like an error in his log.
        if exc.__class__.__name__ in ("WebSocketDisconnected",
                                      "ClientDisconnected"):
            log.info("Browser disconnected.")
        else:
            log.warning("WebSocket error: %s: %s",
                        exc.__class__.__name__, exc)
    finally:
        await manager.unregister(ws)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def ensure_api_key():
    from providers import key_vault

    # 1) key already in the environment (e.g. set by hand) -> use it,
    #    and remember it on this PC if the vault is still empty.
    key = config.get_api_key()
    if key:
        log.info("Gemini API key: %s", config.mask_key(key))
        if key_vault.vault_available() and not key_vault.has_saved_key():
            if key_vault.save_key(key):
                print("  Note: Key is PC par surakshit (encrypted) save "
                      "ho gayi hai - agli baar nahi dalna padega.")
        return

    # 2) key saved on this PC (DPAPI-encrypted) -> use it silently.
    saved = key_vault.load_key()
    if saved:
        os.environ["GEMINI_API_KEY"] = saved
        log.info("Gemini API key: %s (saved on this PC)",
                 config.mask_key(saved))
        print("  Save ki hui key mil gayi - is baar key nahi dalna padega.")
        return

    # 3) first time -> ask once, then save it encrypted on this PC.
    #    Preferred: the friendly pop-up box (ordinary paste works there;
    #    the black console window swallows Ctrl+V, which confused the
    #    user). Any GUI failure falls back to the console prompt below.
    try:
        from providers.key_prompt_gui import ask_key_gui
        gui_key = ask_key_gui()
    except Exception:  # noqa: BLE001
        gui_key = None
    if gui_key:
        os.environ["GEMINI_API_KEY"] = gui_key
        log.info("Gemini API key: %s", config.mask_key(gui_key))
        if key_vault.save_key(gui_key):
            print("  Key save ho gayi (encrypted). Badalna ho to "
                  "KEY_CHANGE.bat chalana.")
        return
    if sys.stdin and sys.stdin.isatty():
        print()
        print("  JARVIS ko Gemini API key chahiye (Google AI Studio se free milti hai).")
        print("  Key yaha chipi hui rahegi - type/paste karke Enter dabayein.")
        print("  Ye key is PC par encrypted save ho jayegi - dobara nahi dalna padega.")
        key = getpass.getpass("  Gemini API Key: ").strip()
        if key:
            os.environ["GEMINI_API_KEY"] = key
            log.info("Gemini API key: %s", config.mask_key(key))
            if key_vault.save_key(key):
                print("  Key save ho gayi (encrypted). Badalna ho to "
                      "KEY_CHANGE.bat chalana.")
            return
    log.warning(
        "GEMINI_API_KEY set nahi hai. Server chalega, lekin START TALKING "
        "dabane par key ki error dikhegi. Behtar: START_MAYERA.bat use karein."
    )


def _install_stop_hotkey():
    """Global Ctrl+Shift+Q = JARVIS ko turant band karo (v3.13,
    user's spec). Uses the `keyboard` package when installed; any
    failure (not installed, no permission) is soft - the Settings
    exit button and Ctrl+C keep working exactly as before."""
    try:
        import keyboard
    except Exception:  # noqa: BLE001 - optional dependency
        print("  Note: 'keyboard' package nahi mila - Ctrl+Shift+Q "
              "hotkey band rahegi, Ctrl+C se band hoga.")
        return

    def _stop():
        print("\n  Ctrl+Shift+Q dabaya gaya - JARVIS band ho raha hai.")
        os.kill(os.getpid(), signal.SIGINT)

    try:
        keyboard.add_hotkey("ctrl+shift+q", _stop)
        print("  Emergency stop: Ctrl+Shift+Q (kahin se bhi dabao, "
              "JARVIS turant band).")
    except Exception:  # noqa: BLE001 - e.g. needs admin on some PCs
        print("  Note: Ctrl+Shift+Q hotkey register nahi ho payi "
              "(terminal ko Administrator se chalakar dekho).")


def main():
    ensure_api_key()
    _install_stop_hotkey()
    url = f"http://{config.HOST}:{config.PORT}"
    if os.environ.get("MAYERA_NO_BROWSER") != "1":
        ui_mod.open_ui_later(url)
    print()
    print("  ============================================")
    print("   JARVIS AI - Voice Companion")
    print(f"   Khul raha hai: {url}")
    print("   Band karne ke liye: Ctrl+C")
    print("  ============================================")
    print()
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
