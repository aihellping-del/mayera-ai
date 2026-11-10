"""Backtesting - NO look-ahead, payout-aware, in/out-of-sample.

For each index: sig = signal_at(candles, idx) which sees ONLY
candles[:idx+1] (M5 gate likewise uses only M5 blocks closed by
then). Entry = NEXT candle's open, exit = NEXT candle's close
(1-minute expiry). Trades split chronologically: first 70% =
in-sample, last 30% = out-of-sample.
"""
from __future__ import annotations

from .. import config
from .signal_engine import signal_at


def _summarise(trades: list, payout: float) -> dict:
    if not trades:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "breakeven_wr": round(config.breakeven_win_rate(payout), 4),
                "net_pnl": 0.0, "expectation": 0.0, "max_drawdown": 0.0,
                "profit_factor": 0.0}
    wins = sum(1 for t in trades if t["win"])
    pnl_curve, equity, peak, max_dd = [], 0.0, 0.0, 0.0
    gross_win = gross_loss = 0.0
    for t in trades:
        equity += t["pnl"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if t["pnl"] > 0:
            gross_win += t["pnl"]
        else:
            gross_loss += abs(t["pnl"])
    n = len(trades)
    return {"trades": n, "wins": wins, "losses": n - wins,
            "win_rate": round(wins / n, 4),
            "breakeven_wr": round(config.breakeven_win_rate(payout), 4),
            "net_pnl": round(equity, 2),
            "expectation": round(equity / n, 4),
            "max_drawdown": round(max_dd, 2),
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else 0.0}


def backtest_pair(candles, symbol: str, payout: float = config.DEFAULT_PAYOUT,
                  warmup: int = config.WARMUP_CANDLES,
                  min_power: int = config.MIN_POWER_FOR_BEST) -> dict:
    trades = []
    for idx in range(warmup, len(candles) - 1):
        sig = signal_at(candles, idx, symbol=symbol)
        if not sig or sig.direction not in ("CALL", "PUT"):
            continue
        if sig.power_score < min_power:
            continue
        nxt = candles[idx + 1]
        entry, exit_ = nxt.open, nxt.close
        if exit_ == entry:
            continue  # refund - excluded, matches paper tie rule
        win = (exit_ > entry) if sig.direction == "CALL" else (exit_ < entry)
        trades.append({"time": candles[idx].time, "symbol": symbol,
                       "direction": sig.direction, "power": sig.power_score,
                       "entry": entry, "exit": exit_, "win": win,
                       "pnl": payout if win else -1.0})
    split = int(len(trades) * 0.7)
    return {"symbol": symbol, "payout": payout,
            "combined": _summarise(trades, payout),
            "in_sample": _summarise(trades[:split], payout),
            "out_of_sample": _summarise(trades[split:], payout),
            "trade_list": trades}


def run_backtest(feed, symbols=None, candles: int = 1500,
                 payout: float = config.DEFAULT_PAYOUT) -> dict:
    report = {}
    for symbol in (symbols or config.PAIRS):
        try:
            hist = feed.history(symbol, candles) \
                if hasattr(feed, "history") else feed.get_candles(symbol, candles)
        except Exception as exc:
            report[symbol] = {"error": str(exc)}
            continue
        r = backtest_pair(hist, symbol, payout=payout)
        r.pop("trade_list", None)
        report[symbol] = r
    return report
