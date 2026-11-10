"""WebSocket manager + broadcast loop for the GL Trader dashboard."""
from __future__ import annotations

import asyncio
import json


class WSManager:
    def __init__(self):
        self.clients: set = set()
        self._seen_signals: set = set()

    async def connect(self, ws):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws):
        self.clients.discard(ws)

    async def broadcast(self, payload: dict):
        dead = []
        text = json.dumps(payload)
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


async def broadcast_loop(manager: WSManager, controller, interval: float = 5.0):
    """Every ~interval: push scan + best + paper stats; push a
    NEW_SIGNAL event only once per (symbol, time, direction)."""
    while True:
        try:
            if controller.running:
                data = controller.scan_once()
                await manager.broadcast({"type": "scan", **data})
                best = data.get("best") or {}
                sig = (best.get("signal") or {}) if best else {}
                if sig.get("direction") in ("CALL", "PUT"):
                    key = (sig["symbol"], sig["time"], sig["direction"])
                    if key not in manager._seen_signals:
                        manager._seen_signals.add(key)
                        await manager.broadcast(
                            {"type": "NEW_SIGNAL", "signal": sig})
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)
