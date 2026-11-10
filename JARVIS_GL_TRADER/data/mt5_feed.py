"""Feed layer: MT5 (Windows, read-only) + Synthetic DEMO fallback.

SAFETY: only READS candles. No trade-execution code anywhere.
NON-REPAINTING: both feeds return only CLOSED candles (MT5 feed
drops the still-forming last candle).
Supports timeframe="M1" (primary) and "M5" (confirmation).
"""
from __future__ import annotations

import hashlib
import random
from typing import List, Optional

from .. import config
from ..models import Candle

__all__ = ["Candle", "FeedUnavailable", "MT5Feed", "SyntheticFeed",
           "get_feed", "aggregate_candles"]


class FeedUnavailable(Exception):
    pass


def aggregate_candles(candles: List[Candle], factor: int = 5) -> List[Candle]:
    """Aggregate consecutive M1 candles into M5 (factor=5) candles.
    Only COMPLETE blocks are returned - a trailing partial block is
    dropped, so no forming M5 candle ever leaks in (no look-ahead)."""
    out: List[Candle] = []
    usable = len(candles) - (len(candles) % factor)
    for i in range(0, usable, factor):
        block = candles[i:i + factor]
        out.append(Candle(
            time=block[0].time, open=block[0].open,
            high=max(c.high for c in block),
            low=min(c.low for c in block),
            close=block[-1].close,
            volume=sum(c.volume for c in block)))
    return out


class MT5Feed:
    source = "MT5-LIVE"
    is_live = True

    def __init__(self):
        self._mt5 = None
        self.connect()

    def connect(self):
        try:
            import MetaTrader5 as mt5
        except Exception as exc:
            raise FeedUnavailable(f"MetaTrader5 not available: {exc}")
        try:
            if not mt5.initialize():
                raise FeedUnavailable(f"MT5 initialize failed: {mt5.last_error()}")
        except FeedUnavailable:
            raise
        except Exception as exc:
            raise FeedUnavailable(f"MT5 initialize error: {exc}")
        self._mt5 = mt5
        return True

    def get_candles(self, symbol: str, count: int,
                    timeframe: str = "M1") -> List[Candle]:
        if self._mt5 is None:
            raise FeedUnavailable("MT5 not connected")
        mt5 = self._mt5
        tf = mt5.TIMEFRAME_M5 if timeframe == "M5" else mt5.TIMEFRAME_M1
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count + 1)
        if rates is None or len(rates) < 2:
            raise FeedUnavailable(f"MT5 no rates for {symbol}: {mt5.last_error()}")
        candles = [Candle(time=int(r["time"]), open=float(r["open"]),
                          high=float(r["high"]), low=float(r["low"]),
                          close=float(r["close"]),
                          volume=float(r["tick_volume"])) for r in rates]
        return candles[:-1][-count:]  # drop forming candle

    def history(self, symbol: str, n: int) -> List[Candle]:
        return self.get_candles(symbol, n)


def _seed_for(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)


class SyntheticFeed:
    """Deterministic seeded M1 generator with regime shifts.
    NOT real data - labelled DEMO-SYNTHETIC everywhere."""
    source = "DEMO-SYNTHETIC"
    is_live = False

    def __init__(self, base_time: Optional[int] = None):
        self._anchor = base_time or 1735689600  # 2025-01-01 UTC
        self._cache = {}

    def _gen_series(self, symbol: str, n: int) -> List[Candle]:
        rng = random.Random(_seed_for(symbol))
        pip = config.pip_size(symbol)
        base = config.BASE_PRICES[symbol]
        vol_pips = config.BASE_VOL_PIPS[symbol]
        dec = config.price_decimals(symbol)
        price, candles = base, []
        regime, regime_left, drift, vol_mult = "range", rng.randint(40, 120), 0.0, 1.0
        for i in range(n):
            if regime_left <= 0:
                regime = rng.choice(["trend_up", "trend_down", "range", "range", "burst"])
                regime_left = rng.randint(30, 140)
                if regime == "trend_up":
                    drift = rng.uniform(0.4, 1.4)
                elif regime == "trend_down":
                    drift = -rng.uniform(0.4, 1.4)
                else:
                    drift = rng.uniform(-0.15, 0.15)
                vol_mult = 2.2 if regime == "burst" else rng.uniform(0.7, 1.3)
            regime_left -= 1
            pull = (base - price) / pip * 0.002
            step = rng.gauss(drift + pull, vol_pips * vol_mult)
            o = price
            c = o + step * pip
            h = max(o, c) + rng.uniform(0.1, 0.45) * vol_pips * vol_mult * pip
            lo = min(o, c) - rng.uniform(0.1, 0.45) * vol_pips * vol_mult * pip
            candles.append(Candle(time=self._anchor + i * 60,
                                  open=round(o, dec), high=round(h, dec),
                                  low=round(lo, dec), close=round(c, dec),
                                  volume=round(rng.uniform(60, 240), 1)))
            price = c
        return candles

    def _ensure(self, symbol: str, n: int):
        cached = self._cache.get(symbol)
        if cached and len(cached[0]) >= n:
            return cached
        want = max(n, 600) if not cached else max(n, len(cached[0]) * 2)
        want = max(want, config.MAX_CANDLES_PER_PAIR)
        candles = self._gen_series(symbol, want)
        state = (candles, random.Random(_seed_for(symbol) + want))
        self._cache[symbol] = state
        return state

    def get_candles(self, symbol: str, count: int,
                    timeframe: str = "M1") -> List[Candle]:
        if timeframe == "M5":
            need = count * 5 + 5
            m1, _ = self._ensure(symbol, need)
            return aggregate_candles(list(m1))[-count:]
        candles, _ = self._ensure(symbol, max(count, 600))
        return list(candles[-count:])

    def history(self, symbol: str, n: int) -> List[Candle]:
        candles, _ = self._ensure(symbol, n)
        return list(candles[-n:])

    def tick(self, symbol: str = "EURUSD") -> Candle:
        candles, rng = self._ensure(symbol, 600)
        pip = config.pip_size(symbol)
        vp = config.BASE_VOL_PIPS[symbol]
        dec = config.price_decimals(symbol)
        last = candles[-1]
        o = last.close
        c = o + rng.gauss(0, vp) * pip
        h = max(o, c) + rng.uniform(0.1, 0.4) * vp * pip
        lo = min(o, c) - rng.uniform(0.1, 0.4) * vp * pip
        nc = Candle(time=last.time + 60, open=round(o, dec),
                    high=round(h, dec), low=round(lo, dec),
                    close=round(c, dec),
                    volume=round(rng.uniform(60, 240), 1))
        candles.append(nc)
        # Cache cap: keep memory bounded on an 8GB laptop.
        if len(candles) > config.MAX_CANDLES_PER_PAIR * 4:
            del candles[:len(candles) - config.MAX_CANDLES_PER_PAIR * 2]
        return nc


def get_feed(prefer_mt5: bool = True):
    if prefer_mt5:
        try:
            return MT5Feed()
        except Exception:
            pass
    return SyntheticFeed()
