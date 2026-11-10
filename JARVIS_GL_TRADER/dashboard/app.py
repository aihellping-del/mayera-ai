"""FastAPI dashboard app for JARVIS GL TRADER (port from config)."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from .. import config
from .websocket import WSManager, broadcast_loop

TEMPLATE = Path(__file__).parent / "templates" / "index.html"


def create_app(controller) -> FastAPI:
    app = FastAPI(title="JARVIS GL TRADER - Research Only")
    manager = WSManager()
    app.state.controller = controller
    app.state.manager = manager

    @app.on_event("startup")
    async def _startup():
        app.state.task = asyncio.create_task(
            broadcast_loop(manager, controller))

    @app.on_event("shutdown")
    async def _shutdown():
        task = getattr(app.state, "task", None)
        if task:
            task.cancel()

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return TEMPLATE.read_text(encoding="utf-8")

    @app.get("/api/status")
    async def status():
        return controller.status()

    @app.get("/api/scan")
    async def scan():
        return controller.scan_once()

    @app.get("/api/candles/{symbol}")
    async def candles(symbol: str, count: int = 200):
        symbol = symbol.upper()
        if symbol not in config.PAIRS:
            return JSONResponse({"error": "unknown pair"}, status_code=404)
        cs = controller.feed.get_candles(symbol, min(count, 500))
        return {"symbol": symbol,
                "candles": [{"time": c.time, "open": c.open, "high": c.high,
                             "low": c.low, "close": c.close}
                            for c in cs]}

    @app.get("/api/history")
    async def history(n: int = 50):
        return {"history": controller.history.get_recent(n)}

    @app.get("/api/paper/stats")
    async def paper_stats():
        return controller.paper.stats()

    @app.post("/api/paper/reset")
    async def paper_reset():
        controller.paper.reset()
        return controller.paper.stats()

    @app.get("/api/backtest/{symbol}")
    async def backtest(symbol: str, candles: int = 1500):
        return controller.backtest(symbol, candles=candles)

    @app.post("/api/control")
    async def control(req: Request):
        body = await req.json()
        action = (body or {}).get("action")
        if action == "start":
            return controller.start()
        if action == "stop":
            return controller.stop()
        return JSONResponse({"error": "action must be start|stop"},
                            status_code=400)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(ws)
        except Exception:
            manager.disconnect(ws)

    return app
