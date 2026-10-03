"""Tiny health reporter that runs on each Pi (standard library only).

    python3 -m server.stats_agent --port 8099

GET /stats -> {"temp_c": 61.3, "load": 3.9, "mem_used_pct": 41, "throttled": false}
The leader dashboard shows these so you can spot a Pi that is overheating.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


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
    if shutil.which("vcgencmd"):
        try:
            out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
            # throttled=0x0 means all good. Bit 2 = currently throttled, bit 0 = under-voltage.
            value = int(out.strip().split("=")[1], 16)
            stats["throttled"] = bool(value & 0b101)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            pass
    return stats


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server naming)
        if self.path.rstrip("/") != "/stats":
            self.send_error(404)
            return
        body = json.dumps(read_stats()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
