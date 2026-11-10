"""Persistent activity log (v3.34, from the user's automation
spec §8: 'Keep an activity log').

One JSON line per finished tool call in `activity.log` next to
the program: when, which tool, its status, how long it took.
Deliberately NOT logged: the tool's ARGUMENTS and results -
they can hold dictated messages, typed text and other private
content, and a log must never become a leak. The terminal shows
live [tool] lines; this file is the durable record he can open
 later to see what JARVIS actually did.

The file self-trims to its last ~256 KB. Every failure here is
swallowed: logging must never break a tool call.
"""

import json
import time
from pathlib import Path

MAX_BYTES = 512 * 1024


def _path(root=None):
    base = (Path(root) if root is not None
            else Path(__file__).resolve().parent.parent)
    return base / "activity.log"


def log_tool(name, status, seconds, root=None):
    try:
        path = _path(root)
        line = json.dumps(
            {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
             "tool": str(name), "status": str(status),
             "seconds": round(float(seconds), 2)},
            ensure_ascii=False) + "\n"
        if path.exists() and path.stat().st_size > MAX_BYTES:
            data = path.read_bytes()[-(MAX_BYTES // 2):]
            path.write_bytes(data[data.find(b"\n") + 1:])
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:  # noqa: BLE001 - a log must never break work
        pass
