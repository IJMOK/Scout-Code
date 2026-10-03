"""Tiny helper that runs on each Pi (standard library only).

    python3 -m server.stats_agent --port 8099 --key-file /opt/scout/llm-key

GET  /stats    -> {"temp_c": 61.3, "load": 3.9, "mem_used_pct": 41, "throttled": false, "can_shutdown": true}
POST /shutdown -> powers the Pi off cleanly after a short delay. Needs the
                  same secret key as the AI server ("Authorization: Bearer <key>"),
                  so only the portal can do it, never a scout on the Wi-Fi.

The leader dashboard uses /stats to spot an overheating Pi, and /shutdown for
its "Shut down both Pis" button. Shutting down needs the sudo rule that
setup/update-services.sh installs (see setup/lib.sh).
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import shlex
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODELS_DIR = Path(os.environ.get("SCOUT_MODELS_DIR", "/opt/scout/models"))

# Overridable so tests never switch anything off.
POWEROFF_CMD = shlex.split(os.environ.get("SCOUT_POWEROFF_CMD", "sudo -n /usr/bin/systemctl poweroff"))


def read_stats() -> dict:
    stats: dict = {}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            stats["temp_c"] = round(int(f.read().strip()) / 1000, 1)
    except (OSError, ValueError):
        pass
    try:
        stats["load"] = round(os.getloadavg()[0], 2)
    except OSError:
        pass
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, val = line.split(":", 1)
                info[key] = int(val.strip().split()[0])
        stats["mem_used_pct"] = round(100 * (1 - info["MemAvailable"] / info["MemTotal"]))
    except (OSError, KeyError, ValueError):
        pass
    try:
        # Which AI model this Pi is running (current.gguf is a link to it).
        stats["model"] = Path(os.readlink(MODELS_DIR / "current.gguf")).name
    except OSError:
        pass
    if shutil.which("vcgencmd"):
        try:
            out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
            # throttled=0x0 means all good. Bit 2 = currently throttled, bit 0 = under-voltage.
            value = int(out.strip().split("=")[1], 16)
            stats["throttled"] = bool(value & 0b101)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            pass
    return stats


def shutdown_allowed() -> bool:
    """Can this user power the Pi off without a password? (Checked once at start-up.)"""
    if POWEROFF_CMD[:2] != ["sudo", "-n"]:
        return True  # a test command
    try:
        check = subprocess.run(["sudo", "-n", "-l", *POWEROFF_CMD[2:]], capture_output=True, timeout=5)
        return check.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Handler(BaseHTTPRequestHandler):
    key: str | None = None
    can_shutdown: bool = False

    def do_GET(self):  # noqa: N802 (http.server naming)
        if self.path.rstrip("/") != "/stats":
            self.send_error(404)
            return
        self._json(200, {**read_stats(), "can_shutdown": bool(self.key and self.can_shutdown)})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != "/shutdown":
            self.send_error(404)
            return
        given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not self.key or not hmac.compare_digest(given.encode(), self.key.encode()):
            self._json(403, {"error": "wrong or missing key"})
            return
        if not self.can_shutdown:
            self._json(409, {"error": "this Pi isn't allowed to shut itself down; run setup/update-services.sh"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            delay = float(json.loads(self.rfile.read(length) or b"{}").get("delay", 2))
        except (ValueError, json.JSONDecodeError):
            delay = 2
        delay = min(max(delay, 0), 30)
        # Answer first, then power off, so the portal hears back.
        threading.Timer(delay, lambda: subprocess.run(POWEROFF_CMD)).start()
        self._json(202, {"ok": True, "in_seconds": delay})

    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def make_server(host: str, port: int, key_file: str | None) -> ThreadingHTTPServer:
    Handler.key = Path(key_file).read_text().strip() if key_file and Path(key_file).exists() else None
    Handler.can_shutdown = shutdown_allowed()
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--key-file", help="the AI key file; without it /shutdown is disabled")
    args = parser.parse_args()
    make_server(args.host, args.port, args.key_file).serve_forever()


if __name__ == "__main__":
    main()
