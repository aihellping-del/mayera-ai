"""JARVIS - one shared undo stack (concept ported from Mark LVI's
core/undo.py by FatihMakes, CC BY-NC 4.0; reimplemented for this
codebase with serialisable entries instead of closures).

WHY: a voice assistant misunderstands. "Sorry" is not a remedy -
the file is already moved. So reversible actions register HOW to
reverse themselves here, and the user just says "undo kar do".
Confirmation stays reserved for what cannot be reversed.

Entries are plain dicts (JSON-able), so the stack could be
persisted later; today it is in-memory, depth 10 - roughly "this
conversation", which is where mistakes get noticed.
"""

import threading
import time

MAX_DEPTH = 10

_lock = threading.Lock()
_stack = []


def push_undo(label, op, data):
    """Register a reversible action. op names the reversal the
    file-ops layer knows how to execute; data carries its paths."""
    with _lock:
        _stack.append({"label": label, "op": op, "data": data,
                       "at": time.time()})
        del _stack[:-MAX_DEPTH]


def pop_undo():
    with _lock:
        return _stack.pop() if _stack else None


def peek_label():
    with _lock:
        return _stack[-1]["label"] if _stack else None


def depth():
    with _lock:
        return len(_stack)


def clear():
    with _lock:
        _stack.clear()
