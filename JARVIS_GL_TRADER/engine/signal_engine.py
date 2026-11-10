"""Signal engine - additive scoring + M5 confirmation gate.

NON-REPAINTING: signal_at(candles, idx, m5_candles) uses ONLY
candles[:idx+1] and M5 candles whose close_time <= the signal
candle's close_time. Live and backtest share this one function.

Decisions: CALL / PUT / NO TRADE. NO TRADE when the volatility
filter fails, the score is Weak (power <= 4), or M5 confirmation
FAILS. M5 gate: EMA9 vs EMA21 on M5 closes must agree with the M1
direction; disagreement first halves the trend weight - if the
resulting power still qualifies it is kept with reduced power,
otherwise NO TRADE. The gate result is always in reasons as
"M5 confirmation: OK" or "M5 confirmation: FAILED ...".
"""
from __future__ import annotations

from typing import List, Optional

from .. import config
from ..data.mt5_feed import aggregate_candles
from ..models import Signal
from ..strategies import indicators
from ..strategies.candle_psychology import double_candle_patterns, psychology_result
from ..strategies.crt import crt_event


def m5_trend_direction(m5_candles) -> int:
    """+1 if EMA9 > EMA21 on M5 closes, -1 if below, 0 if unknown."""
    if not m5_candles or len(m5_candles) < 21:
        return 0
    closes = [c.close for c in m5_candles]
    e9 = indicators.ema_series(closes, 9)
    e21 = indicators.ema_series(closes, 21)
    a, b = e9[-1], e21[-1]
    if a is None or b is None:
        return 0
    return 1 if a > b else (-1 if a < b else 0)


def _m5_available_at(m1_candles, idx: int):
    """M5 candles fully closed by the time candle `idx` closes.
    Aggregates ONLY candles[:idx+1] into complete M5 blocks, which
    by construction end at or before idx's close - no look-ahead."""
    upto = m1_candles[:idx + 1]
    return aggregate_candles(upto, 5)


def _no_trade(symbol, price, t, reasons, components=None, atr_pips=None,
              filter_reason=""):
    return Signal(symbol=symbol, direction="NO TRADE", strength_pct=0.0,
                  power_score=0, classification="No Trade", price=price,
                  time=t, reasons=reasons, components=components or {},
                  atr_pips=atr_pips,
                  volatility_ok=(filter_reason == ""),
                  filter_reason=filter_reason, m5_confirmed=False)


def signal_at(candles, idx: int, symbol: str = "",
              m5_candles=None) -> Optional[Signal]:
    if idx < config.WARMUP_CANDLES or idx >= len(candles):
        return None
    window = candles[:idx + 1]
    if m5_candles is None:
        m5 = _m5_available_at(candles, idx)
    else:
        # Use only M5 candles closed by the signal candle's close.
        cutoff = window[-1].time + 60
        m5 = [c for c in m5_candles if c.time + 300 <= cutoff]
    return _score(symbol or "?", window, m5)


def analyse(symbol: str, candles, m5_candles=None) -> Optional[Signal]:
    if len(candles) < config.WARMUP_CANDLES + 1:
        return None
    if m5_candles is None:
        m5_candles = aggregate_candles(list(candles), 5)
    return signal_at(candles, len(candles) - 1, symbol=symbol,
                     m5_candles=m5_candles)


