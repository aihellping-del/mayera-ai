"""CRT - Candle Range Theory.

Price sweeps beyond the previous candle's high/low (liquidity
grab / range raid) then closes BACK INSIDE the previous range
with a rejection wick. Sweep of the LOW + close back inside in
the upper part = bullish CRT; sweep of the HIGH mirror = bearish.
Works on CLOSED candles only. Returns AnalysisResult.
"""
from __future__ import annotations

from typing import Optional

from ..models import AnalysisResult
from .candle_psychology import candle_psychology


def crt_event(prev, cur, symbol: str = "") -> Optional[AnalysisResult]:
    p_rng = prev.high - prev.low
    if p_rng <= 0:
        return None
    psych = candle_psychology(cur)
    if cur.low < prev.low and prev.low < cur.close <= prev.high:
        pos = (cur.close - prev.low) / p_rng
        sweep = (prev.low - cur.low) / p_rng
        if pos >= 0.5 and psych["lower_wick_ratio"] >= 0.15:
            strength = max(0.0, min(1.0, 0.45 + 0.3 * pos + 0.25 * min(sweep, 1.0)))
            return AnalysisResult(
                symbol=symbol, direction=1, score_component=strength * 2.0,
                name="crt_bullish_sweep", strength=round(strength, 3),
                reasons=["CRT bullish: price swept below the previous candle low "
                         "(liquidity grab) then closed back inside its range with "
                         "a rejection wick - sellers trapped, buyers reclaiming."])
    if cur.high > prev.high and prev.low <= cur.close < prev.high:
        pos = (prev.high - cur.close) / p_rng
        sweep = (cur.high - prev.high) / p_rng
        if pos >= 0.5 and psych["upper_wick_ratio"] >= 0.15:
            strength = max(0.0, min(1.0, 0.45 + 0.3 * pos + 0.25 * min(sweep, 1.0)))
            return AnalysisResult(
                symbol=symbol, direction=-1, score_component=-strength * 2.0,
                name="crt_bearish_sweep", strength=round(strength, 3),
                reasons=["CRT bearish: price swept above the previous candle high "
                         "(liquidity grab) then closed back inside its range with "
                         "a rejection wick - buyers trapped, sellers reclaiming."])
    return None


def analyse_crt(candles, symbol: str = "") -> Optional[AnalysisResult]:
    if len(candles) < 2:
        return None
    return crt_event(candles[-2], candles[-1], symbol=symbol)
