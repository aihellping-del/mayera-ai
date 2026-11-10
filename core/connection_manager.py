"""MAYERA - WebSocket connection manager.

Exactly one browser client may be connected at a time. If a second tab
connects, the old one is closed - this prevents the classic bug of two
sockets fighting over one Gemini session and echoing audio.
"""

import asyncio
import json


class ConnectionManager:
    def __init__(self):
        self._ws = None
        self._lock = asyncio.Lock()
        # Decoupled audio sending (v3.14): AI audio goes into a queue
        # and a dedicated sender task writes it to the socket. The
        # Gemini receive loop used to await every socket send itself -
        # any browser/network hiccup stalled the loop, so Gemini's
        # chunks bunched up and then burst, which the user heard as
        # random pauses mid-sentence.
        self._audio_queue = None
        self._sender_task = None
        self.audio_dropped = 0   # chunks dropped by the overflow guard
        self.audio_sent = 0      # chunks actually written to the socket

    @property
    def active_sessions(self):
        """1 while the HUD client is connected, else 0 (v3.32 -
        this manager is single-client by design; see docstring)."""
        return 1 if self._ws is not None else 0

    async def register(self, websocket):
        """Make `websocket` the active client; close any previous one."""
        async with self._lock:
            old = self._ws
            self._ws = websocket
            self._stop_sender_locked()
            self._audio_queue = asyncio.Queue(maxsize=300)
            self._sender_task = asyncio.create_task(
                self._sender_loop(websocket, self._audio_queue))
        if old is not None and old is not websocket:
            try:
                await old.close(code=1000, reason="Replaced by a new connection")
            except Exception:
                pass

    def _stop_sender_locked(self):
        if self._sender_task is not None:
            self._sender_task.cancel()
            self._sender_task = None
        self._audio_queue = None

    async def _sender_loop(self, ws, queue):
        try:
            while True:
                data = await queue.get()
                try:
                    await ws.send_bytes(data)
                    self.audio_sent += 1
                except Exception:
                    # Client went away; register/unregister cleans up.
                    return
        except asyncio.CancelledError:
            raise

    async def unregister(self, websocket):
        async with self._lock:
            if self._ws is websocket:
                self._ws = None
                self._stop_sender_locked()

    @property
    def active(self):
        return self._ws

    async def send_json(self, payload):
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            # Client went away mid-send; the receive loop will clean up.
            pass

    async def send_status(self, state, message=""):
        await self.send_json({"type": "status", "state": state, "message": message})

    async def send_audio(self, pcm_bytes):
        """Non-blocking: enqueue for the sender task and return at
        once, so the Gemini receive loop never waits on the browser.
        Overflow policy: drop the OLDEST queued chunk (stale audio is
        worse than a tiny skip) and count it for the dashboard."""
        queue = self._audio_queue
        if queue is None:
            ws = self._ws
            if ws is None:
                return
            try:
                await ws.send_bytes(pcm_bytes)
                self.audio_sent += 1
            except Exception:
                pass
            return
        if queue.full():
            try:
                queue.get_nowait()
                self.audio_dropped += 1
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(pcm_bytes)

    async def send_interrupted(self):
        await self.send_json({"type": "interrupted"})
