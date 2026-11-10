"""JARVIS integration layer - thin delegates to TraderController.

RESEARCH ONLY: signals are never guaranteed, paper mode only.
"""
from __future__ import annotations


def _controller():
    from ..main import get_controller
    return get_controller()


def start_analysis() -> dict:
    return _controller().start()


def stop_analysis() -> dict:
    return _controller().stop()


def status() -> dict:
    return _controller().status()


def strongest_pair() -> dict:
    best = _controller().best_signal()
    if not best:
        data = _controller().scan_once()
        return {"status": "ok", "best": None,
                "message": data.get("best_reason", "no qualifying setup")}
    return {"status": "ok", "best": best}


def explain_current_signal() -> dict:
    best = strongest_pair().get("best")
    if not best or not best.get("signal"):
        return {"status": "ok", "signal": None,
                "explanation": "Abhi koi qualifying setup nahi hai - "
                               "NO TRADE. Market weak ya filters ne roka hai."}
    s = best["signal"]
    return {"status": "ok", "signal": s,
            "explanation": (
                f"{s['symbol']} par {s['direction']} signal hai. "
                f"Power {s['power_score']}/10 ({s['classification']}), "
                f"strength {s['strength_pct']}%. Wajah: "
                + " ".join(s.get("reasons", []))
                + " Ye RESEARCH signal hai, guarantee nahi hai.")}


def read_history(n: int = 10) -> dict:
    return {"status": "ok",
            "history": _controller().history.get_recent(int(n))}


def backtest_report(symbol: str = "all") -> dict:
    return {"status": "ok", "report": _controller().backtest(symbol)}
