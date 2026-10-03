"""Settings, read from a JSON file plus environment variables.

Example /opt/scout/config.json on the basecamp Pi:

    {
      "event_name": "1st Anytown Scouts - Game Jam",
      "workers": [
        {"name": "basecamp", "llm": "http://127.0.0.1:8080", "stats": "http://127.0.0.1:8099"},
        {"name": "worker",   "llm": "http://worker.local:8080", "stats": "http://worker.local:8099"}
      ]
    }

Environment overrides: SCOUT_CONFIG (path to that file), SCOUT_DATA_DIR,
SCOUT_LEADER_PIN, SCOUT_MOCK=1 (fake AI for development), SCOUT_MOCK_DELAY.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class WorkerConfig:
    name: str
    llm: str
    stats: str | None = None
    api_key: str | None = None
    api_key_file: str | None = None

    def key(self) -> str | None:
        """The llama-server --api-key, given directly or in a file."""
        if self.api_key:
            return self.api_key
        if self.api_key_file and Path(self.api_key_file).exists():
            return Path(self.api_key_file).read_text().strip() or None
        return None


@dataclass
class Settings:
    data_dir: Path
    event_name: str = "Scout Code Game Jam"
    workers: list[WorkerConfig] = field(default_factory=list)
    mock: bool = False
    mock_delay: float = 0.01
    leader_pin: str = ""
    edit_max_tokens: int = 900
    explain_max_tokens: int = 200
    temperature: float = 0.2
    request_timeout: float = 600.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "scout.db"


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("SCOUT_DATA_DIR", ROOT / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = Path(os.environ.get("SCOUT_CONFIG", data_dir / "config.json"))
    raw: dict = {}
    if cfg_path.exists():
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))

    s = Settings(data_dir=data_dir)
    s.event_name = raw.get("event_name", s.event_name)
    s.workers = [WorkerConfig(**w) for w in raw.get("workers", [])]
    s.edit_max_tokens = int(raw.get("edit_max_tokens", s.edit_max_tokens))
    s.explain_max_tokens = int(raw.get("explain_max_tokens", s.explain_max_tokens))
    s.temperature = float(raw.get("temperature", s.temperature))
    s.mock = os.environ.get("SCOUT_MOCK", str(raw.get("mock", ""))).lower() in ("1", "true", "yes")
    s.mock_delay = float(os.environ.get("SCOUT_MOCK_DELAY", raw.get("mock_delay", s.mock_delay)))

    if not s.workers and not s.mock:
        # Sensible default: one llama-server on this machine.
        s.workers = [WorkerConfig(name="local", llm="http://127.0.0.1:8080")]

    s.leader_pin = os.environ.get("SCOUT_LEADER_PIN") or raw.get("leader_pin") or _stored_leader_pin(data_dir)
    return s


def _stored_leader_pin(data_dir: Path) -> str:
    """Make a leader PIN on first run and keep it in data/leader-pin.txt."""
    path = data_dir / "leader-pin.txt"
    if path.exists():
        return path.read_text().strip()
    pin = f"{secrets.randbelow(1_000_000):06d}"
    path.write_text(pin + "\n")
    return pin
