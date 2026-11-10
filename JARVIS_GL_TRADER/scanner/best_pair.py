"""Pair scanner + BEST PAIR selection."""
from __future__ import annotations

from .. import config
from ..engine import signal_engine


def scan_all(feed, candles_per_pair: int = 300, symbols=None) -> list:
    results = []
    for symbol in (symbols or config.PAIRS):
        try:
            candles = feed.get_candles(symbol, min(candles_per_pair,
                                                  config.MAX_CANDLES_PER_PAIR))
            try:
                m5 = feed.get_candles(symbol, 120, timeframe="M5")
            except Exception:
                m5 = None
            sig = signal_engine.analyse(symbol, candles, m5_candles=m5)
        except Exception as exc:
            results.append({"symbol": symbol, "signal": None,
                            "error": str(exc), "power": 0})
            continue
        results.append({
            "symbol": symbol,
            "signal": sig.to_dict() if sig else None,
            "power": sig.power_score if sig else 0,
            "price": candles[-1].close if candles else None,
        })
    results.sort(key=lambda r: r["power"], reverse=True)
    return results


def best_pair(results) -> dict:
    """Only a qualifying setup wins: power >= threshold, not Weak,
    decision CALL/PUT, volatility OK. Else None + honest reason."""
    for r in results:
        sig = r.get("signal")
        if not sig:
            continue
        if (sig["direction"] in ("CALL", "PUT")
                and sig["power_score"] >= config.MIN_POWER_FOR_BEST
                and sig["classification"] != "Weak"
                and sig.get("volatility_ok", True)):
            return {"best": r, "reason": "qualifying setup found"}
    return {"best": None, "reason": "no qualifying setup"}
