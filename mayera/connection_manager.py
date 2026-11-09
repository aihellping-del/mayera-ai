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

    async def register(self, websocket):
        """Make `websocket` the active client; close any previous one."""
        async with self._lock:
            old = self._ws
            self._ws = websocket
        if old is not None and old is not websocket:
            try:
                await old.close(code=1000, reason="Replaced by a new connection")
            except Exception:
                pass

    async def unregister(self, websocket):
        async with self._lock:
            if self._ws is websocket:
                self._ws = None

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
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send_bytes(pcm_bytes)
        except Exception:
            pass

    async def send_interrupted(self):
        await self.send_json({"type": "interrupted"})
