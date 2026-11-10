"""MAYERA - Gemini Live session (v2).

One class owns the whole Gemini Live connection:

    browser mic --> main.py --> GeminiLiveSession --> Gemini Live API
    browser speaker <-- main.py <-- GeminiLiveSession <-- Gemini Live API

v2 responsibilities (on top of v1 streaming/reconnect):
  * the system instruction is built dynamically: base personality +
    long-term memories + last conversation checkpoint
  * tools: Google Search grounding + function calling (remember,
    forget, time, open website) executed locally via ToolExecutor
  * input/output transcription runs SERVER-SIDE ONLY: it powers the
    memory tools, the STOP command and the conversation checkpoint.
    Nothing textual is ever shown in the voice-only UI.
  * a spoken greeting on connect when a previous conversation exists
  * proactive nudges: send a hidden instruction turn and MAYERA starts
    talking herself (used by the ProactiveWatcher)

Audio is bytes end to end. Nothing is ever .encode()d here.
"""

import asyncio
import platform
import random
import re
import time
from pathlib import Path

from google import genai
from google.genai import types

from . import config, tools as tools_mod
from .audio_utils import ensure_bytes
from .errors import MayeraError, friendly_error

_LONG_ABSENCE_SECONDS = 6 * 3600  # >6h away -> "welcome back" greeting

# Reasoning stays private (v3.15, user's feature list): some models /
# servers pass the model's inner reasoning through as ordinary
# content inside <think>...</think>. Without a filter that text would
# be treated as JARVIS's spoken answer - and it would also land in
# the conversation checkpoint and pollute every later session's
# context. Strip it wherever model text is consumed.
_THINK_SPAN = re.compile(r"<think>.*?</think>", re.S | re.I)
_THINK_OPEN = re.compile(r"<think>.*$", re.S | re.I)


def strip_think(text):
    """Remove <think>...</think> reasoning from model text."""
    if not text:
        return ""
    cleaned = _THINK_SPAN.sub("", text)
    cleaned = _THINK_OPEN.sub("", cleaned)  # unclosed tag: drop the tail
    return cleaned.strip()


