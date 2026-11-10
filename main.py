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

from mayera import config
from mayera.audio_utils import rms_level
from mayera.connection_manager import ConnectionManager
from mayera.errors import MayeraError, friendly_error
from mayera.gemini_live import GeminiLiveSession
from mayera.memory_store import MemoryStore
from mayera.proactive import ProactiveWatcher
from mayera.tools import ToolExecutor

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
)
log = logging.getLogger("mayera")

manager = ConnectionManager()
store = MemoryStore()
tool_executor = ToolExecutor(store)
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


def _record_latency(seconds: float):
    latency_samples.append(seconds)
    if len(latency_samples) > 50:
        del latency_samples[:-50]
    avg = sum(latency_samples) / len(latency_samples)
    print(f"  [latency] Jawab ka pehla sound: {seconds:.2f}s "
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
               "thinking_sent": False, "awaiting_reply": False}

STOP_SINGLE = {"stop", "chup"}                      # must be the whole command
STOP_PHRASES = (                                     # may lead a short command
    "stop talking", "stop karo", "ruk jao", "ruk ja", "chup karo",
    "chup ho jao", "band karo", "bas karo",
)
_FILLER_PREFIXES = ("mayera", "hey", "please", "ab", "tum")


def is_stop_command(text: str) -> bool:
    """True only when the user is clearly TELLING Mayera to stop -
    not when 'stop'/'ruk' merely appears inside a longer sentence
    (e.g. 'stop wali kahani mat sunao' must NOT trigger)."""
    words = re.sub(r"[^a-z ]", " ", (text or "").lower()).split()
    while words and words[0] in _FILLER_PREFIXES:
        words.pop(0)
    while words and words[-1] in ("please", "mayera"):
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
        _record_latency(now - voice_state["last_voice"])
    voice_state["last_ai"] = now
    voice_state["thinking_sent"] = False
    watcher.mark_activity()
    await manager.send_audio(pcm_bytes)
    await send_ui_status("speaking", "MAYERA bol rahi hai...")


async def on_status(state: str, message: str):
    log.info("status: %s - %s", state, message)
    if not in_call:
        # Pre-warmed session connecting/reconnecting in the
        # background: stay silent until the user presses START.
        return
    await send_ui_status(state, message)


async def on_interrupted():
    await manager.send_interrupted()


async def on_user_text(text: str):
    """Server-side only: STOP command + activity tracking."""
    watcher.mark_activity()
    if is_stop_command(text):
        log.info("STOP command heard - flushing playback.")
        await manager.send_interrupted()
        await send_ui_status("listening", "MAYERA sun rahi hai...")


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
        if (voice_state["talking"] and now - voice_state["last_voice"] > 0.8
                and now - voice_state["last_ai"] > 1.5
                and not voice_state["thinking_sent"]):
            voice_state["thinking_sent"] = True
            await send_ui_status("thinking", "MAYERA soch rahi hai...")
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
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("MAYERA server ready at http://%s:%s", config.HOST, config.PORT)
    task = asyncio.create_task(watchdog())
    yield
    task.cancel()
    global live_session
    if live_session is not None:
        await live_session.stop()
        live_session = None


app = FastAPI(title="MAYERA AI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
        "last_reply_latency_s": (round(latency_samples[-1], 2)
                                 if latency_samples else None),
        "avg_reply_latency_s": (round(sum(latency_samples)
                                      / len(latency_samples), 2)
                                if latency_samples else None),
        "replies_measured": len(latency_samples),
    }


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
               "quiet_start", "quiet_end", "reply_speed", "web_search"}
    for key, value in (payload or {}).items():
        if key in allowed:
            store.set_setting(key, value)
    return store.all_settings()


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
                if rms_level(chunk) > 0.03:
                    now = time.monotonic()
                    # New speech cancels any pending reply measurement:
                    # he was not finished after all.
                    voice_state["awaiting_reply"] = False
                    if not voice_state["talking"]:
                        voice_state["talking"] = True
                        if live_session is not None:
                            await send_ui_status(
                                "listening", "MAYERA sun rahi hai...")
                    voice_state["last_voice"] = now
                    watcher.mark_activity()
                elif voice_state["talking"] and \
                        time.monotonic() - voice_state["last_voice"] > 0.6:
                    # He finished speaking: the next AI audio is timed
                    # against last_voice (latency monitoring, v3.0).
                    voice_state["talking"] = False
                    voice_state["awaiting_reply"] = True
                if live_session is not None and not mic_muted:
                    await live_session.send_audio(chunk)
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
                in_call = True
                # v3.0 warm path: a pre-warmed session is already
                # connected, so START is instant - just greet + listen.
                if live_session is not None and live_session.is_connected:
                    mic_muted = False
                    watcher.reset()
                    voice_state["awaiting_reply"] = False
                    await send_ui_status(
                        "listening", "MAYERA sun rahi hai... boliye!")
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
                            "listening", "MAYERA sun rahi hai... boliye!")
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
                        "listening", "MAYERA sun rahi hai... boliye!")
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
                    "Mic band hai." if mic_muted else "MAYERA sun rahi hai...",
                )

            elif ctype == "ping":
                await manager.send_json({"type": "pong"})

    except WebSocketDisconnect:
        log.info("Browser disconnected.")
    except Exception as exc:  # noqa: BLE001
        log.warning("WebSocket error: %s", exc.__class__.__name__)
    finally:
        await manager.unregister(ws)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def ensure_api_key():
    from mayera import key_vault

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
        from mayera.key_prompt_gui import ask_key_gui
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
        print("  MAYERA ko Gemini API key chahiye (Google AI Studio se free milti hai).")
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


def main():
    ensure_api_key()
    url = f"http://{config.HOST}:{config.PORT}"
    if os.environ.get("MAYERA_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print()
    print("  ============================================")
    print("   MAYERA AI - Voice Companion")
    print(f"   Khul raha hai: {url}")
    print("   Band karne ke liye: Ctrl+C")
    print("  ============================================")
    print()
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
