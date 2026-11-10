"""Candle psychology + double-candle patterns (CLOSED candles)."""
from __future__ import annotations

from typing import Optional

from ..models import AnalysisResult


def candle_psychology(c) -> dict:
    rng = c.high - c.low
    if rng <= 0:
        return {"type": "flat", "body_pct": 0.0, "upper_wick_ratio": 0.0,
                "lower_wick_ratio": 0.0, "direction": 0,
                "explanation": "Flat candle, no range."}
    body = abs(c.close - c.open)
    upper = c.high - max(c.open, c.close)
    lower = min(c.open, c.close) - c.low
    body_pct, uw, lw = body / rng, upper / rng, lower / rng
    direction = 1 if c.close > c.open else (-1 if c.close < c.open else 0)
    if body_pct <= 0.10:
        ctype, expl = "doji", "Doji: buyers and sellers balanced - indecision."
    elif body_pct >= 0.85 and uw <= 0.08 and lw <= 0.08:
        ctype, expl = "marubozu", "Marubozu: one side fully in control, almost no wicks."
    elif lw >= 0.55 and body_pct <= 0.35:
        ctype = "hammer" if direction >= 0 else "pin_bar"
        expl = "Long lower wick: lows were strongly rejected (buying pressure)."
    elif uw >= 0.55 and body_pct <= 0.35:
        ctype = "shooting_star" if direction <= 0 else "pin_bar"
        expl = "Long upper wick: highs were strongly rejected (selling pressure)."
    elif body_pct <= 0.35:
        ctype, expl = "spinning_top", "Spinning top: small body, both sides tried - indecision."
    else:
        ctype, expl = "normal", "Normal directional candle."
    return {"type": ctype, "body_pct": round(body_pct, 3),
            "upper_wick_ratio": round(uw, 3), "lower_wick_ratio": round(lw, 3),
            "direction": direction, "explanation": expl}


def _res(name, direction, strength, explanation, symbol=""):
    s = max(0.0, min(1.0, strength))
    return AnalysisResult(symbol=symbol, direction=direction,
                          score_component=direction * s * 1.5,
                          name=name, strength=round(s, 3),
                          reasons=[explanation])


def double_candle_patterns(prev, cur, symbol: str = "") -> Optional[AnalysisResult]:
    found = []
    p_top, p_bot = max(prev.open, prev.close), min(prev.open, prev.close)
    c_top, c_bot = max(cur.open, cur.close), min(cur.open, cur.close)
    p_rng, c_rng = prev.high - prev.low, cur.high - cur.low
    if p_rng <= 0 or c_rng <= 0:
        return None
    if cur.close > cur.open and prev.close < prev.open and c_top >= p_top and c_bot <= p_bot:
        e = (c_top - c_bot) / max(p_top - p_bot, 1e-9)
        found.append(_res("bullish_engulfing", 1, 0.5 + 0.3 * min(e - 1, 1),
                          "Bullish engulfing: buyers swallowed the prior bear candle.", symbol))
    if cur.close < cur.open and prev.close > prev.open and c_top >= p_top and c_bot <= p_bot:
        e = (c_top - c_bot) / max(p_top - p_bot, 1e-9)
        found.append(_res("bearish_engulfing", -1, 0.5 + 0.3 * min(e - 1, 1),
                          "Bearish engulfing: sellers swallowed the prior bull candle.", symbol))
    tol = 0.05 * p_rng
    if abs(cur.high - prev.high) <= tol and cur.close < cur.open and prev.close > prev.open:
        found.append(_res("tweezer_top", -1, 0.55, "Tweezer top: same high rejected twice.", symbol))
    if abs(cur.low - prev.low) <= tol and cur.close > cur.open and prev.close < prev.open:
        found.append(_res("tweezer_bottom", 1, 0.55, "Tweezer bottom: same low rejected twice.", symbol))
    if cur.high <= prev.high and cur.low >= prev.low and c_rng < p_rng:
        found.append(AnalysisResult(symbol=symbol, direction=0, score_component=0.0,
                                    name="inside_bar", strength=0.35,
                                    reasons=["Inside bar: range compressed inside prior candle."]))
    p_mid = (prev.open + prev.close) / 2.0
    if prev.close < prev.open and cur.close > cur.open and cur.open < prev.low and p_mid < cur.close < prev.open:
        found.append(_res("piercing_line", 1, 0.6,
                          "Piercing line: gap-down open recovered past the midpoint.", symbol))
    if prev.close > prev.open and cur.close < cur.open and cur.open > prev.high and prev.open > cur.close > p_mid:
        found.append(_res("dark_cloud_cover", -1, 0.6,
                          "Dark cloud cover: gap-up open fell past the midpoint.", symbol))
    directional = [f for f in found if f.direction != 0]
    pool = directional if directional else found
    return max(pool, key=lambda f: f.strength) if pool else None


def psychology_result(c, symbol: str = "") -> AnalysisResult:
    """Psychology as a standardized AnalysisResult (score up to +/-0.5)."""
    p = candle_psychology(c)
    score, direction = 0.0, 0
    if p["type"] == "hammer":
        score, direction = 0.5, 1
    elif p["type"] == "shooting_star":
        score, direction = -0.5, -1
    elif p["type"] == "marubozu":
        score, direction = 0.5 * p["direction"], p["direction"]
    elif p["type"] == "pin_bar":
        direction = 1 if p["lower_wick_ratio"] > p["upper_wick_ratio"] else -1
        score = 0.3 * direction
    return AnalysisResult(symbol=symbol, direction=direction,
                          score_component=score, name=f"psych_{p['type']}",
                          strength=abs(score) * 2,
                          reasons=[f"Candle psychology: {p['explanation']}"] if score else [],
                          extra=p)
