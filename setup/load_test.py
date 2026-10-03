#!/usr/bin/env python3
"""Pretend to be a room full of scouts, to check the queue before the event.

Creates N teams, has them all ask for a change at the same moment, and reports
how long each one waited. Works against the real Pis or the mock AI:

    python setup/load_test.py --url http://scout.local --leader-pin 123456 --teams 6

Test teams are named "Load Test 1" and so on. Delete data/scout.db
afterwards (or use a fresh SCOUT_DATA_DIR) for a clean start.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import time

import httpx

REQUESTS = ["make it red", "make the player a 🐸", "make it faster", "make the background black",
            "make everything slower", "make it pink"]


def run_team(url: str, join: str, n: int, request: str) -> dict:
    c = httpx.Client(base_url=url, timeout=900)
    r = c.post("/api/teams", json={"name": f"Load Test {n} {int(time.time()) % 10000}", "emoji": "🦊",
                                   "join_code": join})
    r.raise_for_status()
    game = c.post("/api/games", json={"starter": "space-shooter"}).json()["id"]
    start = time.monotonic()
    c.post(f"/api/games/{game}/ask", json={"request": request}).raise_for_status()
    while True:
        g = c.get(f"/api/games/{game}").json()
        if g["pending_test_version_id"]:
            # A real browser would test-play it here; we just say it worked.
            c.post(f"/api/versions/{g['pending_test_version_id']}/test", json={"ok": True})
            return {"team": n, "seconds": round(time.monotonic() - start, 1), "result": "new version"}
        if g["active_job"] is None:
            return {"team": n, "seconds": round(time.monotonic() - start, 1), "result": "AI gave up"}
        time.sleep(0.5)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--leader-pin", required=True)
    ap.add_argument("--teams", type=int, default=6)
    args = ap.parse_args()

    leader = httpx.Client(base_url=args.url, timeout=30)
    leader.post("/api/leader/login", json={"pin": args.leader_pin}).raise_for_status()
    join = leader.get("/api/leader/status").json()["join_code"]

    print(f"{args.teams} teams asking at once…")
    with cf.ThreadPoolExecutor(args.teams) as pool:
        futures = [pool.submit(run_team, args.url, join, i + 1, REQUESTS[i % len(REQUESTS)])
                   for i in range(args.teams)]
        results = sorted((f.result() for f in futures), key=lambda r: r["seconds"])
    for r in results:
        print(f"  team {r['team']:>2}: {r['seconds']:>6}s  {r['result']}")
    print(f"Longest wait: {results[-1]['seconds']}s")


if __name__ == "__main__":
    main()
