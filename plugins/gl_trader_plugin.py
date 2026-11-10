"""JARVIS plugin: GL Trader (v3.35) - binary signal RESEARCH.

One tool "gl_trader" with an action parameter, routing to
JARVIS_GL_TRADER/jarvis/integration.py -> TraderController.
RESEARCH ONLY - koi guarantee nahi, paper mode only, koi real
trade kabhi nahi lagta.
"""

TOOL = {
    "name": "gl_trader",
    "description": (
        "Jab user trading signal / best pair / GL Trader / backtest "
        "bole to is tool se asli scan lao, khud mat banao. Actions: "
        "start, stop, status, best, explain, history, backtest. "
        "Ye RESEARCH hai, guarantee nahi - ye baat user ko hamesha "
        "bolo. Koi real-money trade isse kabhi nahi lagta, sirf "
        "paper/research analysis hota hai."
    ),
    "parameters": {
        "action": ("string",
                   "Ek action: start | stop | status | best | explain | history | backtest."),
        "symbol": ("string",
                   "Backtest ke liye pair (EURUSD jaise) ya 'all'. Optional."),
    },
    "required": ["action"],
}


def handle(args):
    try:
        from JARVIS_GL_TRADER.jarvis import integration
    except Exception as exc:  # GL Trader missing/broken - never crash JARVIS
        return {"status": "error",
                "message": f"GL Trader load nahi hua: {exc}"}
    action = str((args or {}).get("action") or "status").lower().strip()
    symbol = str((args or {}).get("symbol") or "all")
    try:
        if action == "start":
            return {"status": "done", **integration.start_analysis()}
        if action == "stop":
            return {"status": "done", **integration.stop_analysis()}
        if action == "status":
            return {"status": "ok", **integration.status()}
        if action == "best":
            return integration.strongest_pair()
        if action == "explain":
            return integration.explain_current_signal()
        if action == "history":
            return integration.read_history(10)
        if action == "backtest":
            return integration.backtest_report(symbol)
        return {"status": "error",
                "message": f"Unknown action '{action}' - start/stop/status/best/explain/history/backtest me se ek do."}
    except Exception as exc:
        return {"status": "error", "message": f"GL Trader error: {exc}"}
