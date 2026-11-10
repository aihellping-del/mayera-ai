"""JARVIS GL TRADER - CENTRAL CONTROLLER (single entry point).

Run from repo root:  python -m JARVIS_GL_TRADER.main
Initializes in order: (1) feed, (2) candle analysis, (3) CRT,
(4) candle psychology, (5) indicators, (6) BEST PAIR scanner,
(7) signal engine, (8) backtesting engine, (9) FastAPI dashboard,
(10) JARVIS integration. TraderController is the single source of
truth used by BOTH dashboard controls and JARVIS integration.

RESEARCH ONLY - paper trading, no real-money execution anywhere.
"""
from __future__ import annotations

import threading

from . import config
from .data.mt5_feed import get_feed
from .engine.backtesting import run_backtest
from .engine.history import SignalHistory
from .engine.paper import PaperTrader
from .scanner.best_pair import best_pair, scan_all

_controller = None
_lock = threading.Lock()


class TraderController:
    def __init__(self, feed=None):
        # (1) feed: MT5 live if available, else DEMO synthetic
        self.feed = feed or get_feed(prefer_mt5=True)
        # (2)-(5) strategies are pure functions (strategies/*) - wired
        # through the signal engine; nothing stateful to construct.
        # (6) scanner + (7) signal engine are function modules.
        # (8) backtesting engine = engine.backtesting.run_backtest
        self.history = SignalHistory()
        self.paper = PaperTrader()
        self.running = False
        self._last_scan = None
        self._backtest_cache = {}
        self._seen = set()

    # -- lifecycle ------------------------------------------------------
    def start(self):
        self.running = True
        return self.status()

    def stop(self):
        self.running = False
        return self.status()

    def status(self):
        return {"running": self.running,
                "feed_source": self.feed.source,
                "is_live": bool(getattr(self.feed, "is_live", False)),
                "disclaimer": config.DISCLAIMER,
                "paper": self.paper.stats()}

    # -- core scan --------------------------------------------------------
    def scan_once(self):
        results = scan_all(self.feed)
        best = best_pair(results)
        best_entry = best["best"]
        if best_entry and best_entry.get("signal"):
            sig = best_entry["signal"]
            key = (sig["symbol"], sig["time"], sig["direction"])
            if key not in self._seen:
                self._seen.add(key)
                self.history.add(sig)
                self.paper.place(sig)
        try:
            if isinstance(self.feed.source, str) and "DEMO" in self.feed.source:
                self.feed.tick(best_entry["symbol"] if best_entry else "EURUSD")
            self.paper.settle_due(self.feed)
        except Exception:
            pass
        data = {"scan": results,
                "best": best_entry,
                "best_reason": best["reason"],
                "paper_stats": self.paper.stats(),
                "feed_source": self.feed.source}
        self._last_scan = data
        return data

    def best_signal(self):
        data = self._last_scan or self.scan_once()
        return data.get("best")

    def backtest(self, symbol: str = "all", candles: int = 1500):
        key = (symbol, candles)
        if key not in self._backtest_cache:
            syms = None if symbol == "all" else [symbol.upper()]
            self._backtest_cache[key] = run_backtest(
                self.feed, symbols=syms, candles=candles)
        return self._backtest_cache[key]


def get_controller() -> TraderController:
    global _controller
    with _lock:
        if _controller is None:
            _controller = TraderController()
        return _controller


def main():
    # (9) dashboard + (10) integration both use get_controller().
    import uvicorn
    from .dashboard.app import create_app
    app = create_app(get_controller())
    print(f"JARVIS GL TRADER on http://{config.HOST}:{config.PORT} "
          f"(feed: {get_controller().feed.source}) - RESEARCH ONLY")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