def _score(symbol: str, window, m5_candles) -> Optional[Signal]:
    closes = [c.close for c in window]
    last, prev, i = window[-1], window[-2], len(window) - 1
    pip = config.pip_size(symbol) if symbol in config.PAIRS else (
        0.01 if "JPY" in symbol else 0.0001)
    ema9 = indicators.ema_series(closes, 9)
    ema21 = indicators.ema_series(closes, 21)
    ema50 = indicators.ema_series(closes, 50)
    ema200 = indicators.ema_series(closes, 200)
    rsi = indicators.rsi_series(closes, 14)
    _, _, macd_hist = indicators.macd_series(closes)
    bb_up, bb_mid, bb_low = indicators.bollinger(closes, 20, 2.0)
    atr = indicators.atr_series(window, 14)
    if None in (ema200[i], rsi[i], macd_hist[i], bb_mid[i], atr[i]):
        return None
    atr_pips = atr[i] / pip

    # Volatility filter gate.
    if atr_pips < config.ATR_MIN_PIPS:
        return _no_trade(symbol, last.close, last.time,
                         [f"Volatility filter: ATR too low ({atr_pips:.1f} pips) - dead market. NO TRADE."],
                         atr_pips=round(atr_pips, 2), filter_reason="atr_too_low")
    vals = sorted(v for v in atr[-60:] if v is not None)
    median = vals[len(vals) // 2] if len(vals) >= 20 else None
    if atr_pips > config.ATR_MAX_PIPS or (median and atr[i] > 2.5 * median):
        return _no_trade(symbol, last.close, last.time,
                         [f"Volatility filter: ATR spike ({atr_pips:.1f} pips) - chaotic market. NO TRADE."],
                         atr_pips=round(atr_pips, 2), filter_reason="atr_spike")

    total, components, reasons = 0.0, {}, []
    price = closes[i]
    trend = 0.0
    trend += 0.7 if price > ema200[i] else -0.7
    trend += 0.5 if ema9[i] > ema21[i] else -0.5
    trend += 0.4 if ema21[i] > ema50[i] else -0.4
    trend += 0.4 if price > ema50[i] else -0.4
    trend = max(-2.0, min(2.0, trend))
    components["trend"] = round(trend, 2)
    total += trend
    reasons.append(f"Trend {'bullish' if trend > 0 else 'bearish'} (EMA9/21/50/200 {trend:+.1f})")

    hist_now, hist_prev = macd_hist[i], macd_hist[i - 1] or 0.0
    macd_score = (0.9 if hist_now > 0 else -0.9 if hist_now < 0 else 0.0)
    if hist_now > hist_prev and hist_now > 0:
        macd_score += 0.6
    elif hist_now < hist_prev and hist_now < 0:
        macd_score -= 0.6
    macd_score = max(-1.5, min(1.5, macd_score))
    components["macd"] = round(macd_score, 2)
    total += macd_score
    reasons.append(f"MACD histogram {'positive' if macd_score > 0 else 'negative'} ({macd_score:+.1f})")

    r = rsi[i]
    rsi_score = 0.0
    if r <= 30:
        rsi_score = 1.5
        reasons.append(f"RSI oversold ({r:.0f}) - bounce bias CALL")
    elif r <= 40:
        rsi_score = 0.7
        reasons.append(f"RSI low zone ({r:.0f}) - mild CALL bias")
    elif r >= 70:
        rsi_score = -1.5
        reasons.append(f"RSI overbought ({r:.0f}) - rejection bias PUT")
    elif r >= 60:
        rsi_score = -0.7
        reasons.append(f"RSI high zone ({r:.0f}) - mild PUT bias")
    else:
        reasons.append(f"RSI neutral ({r:.0f})")
    components["rsi"] = round(rsi_score, 2)
    total += rsi_score

    bb_score = 0.0
    width = (bb_up[i] - bb_low[i]) or 1e-9
    pos = (price - bb_low[i]) / width
    if last.low <= bb_low[i] and price > bb_low[i]:
        bb_score = 1.0
        reasons.append("Bollinger: lower band rejected - mean reversion CALL")
    elif last.high >= bb_up[i] and price < bb_up[i]:
        bb_score = -1.0
        reasons.append("Bollinger: upper band rejected - mean reversion PUT")
    elif pos > 0.85:
        bb_score = -0.4
        reasons.append("Bollinger: price stretched near upper band")
    elif pos < 0.15:
        bb_score = 0.4
        reasons.append("Bollinger: price stretched near lower band")
    components["bollinger"] = round(bb_score, 2)
    total += bb_score

    crt = crt_event(prev, last, symbol=symbol)
    crt_score = crt.score_component if crt else 0.0
    if crt:
        reasons.extend(crt.reasons)
    components["crt"] = round(crt_score, 2)
    total += crt_score

    pat = double_candle_patterns(prev, last, symbol=symbol)
    pat_score = pat.score_component if pat and pat.direction != 0 else 0.0
    if pat and pat.direction != 0:
        reasons.extend(pat.reasons)
    components["pattern"] = round(pat_score, 2)
    total += pat_score

    psy = psychology_result(last, symbol=symbol)
    components["psychology"] = round(psy.score_component, 2)
    total += psy.score_component
    reasons.extend(psy.reasons)

    direction_int = 1 if total >= 0 else -1

    # ---- M5 CONFIRMATION GATE ---------------------------------------
    m5_dir = m5_trend_direction(m5_candles)
    m5_ok = (m5_dir == direction_int) if m5_dir != 0 else False
    if m5_dir == 0:
        reasons.append("M5 confirmation: FAILED (not enough M5 data) - NO TRADE")
        return _no_trade(symbol, last.close, last.time, reasons,
                         components, round(atr_pips, 2), "m5_unavailable")
    if not m5_ok:
        # Downgrade: halve total; qualifies only if still Strong+.
        reduced = total * 0.5
        power_r = int(max(1, min(10, round(abs(reduced)))))
        reasons.append("M5 confirmation: FAILED (M5 trend disagrees with M1) - power reduced")
        if power_r < 5:
            return Signal(symbol=symbol, direction="NO TRADE",
                          strength_pct=round(abs(reduced) * 10, 1),
                          power_score=power_r, classification="No Trade",
                          price=last.close, time=last.time, reasons=reasons,
                          components=components, atr_pips=round(atr_pips, 2),
                          volatility_ok=True, filter_reason="m5_failed",
                          m5_confirmed=False)
        total = reduced
        reasons.append("M5 confirmation: FAILED but setup strong enough - kept at reduced power")
    else:
        reasons.append("M5 confirmation: OK (M5 EMA9/21 agrees with M1)")

    power = int(max(1, min(10, round(abs(total)))))
    classification = config.classify_power(power)
    if power <= 4:
        return Signal(symbol=symbol, direction="NO TRADE",
                      strength_pct=round(abs(total) * 10, 1),
                      power_score=power, classification="No Trade",
                      price=last.close, time=last.time,
                      reasons=reasons + ["Weak setup (power <= 4) - NO TRADE"],
                      components=components, atr_pips=round(atr_pips, 2),
                      volatility_ok=True, filter_reason="weak",
                      m5_confirmed=m5_ok)
    return Signal(symbol=symbol,
                  direction="CALL" if total >= 0 else "PUT",
                  strength_pct=round(min(100.0, abs(total) * 10.0), 1),
                  power_score=power, classification=classification,
                  price=last.close, time=last.time, reasons=reasons,
                  components=components, atr_pips=round(atr_pips, 2),
                  volatility_ok=True, filter_reason="",
                  m5_confirmed=m5_ok)
