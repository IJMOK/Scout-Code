#!/usr/bin/env python3
"""How fast and how good is the AI on this Pi?

Sends real scout-style requests for the starter games to llama-server and
reports, for each one, the time taken and whether the AI's edits actually
applied to the game. Use it to choose between models:

    /opt/scout/venv/bin/python setup/benchmark.py
    /opt/scout/venv/bin/python setup/benchmark.py --url http://scout-worker.local:8080

Rule of thumb for a 2-3 hour session: aim for under ~90 seconds per request
and at least 7 out of 10 edits applying cleanly.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import prompts  # noqa: E402
from server.edits import apply_reply, parse_reply  # noqa: E402
from server.grammar import EDIT_GRAMMAR  # noqa: E402

CASES = [
    ("space-shooter", "make the player a dragon 🐉 and the enemies ghosts 👻"),
    ("catch", "make it rain sweets instead of fruit"),
    ("snake", "make the snake rainbow coloured"),
    ("flappy", "make the gap get smaller every time I score"),
    ("breakout", "make the paddle wider and the ball faster"),
    ("dodge", "add a shield power-up that protects me for 3 seconds"),
    ("platformer", "let me double jump"),
    ("maze", "make the ghosts move twice as fast"),
    ("space-shooter", "add a boss that appears every 100 points"),
    ("catch", "add a golden star that gives an extra life"),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--key-file", default="/opt/scout/llm-key")
    ap.add_argument("--cases", type=int, default=len(CASES), help="how many requests to try (max 10)")
    ap.add_argument("--max-tokens", type=int, default=900)
    ap.add_argument("--show", action="store_true", help="print the AI's raw reply for requests that failed")
    ap.add_argument("--show-all", action="store_true", help="print every raw reply")
    ap.add_argument("--no-grammar", action="store_true", help="don't force the edit format (to compare)")
    args = ap.parse_args()

    headers = {}
    key_path = Path(args.key_file)
    if key_path.exists():
        headers["Authorization"] = f"Bearer {key_path.read_text().strip()}"

    client = httpx.Client(base_url=args.url, headers=headers, timeout=900)
    try:
        props = client.get("/props").json()
        model = Path(props.get("model_path", "?")).name
    except Exception:
        model = "?"
    print(f"Model: {model}   Server: {args.url}   Grammar: {'off' if args.no_grammar else 'on'}\n")
    print(f"{'#':>2}  {'game':<14} {'prompt':>7} {'read s':>7} {'gen tok':>7} {'tok/s':>6} {'total s':>8}  result")

    ok = 0
    totals = []
    for i, (starter, request) in enumerate(CASES[: args.cases], 1):
        code = (ROOT / "server" / "starters" / f"{starter}.html").read_text(encoding="utf-8")
        start = time.monotonic()
        body = {
            "messages": prompts.edit_messages(code, request),
            "max_tokens": args.max_tokens,
            "temperature": 0.2,
            "cache_prompt": True,
        }
        if not args.no_grammar:
            body["grammar"] = EDIT_GRAMMAR
        r = client.post("/v1/chat/completions", json=body)
        r.raise_for_status()
        total = time.monotonic() - start
        data = r.json()
        reply = data["choices"][0]["message"]["content"]
        t = data.get("timings", {})
        result = apply_reply(code, parse_reply(reply))
        verdict = "✅ applied" if result.ok else f"❌ {(result.errors or ['no edits'])[0][:50]}"
        ok += result.ok
        totals.append(total)
        print(f"{i:>2}  {starter:<14} {t.get('prompt_n', 0):>7} {t.get('prompt_ms', 0) / 1000:>7.1f} "
              f"{t.get('predicted_n', 0):>7} {t.get('predicted_per_second', 0):>6.1f} {total:>8.1f}  {verdict}")
        if args.show_all or (args.show and not result.ok):
            print("    ┌─ AI reply " + "─" * 50)
            for line in reply.splitlines():
                print("    │ " + line)
            print("    └" + "─" * 61)

    n = len(totals)
    print(f"\nEdits that applied: {ok}/{n}    Average time per request: {sum(totals) / n:.0f}s")
    print("(The browser's test-play then catches crashes and asks the AI to fix them.)")


if __name__ == "__main__":
    main()
