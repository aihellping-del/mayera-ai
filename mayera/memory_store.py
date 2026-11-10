"""MAYERA - persistent memory (SQLite, stdlib only).

Stores three things in `mayera_memory.db` next to the app:
  * memories    - facts MAYERA is asked (or decides) to remember
  * checkpoints - where the last conversation ended, so the next one
                  can continue naturally ("conversation checkpoint")
  * settings    - memory on/off, proactive on/off, quiet hours, ...

Rules:
  * Passwords and API keys are NEVER stored here - add_memory() refuses
    anything that looks like a credential.
  * Everything can be viewed and deleted from the Settings panel, and
    memory can be switched off completely.
"""

import re
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "mayera_memory.db"

_SECRET_PATTERNS = (
    re.compile(r"api[\s_-]*key", re.I),
    re.compile(r"password|पासवर्ड", re.I),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{10,}"),          # Google API key shape
    re.compile(r"\bsk-[0-9A-Za-z]{10,}"),              # generic secret key shape
    re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),  # card numbers
)

DEFAULT_SETTINGS = {
    "memory_enabled": "1",
    "proactive_enabled": "1",
    "inactivity_seconds": "120",
    "quiet_start": "23:00",
    "quiet_end": "07:00",
    "reply_speed": "fast",
    "web_search": "0",
    "push_to_talk": "0",
}


def looks_like_secret(text):
    return any(p.search(text or "") for p in _SECRET_PATTERNS)


class MemoryStore:
    def __init__(self, db_path=None):
        self._path = str(db_path or DB_PATH)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self._path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'voice',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    topic TEXT, last_user TEXT, last_ai TEXT,
                    ended_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                """
            )
            for k, v in DEFAULT_SETTINGS.items():
                self._db.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (k, v),
                )

    # ------------------------------------------------------------------
    # memories
    # ------------------------------------------------------------------
    def add_memory(self, content, source="voice"):
        content = (content or "").strip()
        if not content:
            return None
        if looks_like_secret(content):
            return "refused_secret"
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO memories (content, source, created_at) VALUES (?, ?, ?)",
                (content, source, time.time()),
            )
            return cur.lastrowid

    def list_memories(self, limit=100):
        with self._lock:
            rows = self._db.execute(
                "SELECT id, content, source, created_at FROM memories "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def search_memories(self, query, limit=10):
        """Keyword search across ALL stored memories (v3.15 recall):
        the session prompt only carries the newest memories, so
        older facts are found on demand through this search -
        nothing stored is ever out of reach."""
        words = [w for w in (query or "").lower().split() if len(w) > 2]
        if not words:
            return []
        with self._lock:
            rows = self._db.execute(
                "SELECT id, content, source, created_at FROM memories "
                "ORDER BY id DESC"
            ).fetchall()
        scored = []
        for r in rows:
            text = r["content"].lower()
            hits = sum(1 for w in words if w in text)
            if hits:
                scored.append((hits, dict(r)))
        scored.sort(key=lambda item: -item[0])
        return [item[1] for item in scored[:limit]]

    def count_memories(self):
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def delete_memory(self, memory_id):
        with self._lock, self._db:
            cur = self._db.execute(
                "DELETE FROM memories WHERE id = ?", (memory_id,)
            )
            return cur.rowcount > 0

    def delete_matching(self, query):
        """Delete memories whose content contains the query (case-insensitive)."""
        query = (query or "").strip().lower()
        if not query:
            return 0
        with self._lock, self._db:
            rows = self._db.execute("SELECT id, content FROM memories").fetchall()
            ids = [r["id"] for r in rows if query in r["content"].lower()]
            for mid in ids:
                self._db.execute("DELETE FROM memories WHERE id = ?", (mid,))
            return len(ids)

    def clear_memories(self):
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM memories")
            return cur.rowcount

    # ------------------------------------------------------------------
    # conversation checkpoint
    # ------------------------------------------------------------------
    def save_checkpoint(self, topic, last_user, last_ai):
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO checkpoints (id, topic, last_user, last_ai, ended_at) "
                "VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET topic=excluded.topic, "
                "last_user=excluded.last_user, last_ai=excluded.last_ai, "
                "ended_at=excluded.ended_at",
                (topic or "", last_user or "", last_ai or "", time.time()),
            )

    def get_checkpoint(self):
        with self._lock:
            row = self._db.execute(
                "SELECT topic, last_user, last_ai, ended_at FROM checkpoints WHERE id = 1"
            ).fetchone()
        return dict(row) if row else None

    def clear_checkpoint(self):
        with self._lock, self._db:
            self._db.execute("DELETE FROM checkpoints WHERE id = 1")

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------
    def get_setting(self, key, default=None):
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return DEFAULT_SETTINGS.get(key, default)
        return row["value"]

    def set_setting(self, key, value):
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def all_settings(self):
        out = dict(DEFAULT_SETTINGS)
        with self._lock:
            for r in self._db.execute("SELECT key, value FROM settings"):
                out[r["key"]] = r["value"]
        return out

    # typed helpers ------------------------------------------------------
    def memory_enabled(self):
        return self.get_setting("memory_enabled", "1") == "1"

    def proactive_enabled(self):
        return self.get_setting("proactive_enabled", "1") == "1"

    def inactivity_seconds(self):
        try:
            return max(30, min(1800, int(self.get_setting("inactivity_seconds", "120"))))
        except (TypeError, ValueError):
            return 120

    def close(self):
        with self._lock:
            self._db.close()
