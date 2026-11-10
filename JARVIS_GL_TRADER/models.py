"""Shared data structures for JARVIS GL TRADER.

Single source of truth: Candle, AnalysisResult, Signal.
Everything flows: feed -> strategies -> scanner -> engine -> dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Candle:
    time: int  # epoch seconds of candle OPEN
    open: float
    high: float
    low: float
    close: float
    volume: float = 100.0

    @property
    def close_time(self) -> int:
        return self.time + 60

    def to_dict(self):
        return asdict(self)


@dataclass
class AnalysisResult:
    """Standardized output from every strategy."""
    symbol: str
    direction: int  # +1 bullish, -1 bearish, 0 neutral/none
    score_component: float = 0.0
    reasons: List[str] = field(default_factory=list)
    name: str = ""
    strength: float = 0.0  # 0..1 where relevant
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class Signal:
    symbol: str
    direction: str  # "CALL" / "PUT" / "NO TRADE"
    strength_pct: float = 0.0
    power_score: int = 0
    classification: str = "Weak"  # Weak / Strong / Very Strong / No Trade
    price: float = 0.0
    time: int = 0
    reasons: List[str] = field(default_factory=list)
    components: dict = field(default_factory=dict)
    atr_pips: Optional[float] = None
    volatility_ok: bool = True
    filter_reason: str = ""
    m5_confirmed: bool = False

    def to_dict(self):
        return asdict(self)
