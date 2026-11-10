"""Paper trading ledger - PAPER money only, never real.

Tie rule: exit == entry = REFUND (stake back, counts neither as
win nor loss). Documented choice for research realism.
Persists to logs/paper.json (runtime data, not in manifest).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import config

PAPER_FILE = Path(__file__).resolve().parent.parent / "logs" / "paper.json"


class PaperTrader:
    def __init__(self, path=None, stake: float = config.DEFAULT_STAKE,
                 payout: float = config.DEFAULT_PAYOUT):
        self.path = Path(path) if path else PAPER_FILE
        self.stake, self.payout = stake, payout
        self.balance = config.PAPER_START_BALANCE
        self.pending: list = []
        self.closed: list = []
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.balance = d.get("balance", self.balance)
                self.pending = d.get("pending", [])
                self.closed = d.get("closed", [])
        except Exception:
            pass

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(
                {"balance": self.balance, "pending": self.pending,
                 "closed": self.closed}, indent=1), encoding="utf-8")
        except OSError:
            pass

    def reset(self):
        self.balance = config.PAPER_START_BALANCE
        self.pending, self.closed = [], []
        self._save()

    def place(self, signal) -> dict:
        s = signal.to_dict() if hasattr(signal, "to_dict") else dict(signal)
        if s.get("direction") not in ("CALL", "PUT"):
            return {"status": "skipped", "reason": "NO TRADE is not placed"}
        trade = {"symbol": s["symbol"], "direction": s["direction"],
                 "entry_price": s["price"], "entry_time": s["time"],
                 "expiry_time": s["time"] + 60, "stake": self.stake,
                 "power": s.get("power_score")}
        self.pending.append(trade)
        self._save()
        return {"status": "placed", "trade": trade}

    def settle_due(self, feed, now: int = None) -> list:
        now = now or int(time.time())
        settled, remaining = [], []
        for t in self.pending:
            # Synthetic feed times are historical; settle on the
            # feed's own latest candle instead of wall-clock when
            # the feed is the demo feed.
            try:
                candles = feed.get_candles(t["symbol"], 5)
                latest = candles[-1] if candles else None
            except Exception:
                latest = None
            feed_now = latest.time if latest else now
            due = (t["expiry_time"] <= now) or (latest and t["entry_time"] < latest.time)
            if not due or latest is None:
                remaining.append(t)
                continue
            exit_price = latest.close
            result = self._settle_one(t, exit_price)
            settled.append(result)
        self.pending = remaining
        if settled:
            self._save()
        return settled

    def settle_with_price(self, trade_index_price: float = None, **kw):
        """Direct settle helper (used by tests + server loop)."""
        raise NotImplementedError

    def _settle_one(self, t: dict, exit_price: float) -> dict:
        entry = t["entry_price"]
        if exit_price == entry:
            outcome, pnl = "REFUND", 0.0
        elif (t["direction"] == "CALL" and exit_price > entry) or \
                (t["direction"] == "PUT" and exit_price < entry):
            outcome, pnl = "WIN", round(t["stake"] * self.payout, 2)
        else:
            outcome, pnl = "LOSS", -t["stake"]
        self.balance = round(self.balance + pnl, 2)
        done = {**t, "exit_price": exit_price, "outcome": outcome, "pnl": pnl}
        self.closed.append(done)
        return done

    def settle_trade(self, symbol: str, exit_price: float) -> list:
        """Settle ALL pending trades for a symbol at a given price
        (deterministic helper for tests and manual server settle)."""
        out, remaining = [], []
        for t in self.pending:
            if t["symbol"] == symbol:
                out.append(self._settle_one(t, exit_price))
            else:
                remaining.append(t)
        self.pending = remaining
        if out:
            self._save()
        return out

    def stats(self) -> dict:
        wins = sum(1 for c in self.closed if c["outcome"] == "WIN")
        losses = sum(1 for c in self.closed if c["outcome"] == "LOSS")
        refunds = sum(1 for c in self.closed if c["outcome"] == "REFUND")
        decided = wins + losses
        by_pair = {}
        for c in self.closed:
            p = by_pair.setdefault(c["symbol"], {"trades": 0, "wins": 0, "pnl": 0.0})
            p["trades"] += 1
            p["wins"] += 1 if c["outcome"] == "WIN" else 0
            p["pnl"] = round(p["pnl"] + c["pnl"], 2)
        return {"mode": "PAPER", "balance": self.balance,
                "start_balance": config.PAPER_START_BALANCE,
                "trades": len(self.closed), "wins": wins, "losses": losses,
                "refunds": refunds, "pending": len(self.pending),
                "win_rate": round(wins / decided, 4) if decided else 0.0,
                "net_pnl": round(self.balance - config.PAPER_START_BALANCE, 2),
                "by_pair": by_pair}
