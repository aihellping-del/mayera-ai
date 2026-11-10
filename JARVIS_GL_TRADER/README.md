# JARVIS GL TRADER — Binary Signal Research System

> **RISK WARNING:** Binary trading is high risk and most retail
> traders lose money. This system is for **RESEARCH and paper
> trading only**. Signals are **NOT guaranteed** — no win rate is
> promised anywhere. It never places a real-money trade and has
> no order-execution code at all.

## Run it

```
START_GL_TRADER.bat            (Windows, repo root)
python -m JARVIS_GL_TRADER.main   (from repo root, any OS)
```
Dashboard: http://127.0.0.1:8771 (JARVIS voice app uses 8765 — no clash).
Lightweight: pure Python, no pandas/numpy, candle cache capped at
500/pair — runs fine on an **8GB RAM** laptop.

## Layout (single flow, no disconnected scripts)

```
feed (data/mt5_feed.py) -> strategies (CRT + psychology + indicators)
-> scanner/best_pair.py -> engine/signal_engine.py
-> dashboard + engine/history.py (logs/signals.json) + engine/paper.py
main.py = TraderController — dashboard AND voice plugin both use it.
```

## Data: MT5 or DEMO

Open the MetaTrader 5 terminal and log in with a **demo account**
first — GL Trader then reads **closed M1 + M5 candles only**
(read-only; Algo Trading is NOT needed and nothing is ever sent
to the broker). Without MT5 it falls back to a deterministic
**DEMO-SYNTHETIC** feed (badge on the dashboard says which).

## How a signal is made

M1 is primary; **M5 confirmation is mandatory**: EMA9 vs EMA21 on
closed M5 candles must agree with the M1 direction, else the
decision is downgraded — usually to **NO TRADE** (reason recorded
as `M5 confirmation: OK/FAILED`). Decisions: CALL / PUT / NO TRADE.

| Component | Max points |
|---|---|
| Trend EMA 9/21/50/200 alignment | ±2.0 |
| CRT sweep-and-reclaim | ±2.0 |
| MACD momentum | ±1.5 |
| RSI zone | ±1.5 |
| Double-candle pattern | ±1.5 |
| Bollinger position | ±1.0 |
| Candle psychology | ±0.5 |

Power = round(|total|) clamped 1–10 · ≤4 Weak · 5–7 Strong ·
8–10 Very Strong · Strength % = |total| × 10. Volatility filter
(ATR) and the M5 gate can force NO TRADE. **Non-repainting:**
`signal_at(candles, idx)` uses only `candles[:idx+1]`; live and
backtest share it, so a past signal can never change.

**CRT (Candle Range Theory):** price raids beyond the previous
candle's high/low (liquidity grab), then closes back inside that
range with a rejection wick — the trapped side drives the signal.

## Backtest meaning

`engine/backtesting.py`: entry = next candle open, exit = next
candle close (1-minute expiry), stake 1 unit, payout-aware
(breakeven at 0.80 payout = **55.56%** win rate). First 70% of
trades = in-sample, last 30% = out-of-sample, reported separately.
On synthetic demo data expect ~50% — synthetic data has no real
edge, and the engine is deliberately **not** tuned to fake one.

## Voice (JARVIS)

Say *"GL Trader best pair batao"* — the `gl_trader` plugin tool
(start/stop/status/best/explain/history/backtest) answers from the
same controller the dashboard uses.
