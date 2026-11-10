"""Signal history - append-only store at logs/signals.json.

The file is runtime data: it is NOT in manifest.txt (an update
must never wipe trading history). Code creates logs/ + the file
([]) if missing, and tolerates a corrupt/missing file.
A recorded signal is never edited - that immutability is the
live non-repaint proof.
"""
from __future__ import annotations

import json
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
SIGNALS_FILE = LOGS_DIR / "signals.json"


def _ensure():
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        if not SIGNALS_FILE.exists():
            SIGNALS_FILE.write_text("[]", encoding="utf-8")
    except OSError:
        pass


def _load() -> list:
    _ensure()
    try:
        data = json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


class SignalHistory:
    def __init__(self, path=None):
        self.path = Path(path) if path else SIGNALS_FILE
        if path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self.path.write_text("[]", encoding="utf-8")

    def _read(self) -> list:
        if self.path == SIGNALS_FILE:
            return _load()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def add(self, signal_dict: dict) -> dict:
        rows = self._read()
        rows.append(signal_dict)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        except OSError:
            pass
        return signal_dict

    def get_recent(self, n: int = 50) -> list:
        return self._read()[-n:][::-1]

    def count(self) -> int:
        return len(self._read())