class GeminiLiveSession:
    def __init__(self, api_key, on_audio, on_status, on_interrupted,
                 store=None, tool_executor=None,
                 on_user_text=None, on_ai_text=None):
        self._api_key = api_key
        self._on_audio = on_audio
        self._on_status = on_status
        self._on_interrupted = on_interrupted
        self._store = store
        self._tools = tool_executor
        self._on_user_text = on_user_text    # async fn(str) - server-side only
        self._on_ai_text = on_ai_text        # async fn(str) - server-side only
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(api_version="v1beta"),
        )
        self._session = None
        self._ctx = None
        self._recv_task = None
        self._reconnect_task = None
        self._send_lock = asyncio.Lock()
        # Connection state machine (v3.7, spec B): DISCONNECTED ->
        # CONNECTING -> CONNECTED -> RECONNECTING -> CONNECTED ...,
        # ERROR when reconnects are exhausted. Shown in /health.
        self.state = "DISCONNECTED"
        self.reconnect_count = 0
        self.last_reconnect_seconds = None
        self._last_msg_at = 0.0    # last message FROM Gemini
        self._last_tool_at = 0.0   # last tool execution (stuck guard)
        self._send_failed = False  # a send failed on a "live" session
        # Tool responses that could not be delivered because the
        # connection dropped mid-tool-call (v3.13, user's spec):
        # queued here and flushed on the (re)connected session, so a
        # finished action (e.g. text already typed) is never reported
        # lost and the model never hangs waiting for a result.
        self._pending_tool_responses = []
        self._tool_tasks = set()       # background tool batches (v3.14)
        self._tool_lock = asyncio.Lock()  # batches never overlap
        self.tool_stats = {"calls": 0, "deduped": 0,
                           "total_seconds": 0.0, "last_seconds": None}
        self._reconnect_started = 0.0
        self._stopped = True
        self._resumption_handle = None
        self._model_in_use = None
        self._tools_active = True
        # transcript accumulators (checkpoint + command detection)
        self._in_buf = ""
        self._out_buf = ""
        self.last_user_text = ""
        self.last_ai_text = ""

    # ------------------------------------------------------------------
    # dynamic instruction: personality + memory
    # ------------------------------------------------------------------
    def _system_instruction(self):
        text = config.SYSTEM_INSTRUCTION
        if self._store is not None and self._store.memory_enabled():
            memories = self._store.list_memories(limit=30)
            if memories:
                lines = "\n".join("- " + m["content"] for m in memories)
                text += (
                    "\n\nGOLU KE BAARE ME TUMHARI YAADEIN (swabhavik roop "
                    "se istemal karo, ginwao mat):\n"
                    + lines
                )
            # Mood memory (v3.2): how he sounded last time, if recent,
            # so she opens with care instead of a blank slate.
            mood = self._store.get_setting("last_mood", "")
            try:
                mood_age = time.time() - float(
                    self._store.get_setting("last_mood_at", "0"))
            except (TypeError, ValueError):
                mood_age = 1e18
            if mood in ("udaas", "khush") and mood_age < 48 * 3600:
                label = ("thoda udaas/pareshan" if mood == "udaas"
                         else "khush aur energetic")
                text += (
                    "\n\nPICHHLI BAAT KA HAAL: Golu pichhli baar "
                    f"{label} mehsoos kar raha tha. Aaj baat ki "
                    "shuruaat me pyar se uska haal puchhna aur usi "
                    "ehsaas ko dhyaan me rakhkar baat karna."
                )
            cp = self._store.get_checkpoint()
            if cp and cp.get("topic"):
                text += (
                    "\n\nPICHHLI BAATCHEET: Aakhri baar tum is vishay par "
                    f"baat kar rahe the: \"{cp['topic']}\". Mauka mile to "
                    "wahi se swabhavik roop se jodo."
                )
        text += "\n\n" + self._self_knowledge()
        return text

    @staticmethod
    def _self_knowledge():
        """Runtime self-knowledge (v3.15): generated fresh from the
        live system every session - rename JARVIS, add a plugin or
        run a new version and this block already knows. Includes his
        hard limits, so he answers 'tum ye kar sakte ho?' honestly."""
        try:
            version = (Path(__file__).resolve().parent.parent
                       / "version.txt").read_text().strip()
        except Exception:  # noqa: BLE001
            version = "?"
        try:
            names = [d.name for d in tools_mod.function_declarations()]
        except Exception:  # noqa: BLE001
            names = []
        return (
            "APNE BAARE ME (runtime sach, is session ke liye): Tum "
            f"JARVIS ho, version {version}, is samay "
            f"{platform.system()} computer par chal rahe ho. Tumhare "
            f"paas ye tools hain: {', '.join(names)}. Tum ye NAHI kar "
            "sakte - inke tools hi nahi hain: file delete karna, "
            "email/message bhejna, payment, shutdown/restart. Agar "
            "Golu inme se kuch maange to jhoothi haan mat bolo - "
            "pehle confirmation wala niyam yaad karo aur sach batao "
            "ki ye abhi tumhare bas me nahi hai. Apni andar ki soch "
            "(reasoning) kabhi bolo ya dikhao mat - sirf final jawab "
            "do."
        )

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def start(self, greet=True):
        if not self._api_key:
            raise MayeraError(
                "auth_error",
                "Gemini API key nahi mili. START_MAYERA.bat se chalakar "
                "key daalein.",
            )
        self._stopped = False
        await self._connect_with_fallback()
        if greet:
            await self._maybe_greet()

    async def greet(self):
        """The spoken greeting, deferred: pre-warmed sessions connect
        silently in the background (v3.0) and greet only when the user
        actually presses START TALKING."""
        await self._maybe_greet()

    async def stop(self):
        self._stopped = True
        self.state = "DISCONNECTED"
        self._save_checkpoint()
        for _task in list(self._tool_tasks):
            _task.cancel()
        self._tool_tasks.clear()
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        if self._recv_task is not None:
            self._recv_task.cancel()
            self._recv_task = None
        await self._close_session()

    @property
    def is_connected(self):
        return self._session is not None

    def _save_checkpoint(self):
        if self._store is None or not self._store.memory_enabled():
            return
        topic = (self.last_user_text or self.last_ai_text or "").strip()
        if topic:
            self._store.save_checkpoint(
                topic=topic[:300],
                last_user=self.last_user_text[:300],
                last_ai=self.last_ai_text[:300],
            )

    # ------------------------------------------------------------------
    # greeting (spoken by MAYERA herself, in context)
    # ------------------------------------------------------------------
    async def _maybe_greet(self):
        if self._store is None:
            return
        cp = self._store.get_checkpoint() if self._store.memory_enabled() else None
        if not cp or not cp.get("topic"):
            return
        away = time.time() - float(cp.get("ended_at") or time.time())
        if away >= _LONG_ABSENCE_SECONDS:
            note = (
                "[System note - do not read this aloud: Golu has returned "
                "after a long time. Greet him with a warm welcome-back in "
                f"one or two sentences. Your last conversation was about: "
                f"\"{cp['topic']}\". Mention it lightly and ask how he is.]"
            )
        else:
            note = (
                "[System note - do not read this aloud: Golu just "
                "reconnected. Greet him warmly and briefly in one "
                "sentence, like continuing an ongoing friendship. "
                "Do NOT repeat anything you said before the "
                "disconnect - after this one line, stay silent and "
                "listen.]"
            )
        await self._send_instruction_turn(note)

    async def nudge(self, instruction):
        """Proactive check-in: MAYERA starts talking on her own."""
        if self._session is not None and not self._stopped:
            await self._send_instruction_turn(instruction)

    async def _send_instruction_turn(self, text):
        session = self._session
        if session is None:
            return
        try:
            if hasattr(session, "send_client_content"):
                turn = types.Content(
                    role="user", parts=[types.Part(text=text)]
                )
                await session.send_client_content(turns=turn, turn_complete=True)
            else:
                await session.send(input=text, end_of_turn=True)
        except Exception:
            pass  # a failed greeting/nudge must never kill the session

    # ------------------------------------------------------------------
    # connection management
    # ------------------------------------------------------------------
    def _vad_settings(self):
        """Reply-speed tuning, chosen in Settings.

        fast    -> she answers quickly after you stop (~0.35 s pause)
        patient -> she waits longer (~0.9 s) so she never cuts you off
        """
        speed = "fast"
        if self._store is not None:
            speed = self._store.get_setting("reply_speed", "fast")
        if speed == "patient":
            return (types.EndSensitivity.END_SENSITIVITY_LOW, 300, 900)
        return (types.EndSensitivity.END_SENSITIVITY_HIGH, 120, 250)

    def _web_search_enabled(self):
        return (self._store is not None
                and self._store.get_setting("web_search", "0") == "1")

    def _live_config(self, with_tools=True, fast_thinking=True):
        tool_list = None
        if with_tools:
            tool_list = [
                types.Tool(
                    function_declarations=tools_mod.function_declarations()
                ),
            ]
            # Google Search grounding is OFF by default: with it on, the
            # model deliberates (and often searches) before speaking,
            # which made every reply feel late. The user can switch it
            # on in Settings when fresh facts matter more than speed.
            if self._web_search_enabled():
                tool_list.insert(0, types.Tool(
                    google_search=types.GoogleSearch()))
        end_sens, prefix_ms, silence_ms = self._vad_settings()
        # Fast thinking (v2.8): the user's log showed 'thought' parts
        # in the model's responses - it was silently deliberating
        # before speaking, which feels nothing like ChatGPT's instant
        # voice replies. thinking_budget=0 turns that pre-thinking
        # off. If a model rejects this config, _try_models retries
        # with fast_thinking=False (the old behaviour) automatically.
        thinking = (types.ThinkingConfig(thinking_budget=0)
                    if fast_thinking else None)
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            thinking_config=thinking,
            system_instruction=self._system_instruction(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=(
                        types.StartSensitivity.START_SENSITIVITY_HIGH
                    ),
                    end_of_speech_sensitivity=end_sens,
                    prefix_padding_ms=prefix_ms,
                    silence_duration_ms=silence_ms,
                )
            ),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=tool_list,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=config.VOICE_NAME
                    )
                ),
                language_code=config.LANGUAGE_CODE,
            ),
            session_resumption=types.SessionResumptionConfig(
                handle=self._resumption_handle
            ),
        )

    async def _open(self, model, with_tools, fast_thinking=True):
        ctx = self._client.aio.live.connect(
            model=model,
            config=self._live_config(with_tools=with_tools,
                                     fast_thinking=fast_thinking)
        )
        session = await ctx.__aenter__()
        self._ctx = ctx
        self._session = session
        self._model_in_use = model
        self._tools_active = with_tools

    async def _close_session(self):
        ctx, self._ctx = self._ctx, None
        self._session = None
        if ctx is not None:
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass

    def _ordered_candidates(self):
        """Model candidates, last successful model first.

        The user's log (2026-11-10) showed ~35 s from START TALKING to
        'connected': dead/slow candidates were being tried in a fixed
        order every single time. Remembering which model actually
        worked makes later connects a single quick attempt.
        """
        models = config.get_model_candidates()
        if self._store is not None:
            try:
                last = self._store.get_setting("last_model", "")
            except Exception:  # noqa: BLE001
                last = ""
            if last and last in models:
                models = [last] + [m for m in models if m != last]
        return models

    async def _try_models(self, attempt_timeout=None):
        """Try models fast-first: tools+no-thinking, then no-tools,
        then the same again with thinking left on (old behaviour) as
        a last resort. True if connected."""
        timeout = attempt_timeout or config.CONNECT_TIMEOUT_SECONDS
        combos = ((True, True), (False, True), (True, False),
                  (False, False))
        for with_tools, fast_thinking in combos:
            for model in self._ordered_candidates():
                started = time.monotonic()
                try:
                    await asyncio.wait_for(
                        self._open(model, with_tools, fast_thinking),
                        timeout=timeout)
                except Exception as exc:  # noqa: BLE001
                    elapsed = time.monotonic() - started
                    print(f"  [connect] {model} nahi chala "
                          f"({elapsed:.1f}s) - agla try...",
                          flush=True)
                    try:
                        await self._close_session()
                    except Exception:  # noqa: BLE001
                        pass
                    code, message = friendly_error(exc)
                    if code in ("auth_error", "quota_error"):
                        raise MayeraError(code, message) from exc
                    continue
                elapsed = time.monotonic() - started
                print(f"  [connect] Model jud gaya: {model} "
                      f"({elapsed:.1f}s)", flush=True)
                if self._store is not None:
                    try:
                        self._store.set_setting("last_model", model)
                    except Exception:  # noqa: BLE001
                        pass
                return True
        return False

    async def _connect_with_fallback(self):
        self.state = "CONNECTING"
        if not await self._try_models():
            self.state = "ERROR"
            raise MayeraError(
                "network_error",
                "Gemini se connect nahi ho paya. Internet check karke "
                "dobara try karein.",
            )
        self.state = "CONNECTED"
        self._send_failed = False
        await self._on_status("connected", "JARVIS connected hai.")
        self._recv_task = asyncio.create_task(self._receive_loop())
        await self._flush_pending_tool_responses()

    def _schedule_reconnect(self):
        """The ONE owner of reconnection (v3.6 fix).

        A drop can announce itself three ways at nearly the same
        moment - a go_away warning, a receive error, and the receive
        stream simply ending. Before this fix each one spawned its
        own reconnect, and the parallel reconnects kept closing each
        other's brand-new sessions: the UI said "reconnecting"
        forever and JARVIS never actually came back.
        """
        if self._stopped:
            return
        task = self._reconnect_task
        if task is not None and not task.done():
            return
        if self.state in ("CONNECTED", "CONNECTING"):
            self.state = "RECONNECTING"
        self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self):
        # Nothing inside a reconnect may ever kill the app or die
        # silently (v3.7): the worst case is an honest ERROR status.
        try:
            await self._reconnect_inner()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"  [reconnect] unexpected error: "
                  f"{exc.__class__.__name__}: {exc}", flush=True)
            self.state = "ERROR"
            try:
                await self._on_status(
                    "error",
                    "Reconnect me gadbad ho gayi. START TALKING dobara "
                    "dabayein.")
            except Exception:  # noqa: BLE001
                pass

    async def _reconnect_inner(self):
        self._reconnect_started = time.monotonic()
        # Take over cleanly first: stop the old receive loop before
        # touching the session, so two loops never fight over one
        # connection.
        recv = self._recv_task
        if recv is not None and not recv.done():
            recv.cancel()
            try:
                await recv
            except BaseException:  # noqa: BLE001 - old loop is done either way
                pass
        if self._recv_task is recv:
            self._recv_task = None
        if self._stopped:
            return
        delay = config.RECONNECT_BASE_DELAY
        for attempt in range(1, config.MAX_RECONNECT_ATTEMPTS + 1):
            if self._stopped:
                return
            await self._on_status(
                "reconnecting",
                f"Connection toot gaya. Dobara try {attempt}/"
                f"{config.MAX_RECONNECT_ATTEMPTS}...",
            )
            await self._close_session()
            try:
                # Reconnects are mid-conversation: a hanging candidate
                # gets 4s, not 10s (v3.7) - that wait WAS the 13s+
                # reply delay in the user's log.
                ok = await self._try_models(
                    attempt_timeout=config.RECONNECT_ATTEMPT_TIMEOUT)
            except MayeraError as err:
                self.state = "ERROR"
                await self._on_status("error", err.message)
                return
            if ok and self._session is not None:
                if self._stopped:
                    await self._close_session()
                    return
                self.state = "CONNECTED"
                self._send_failed = False
                self.reconnect_count += 1
                self.last_reconnect_seconds = round(
                    time.monotonic() - self._reconnect_started, 1)
                print(f"  [reconnect] judne me kul "
                      f"{self.last_reconnect_seconds:.1f}s laga "
                      f"(reconnect #{self.reconnect_count})", flush=True)
                await self._on_status("connected", "JARVIS phir se connected hai.")
                self._recv_task = asyncio.create_task(self._receive_loop())
                await self._flush_pending_tool_responses()
                return
            if self._resumption_handle:
                # A stale resumption handle can make every attempt
                # fail while a FRESH connect would succeed (v3.7).
                # Drop it once and continue with plain connects.
                print("  [reconnect] purana session handle kaam nahi "
                      "kar raha - fresh connect try kar raha hu",
                      flush=True)
                self._resumption_handle = None
            # Exponential backoff WITH jitter (v3.7): fixed delays
            # make repeated retries collide with the same network
            # moment; jitter spreads them. No sleep after the FINAL
            # attempt - the ERROR should surface at once.
            if attempt < config.MAX_RECONNECT_ATTEMPTS:
                await asyncio.sleep(delay * random.uniform(0.75, 1.25))
                delay *= 2
        self.state = "ERROR"
        await self._on_status(
            "error",
            "Baar-baar connect fail ho raha hai. Internet check karke "
            "START TALKING dobara dabayein.",
        )

    def force_reconnect(self, reason=""):
        """Reconnect NOW because the session looks dead although no
        error surfaced (called by main.py's watchdog when a reply is
        25s overdue). Refuses while a tool just ran - that turn may
        still be finishing legitimately."""
        if self._stopped or self._session is None:
            return
        if self.state != "CONNECTED":
            return
        if time.monotonic() - self._last_tool_at < 15:
            return
        print(f"  [stuck] {reason} - session dead lagta hai, "
              f"reconnect kar raha hu", flush=True)
        self._schedule_reconnect()

    # ------------------------------------------------------------------
    # sending microphone audio
    # ------------------------------------------------------------------
    async def send_audio(self, pcm_bytes):
        session = self._session
        if session is None or self._stopped:
            return
        pcm_bytes = ensure_bytes(pcm_bytes, "microphone audio")
        blob = types.Blob(
            data=pcm_bytes,
            mime_type=f"audio/pcm;rate={config.INPUT_SAMPLE_RATE}",
        )
        async with self._send_lock:
            try:
                if hasattr(session, "send_realtime_input"):
                    await session.send_realtime_input(audio=blob)
                else:
                    await session.send(input=blob, end_of_turn=False)
            except Exception:
                # A failed send on a session we believe is CONNECTED
                # means the socket died silently (half-open: no error
                # will ever arrive on the receive side). Detect it
                # here instead of swallowing it (v3.7) - once per
                # episode, and the single reconnect owner dedupes.
                if self.state == "CONNECTED" and not self._send_failed:
                    self._send_failed = True
                    print("  [net] Gemini ko audio nahi bhej paya - "
                          "connection dead lagta hai, reconnect kar "
                          "raha hu", flush=True)
                    self._schedule_reconnect()

    # ------------------------------------------------------------------
    # receiving: audio + transcription + tool calls
    # ------------------------------------------------------------------
    async def _receive_loop(self):
        # Bound to ONE session instance: if the session is replaced
        # (reconnect) or the app stops, this loop simply exits.
        session = self._session
        empty_fast = 0
        try:
            while not self._stopped and self._session is session:
                run_started = time.monotonic()
                got = 0
                async for response in session.receive():
                    if self._stopped or self._session is not session:
                        return
                    got += 1
                    self._last_msg_at = time.monotonic()
                    await self._handle_response(response)
                # receive() ending is NORMAL, not a disconnect: the
                # google-genai SDK ends receive() when a TURN
                # completes (live.py receive(): "if
                # _is_interaction_complete(...): yield; break").
                # v3.6 wrongly treated every turn-end as a dead
                # session and reconnected - his 2026-11-10 log shows
                # 7 reconnects in 2 minutes, right after replies and
                # tool calls, and the model repeated itself on every
                # resume ("ek baat 2 bar bolta hai"). So: loop around
                # and listen for the next turn on the SAME session.
                if got:
                    empty_fast = 0
                    continue
                # A run with NO messages at all is the suspicious
                # one: a truly dead session's receive() comes back
                # instantly-empty forever (the original v3.6 hang,
                # where JARVIS looked connected but was not). Three
                # fast empty runs in a row = really gone: reconnect.
                if time.monotonic() - run_started < 0.5:
                    empty_fast += 1
                    if empty_fast >= 3:
                        break
                    await asyncio.sleep(0.1)
                else:
                    empty_fast = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._stopped or self._session is not session:
                return
            code, message = friendly_error(exc)
            if code == "auth_error":
                await self._on_status("error", message)
                return
        if not self._stopped and self._session is session:
            self._schedule_reconnect()

    async def _handle_response(self, response):
        # --- tool calls (MAYERA wants to act) ---
        tool_call = getattr(response, "tool_call", None)
        if tool_call is not None and getattr(tool_call, "function_calls", None):
            # v3.14: tools run as a BACKGROUND task. Awaiting them
            # here used to freeze the whole receive loop for the
            # tool's full duration (a 5 s screen look stalled audio,
            # transcription, interruption and go_away handling alike).
            self._spawn_tool_calls(tool_call.function_calls)

        sc = getattr(response, "server_content", None)

        # --- transcriptions (server-side only: memory + STOP command) ---
        if sc is not None:
            in_tr = getattr(sc, "input_transcription", None)
            if in_tr is not None and getattr(in_tr, "text", None):
                self._in_buf += in_tr.text
            out_tr = getattr(sc, "output_transcription", None)
            if out_tr is not None and getattr(out_tr, "text", None):
                self._out_buf += out_tr.text
            if getattr(sc, "turn_complete", False):
                await self._flush_turn()

        # --- AI audio ---
        data = getattr(response, "data", None)
        if data:
            await self._on_audio(ensure_bytes(data, "AI audio"))

        # --- interruption ---
        if sc is not None and getattr(sc, "interrupted", False):
            self._out_buf = ""
            await self._on_interrupted()
            await self._on_status("listening", "JARVIS sun raha hai...")
            return

        # --- session resumption bookkeeping ---
        update = getattr(response, "session_resumption_update", None)
        if update is not None and getattr(update, "resumable", False):
            handle = getattr(update, "new_handle", None)
            if handle:
                self._resumption_handle = handle

        if getattr(response, "go_away", None) is not None and not self._stopped:
            self._schedule_reconnect()

    async def _flush_turn(self):
        if self._in_buf.strip():
            self.last_user_text = self._in_buf.strip()
            if self._on_user_text is not None:
                await self._on_user_text(self.last_user_text)
        ai_text = strip_think(self._out_buf)
        if ai_text:
            self.last_ai_text = ai_text
            if self._on_ai_text is not None:
                await self._on_ai_text(self.last_ai_text)
        self._in_buf = ""
        self._out_buf = ""

    # Tools that only read the world or touch independent state -
    # safe to run concurrently inside one batch (v3.14). Everything
    # that drives the PC/mouse/screen/YouTube stays sequential and in
    # order: open_app -> type_text must never race each other.
    _PARALLEL_SAFE = frozenset(
        {"get_current_time", "youtube_search", "remember_this",
         "forget_memory"})

    # Heavy tools get an instant visible acknowledgment (v3.15) so a
    # long task never starts in silence: the UI status flips to a
    # "working" line at once, and the instruction tells JARVIS to
    # speak a one-line filler before heavy tools too.
    _ACK_LABELS = {
        "look_at_screen": "Screen dekh raha hai...",
        "youtube_search": "YouTube par dhoondh raha hai...",
        "youtube_play": "Video laga raha hai...",
        "open_app": "App khol raha hai...",
        "take_screenshot": "Screenshot le raha hai...",
    }

    def _spawn_tool_calls(self, function_calls):
        if self._tools is None:
            return
        for _call in function_calls:
            _label = self._ACK_LABELS.get(getattr(_call, "name", ""))
            if _label:
                asyncio.create_task(self._on_status("thinking", _label))
                break
        task = asyncio.create_task(self._handle_tool_calls(function_calls))
        self._tool_tasks.add(task)

        def _done(done_task):
            self._tool_tasks.discard(done_task)
            if not done_task.cancelled() and done_task.exception() is not None:
                print(f"  [tool] background batch me gadbad: "
                      f"{done_task.exception().__class__.__name__}",
                      flush=True)

        task.add_done_callback(_done)

    async def _run_one_tool(self, call, args):
        _args_short = str(args)
        if len(_args_short) > 120:
            _args_short = _args_short[:120] + "..."
        print(f"  [tool] {call.name} called with {_args_short}",
              flush=True)
        _t0 = time.monotonic()
        try:
            result = await self._tools.execute(call.name, args)
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            result = {"status": "error",
                      "message": exc.__class__.__name__}
        _dt = time.monotonic() - _t0
        self._last_tool_at = time.monotonic()
        self.tool_stats["calls"] += 1
        self.tool_stats["total_seconds"] += _dt
        self.tool_stats["last_seconds"] = round(_dt, 2)
        _status = (result or {}).get("status", "?")
        print(f"  [tool] {call.name} -> {_status} ({_dt:.1f}s)",
              flush=True)
        if _status == "typed":
            print(f"  [tool] type_text typed "
                  f"{(result or {}).get('chars', 0)} chars", flush=True)
        if _status == "error":
            print(f"  [tool] error: {call.name}: "
                  f"{(result or {}).get('message', '')}", flush=True)
        return result

    async def _handle_tool_calls(self, function_calls):
        if self._tools is None:
            return
        # Batches are background tasks, but two batches still never
        # run at once: PC state must change one batch at a time.
        async with self._tool_lock:
            self._last_tool_at = time.monotonic()
            calls = [(call, dict(call.args or {})) for call in function_calls]
            results = [None] * len(calls)
            # Deduplicate identical calls in the batch (the model
            # occasionally asks for the same thing twice in one turn):
            # execute once, reuse the result for every copy.
            unique = {}
            for idx, (call, args) in enumerate(calls):
                key = (call.name, repr(sorted(args.items())))
                unique.setdefault(key, []).append(idx)
            if len(unique) < len(calls):
                self.tool_stats["deduped"] += len(calls) - len(unique)
                print(f"  [tool] duplicate call(s) deduped: "
                      f"{len(calls) - len(unique)}", flush=True)
            reps = [(key, idxs[0]) for key, idxs in unique.items()]
            parallel = [(key, i) for key, i in reps
                        if calls[i][0].name in self._PARALLEL_SAFE]
            sequential = [(key, i) for key, i in reps
                          if calls[i][0].name not in self._PARALLEL_SAFE]
            if len(parallel) > 1:
                got = await asyncio.gather(
                    *(self._run_one_tool(calls[i][0], calls[i][1])
                      for _key, i in parallel))
                for (key, _i), result in zip(parallel, got):
                    for idx in unique[key]:
                        results[idx] = result
            else:
                sequential = parallel + sequential
            for key, i in sequential:
                result = await self._run_one_tool(calls[i][0], calls[i][1])
                for idx in unique[key]:
                    results[idx] = result
            responses = []
            for (call, _args), result in zip(calls, results):
                kwargs = {"name": call.name, "response": result}
                if getattr(call, "id", None):
                    kwargs["id"] = call.id
                responses.append(types.FunctionResponse(**kwargs))
            await self._deliver_tool_responses(responses)

    async def _deliver_tool_responses(self, responses):
        """Send tool results back to the model - ALWAYS (v3.13). If
        the connection dropped while the tool was running, the send
        fails here: queue the responses instead of dropping them,
        and flush them on the next (re)connected session, so the
        model never hangs and never falsely says 'done'."""
        if not responses:
            return
        session = self._session
        if session is None:
            self._pending_tool_responses.extend(responses)
            print(f"  [tool] {len(responses)} tool result(s) queue "
                  f"kiye - connection nahi hai, reconnect par bhejunga",
                  flush=True)
            return
        try:
            await session.send_tool_response(
                function_responses=responses
            )
        except Exception:
            self._pending_tool_responses.extend(responses)
            print(f"  [tool] {len(responses)} tool result(s) bhej "
                  f"nahi paya - queue kiye, reconnect par bhejunga",
                  flush=True)

    async def _flush_pending_tool_responses(self):
        """Deliver queued tool results on the fresh session."""
        if not self._pending_tool_responses or self._session is None:
            return
        pending, self._pending_tool_responses = (
            self._pending_tool_responses, [])
        try:
            await self._session.send_tool_response(
                function_responses=pending
            )
            print(f"  [tool] queue wale {len(pending)} tool result(s) "
                  f"reconnect ke baad bhej diye", flush=True)
        except Exception:
            self._pending_tool_responses = pending + self._pending_tool_responses
            print("  [tool] queue flush phir fail - result rakhe hain, "
                  "agle reconnect par try hoga", flush=True)
