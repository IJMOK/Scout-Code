"""SQLite storage. One small file, safe to copy to a USB stick after the event."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  emoji TEXT NOT NULL,
  pin TEXT NOT NULL,
  token TEXT NOT NULL UNIQUE,
  last_worker TEXT,
  demo INTEGER NOT NULL DEFAULT 0,  -- the leaders' demo team: not in awards, export or online
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
  id INTEGER PRIMARY KEY,
  team_id INTEGER NOT NULL REFERENCES teams(id),
  starter TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  current_version_id INTEGER,
  published_version_id INTEGER,
  hidden INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  published_at REAL
);
CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY,
  game_id INTEGER NOT NULL REFERENCES games(id),
  parent_id INTEGER,
  code TEXT NOT NULL,
  request TEXT NOT NULL DEFAULT '',
  plan TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,           -- ok | testing | broken
  error TEXT NOT NULL DEFAULT '',
  job_id INTEGER,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  team_id INTEGER NOT NULL REFERENCES teams(id),
  game_id INTEGER NOT NULL REFERENCES games(id),
  kind TEXT NOT NULL,             -- edit | fix | explain
  priority INTEGER NOT NULL,
  request TEXT NOT NULL,
  snippet TEXT NOT NULL DEFAULT '',
  error_in TEXT NOT NULL DEFAULT '',
  base_version_id INTEGER,
  attempt INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,           -- queued | running | testing | done | failed | cancelled
  plan TEXT NOT NULL DEFAULT '',
  reply TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL DEFAULT '',
  worker TEXT,
  tokens INTEGER NOT NULL DEFAULT 0,
  result_version_id INTEGER,
  created_at REAL NOT NULL,
  started_at REAL,
  finished_at REAL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS ratings (
  game_id INTEGER NOT NULL REFERENCES games(id),
  team_id INTEGER NOT NULL REFERENCES teams(id),
  stars INTEGER NOT NULL,
  reaction TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  PRIMARY KEY (game_id, team_id)
);
CREATE TABLE IF NOT EXISTS votes (
  category TEXT NOT NULL,
  team_id INTEGER NOT NULL REFERENCES teams(id),
  game_id INTEGER NOT NULL REFERENCES games(id),
  PRIMARY KEY (category, team_id)
);
"""


class DB:
    """A single shared connection guarded by a lock: plenty for a dozen scouts."""

    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Bring databases from older versions (and saved events) up to date."""
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(teams)")}
        if "demo" not in columns:
            self.conn.execute("ALTER TABLE teams ADD COLUMN demo INTEGER NOT NULL DEFAULT 0")

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, params)
            return cur.lastrowid if cur.lastrowid else cur.rowcount

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def value(self, sql: str, params: tuple | dict = ()) -> Any:
        with self.lock:
            row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else None

    # --- settings ---
    def get_setting(self, key: str, default: str = "") -> str:
        v = self.value("SELECT value FROM settings WHERE key=?", (key,))
        return default if v is None else v

    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def flag(self, key: str) -> bool:
        return self.get_setting(key, "0") == "1"


def now() -> float:
    return time.time()
