"""GL Trader configuration - pairs, payout, thresholds, ports."""
from __future__ import annotations

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURJPY", "GBPJPY",
]

TIMEFRAME = "M1"
CONFIRM_TIMEFRAME = "M5"
PORT = 8771  # JARVIS main app uses 8765 - no clash
HOST = "127.0.0.1"

BASE_PRICES = {
    "EURUSD": 1.0850, "GBPUSD": 1.2720, "USDJPY": 149.80,
    "AUDUSD": 0.6590, "USDCAD": 1.3680, "USDCHF": 0.8840,
    "NZDUSD": 0.6120, "EURJPY": 162.50, "GBPJPY": 190.60,
}
SPREADS_PIPS = {
    "EURUSD": 1.0, "GBPUSD": 1.2, "USDJPY": 1.1, "AUDUSD": 1.2,
    "USDCAD": 1.4, "USDCHF": 1.3, "NZDUSD": 1.6,
    "EURJPY": 1.8, "GBPJPY": 2.2,
}
BASE_VOL_PIPS = {
    "EURUSD": 4.0, "GBPUSD": 5.0, "USDJPY": 4.5, "AUDUSD": 4.0,
    "USDCAD": 4.0, "USDCHF": 3.5, "NZDUSD": 3.5,
    "EURJPY": 5.5, "GBPJPY": 7.0,
}


def pip_size(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def price_decimals(symbol: str) -> int:
    return 3 if "JPY" in symbol else 5


DEFAULT_PAYOUT = 0.80
DEFAULT_STAKE = 10.0
PAPER_START_BALANCE = 1000.0
MIN_POWER_FOR_BEST = 6
ATR_MIN_PIPS = 1.2
ATR_MAX_PIPS = 25.0
WARMUP_CANDLES = 210
MAX_CANDLES_PER_PAIR = 500  # cache cap - lightweight for 8GB RAM laptops


def breakeven_win_rate(payout: float = DEFAULT_PAYOUT) -> float:
    if payout <= 0:
        raise ValueError("payout must be > 0")
    return 1.0 / (1.0 + payout)


def classify_power(power: int) -> str:
    if power >= 8:
        return "Very Strong"
    if power >= 5:
        return "Strong"
    return "Weak"


DISCLAIMER = (
    "Signals are research, NOT guaranteed. Binary trading is high "
    "risk - paper mode only. No real-money trades are placed."
)
