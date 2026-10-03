#!/usr/bin/env python3
"""How fast and how good is the AI on this Pi?

Sends real scout-style requests for the starter games to llama-server and
handles each one like the studio does (one try, then one automatic retry).
For each it reports the time taken, whether the AI's edits applied, and
whether the edited game still looks like working code.

    /opt/scout/venv/bin/python setup/benchmark.py --show
    /opt/scout/venv/bin/python setup/benchmark.py --url http://scout-worker.local:8080

Compare models side by side (switches the AI model, then puts yours back):

    sudo /opt/scout/venv/bin/python setup/benchmark.py --compare 3b 4b

Rule of thumb for a 2-3 hour session: aim for under ~90 seconds per request
and at least 8 out of 10 working games.

"read s" is the time the Pi spends reading the game before it writes anything.
It is long the first time a Pi sees a game and short once it's cached; the
portal pre-loads ("warms up") all the starters so scouts mostly get the
short version. Use --repeat to see both.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
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

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/opt/scout/models"))
# Same names as setup/download-models.sh
MODEL_FILES = {
    "1.5b": "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
    "3b": "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
    "4b": "qwen3-4b-instruct-2507-q4_k_m.gguf",
    "7b": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
}
SAVE_DIR = Path("/tmp/scout-compare")

LABELS = {
    "first": "✅ first try",
    "retry": "✅ after retry",
    "partial": "⚠️ partly, after retry",
    "broken": "💥 applied but broken",
    "failed": "❌",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--key-file", default="/opt/scout/llm-key")
    ap.add_argument("--cases", type=int, default=len(CASES), help="how many requests to try (max 10)")
    ap.add_argument("--max-tokens", type=int, default=900)
    ap.add_argument("--show", action="store_true", help="print the AI's raw replies for requests that needed a retry")
    ap.add_argument("--show-all", action="store_true", help="print every raw reply")
    ap.add_argument("--no-grammar", action="store_true", help="don't force the edit format (to compare)")
    ap.add_argument("--repeat", action="store_true",
                    help="run everything twice; the second pass shows speed once games are cached")
    ap.add_argument("--compare", nargs="+", metavar="MODEL",
                    help="compare models, e.g. --compare 3b 4b (needs sudo; restores your model afterwards)")
    ap.add_argument("--force", action="store_true",
                    help="with --compare: try models even if they look too big for this Pi's memory")
    args = ap.parse_args()

    client = make_client(args)
    restore_after_crash()
    if args.compare:
        compare_models(client, args)
        return
    if not wait_until_ready(client):
        sys.exit("The AI server isn't ready. Check it with: sudo journalctl -u scout-llm -n 30 --no-pager")
    print(f"Model: {model_name(client)}   Server: {args.url}   Grammar: {'off' if args.no_grammar else 'on'}\n")
    for pass_no in range(1, 3 if args.repeat else 2):
        if args.repeat:
            print(f"--- Pass {pass_no} {'(games now cached: this is what scouts feel)' if pass_no == 2 else ''}")
        summarise(run_cases(client, args))


# --------------------------------------------------------------------------- talking to the AI

def make_client(args) -> httpx.Client:
    headers = {}
    key_path = Path(args.key_file)
    if key_path.exists():
        headers["Authorization"] = f"Bearer {key_path.read_text().strip()}"
    return httpx.Client(base_url=args.url, headers=headers, timeout=900)


def model_name(client: httpx.Client) -> str:
    try:
        return Path(client.get("/props").json().get("model_path", "?")).name
    except Exception:
        return "?"


def wait_until_ready(client: httpx.Client, limit: float = 300) -> bool:
    """llama-server answers 503 while it is still loading the model (e.g. just after a restart)."""
    start = time.monotonic()
    said = False
    while time.monotonic() - start < limit:
        try:
            if client.get("/health", timeout=5).status_code == 200:
                if said:
                    print(" ready!\n")
                return True
        except httpx.HTTPError:
            pass  # not listening yet
        if not said:
            print("Waiting for the AI to finish loading the model", end="", flush=True)
            said = True
        print(".", end="", flush=True)
        time.sleep(3)
    print()
    return False


def ask(client: httpx.Client, args, messages: list[dict]) -> tuple[str, dict, float]:
    body = {"messages": messages, "max_tokens": args.max_tokens, "temperature": 0.2, "cache_prompt": True}
    if not args.no_grammar:
        body["grammar"] = EDIT_GRAMMAR
    start = time.monotonic()
    r = client.post("/v1/chat/completions", json=body)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"], data.get("timings", {}), time.monotonic() - start


def warm_up(client: httpx.Client, cases) -> None:
    """Pre-load each game, exactly like the portal does at start-up."""
    games = list(dict.fromkeys(starter for starter, _ in cases))
    print(f"Warming up {len(games)} games", end="", flush=True)
    for starter in games:
        code = (ROOT / "server" / "starters" / f"{starter}.html").read_text(encoding="utf-8")
        body = {"messages": prompts.edit_messages(code, ""), "max_tokens": 1, "cache_prompt": True}
        client.post("/v1/chat/completions", json=body).raise_for_status()
        print(".", end="", flush=True)
    print(" done\n")


# --------------------------------------------------------------------------- running the cases

def run_cases(client: httpx.Client, args, save_to: Path | None = None) -> list[dict]:
    """Each request is handled like the studio does: one try, then one retry if it didn't fit."""
    print(f"{'#':>2}  {'game':<14} {'prompt':>7} {'read s':>7} {'gen tok':>7} {'tok/s':>6} {'total s':>8}  result")
    results = []
    for i, (starter, request) in enumerate(CASES[: args.cases], 1):
        code = (ROOT / "server" / "starters" / f"{starter}.html").read_text(encoding="utf-8")
        reply, t, total = ask(client, args, prompts.edit_messages(code, request))
        result = apply_reply(code, parse_reply(reply))
        retry_reply = None
        outcome = "first"
        if not result.ok:
            error = " ".join(result.errors)
            retry_reply, _, total2 = ask(client, args, prompts.retry_messages(code, request, error))
            total += total2
            result_again = apply_reply(code, parse_reply(retry_reply), allow_partial=True)
            outcome = ("partial" if result_again.partial else "retry") if result_again.ok else "failed"
            failed_errors, result = result.errors, result_again
        problem = looks_broken(result.code) if result.ok else None
        if problem:
            outcome = "broken"

        verdict = LABELS[outcome]
        if outcome == "failed":
            verdict += " " + (result.errors or ["no edits"])[0][:50]
        if problem:
            verdict += f" ({problem[:40]})"
        print(f"{i:>2}  {starter:<14} {t.get('prompt_n', 0):>7} {t.get('prompt_ms', 0) / 1000:>7.1f} "
              f"{t.get('predicted_n', 0):>7} {t.get('predicted_per_second', 0):>6.1f} {total:>8.1f}  {verdict}")
        if args.show_all or (args.show and (retry_reply is not None or problem)):
            show("AI reply" if retry_reply is None else "first try", reply)
            if retry_reply is not None:
                show(f"retry (told: {' '.join(failed_errors)[:40]}…)", retry_reply)

        if save_to and result.ok:
            save_to.mkdir(parents=True, exist_ok=True)
            (save_to / f"{i:02d}-{starter}.html").write_text(result.code, encoding="utf-8")
        results.append({"starter": starter, "outcome": outcome, "seconds": total,
                        "read_s": t.get("prompt_ms", 0) / 1000, "tok_s": t.get("predicted_per_second", 0)})
    return results


def summarise(results: list[dict]) -> dict:
    n = len(results)
    first = sum(r["outcome"] == "first" for r in results)
    applied = sum(r["outcome"] in ("first", "retry", "partial", "broken") for r in results)
    working = sum(r["outcome"] in ("first", "retry", "partial") for r in results)
    avg = sum(r["seconds"] for r in results) / n
    reads = sum(r["read_s"] for r in results) / n
    speeds = [r["tok_s"] for r in results if r["tok_s"]]
    tok_s = sum(speeds) / len(speeds) if speeds else 0
    print(f"\nApplied first try: {first}/{n}    With the automatic retry: {applied}/{n}    "
          f"Still working code: {working}/{n}")
    print(f"Average per request: {avg:.0f}s (of which reading the game: {reads:.0f}s)")
    print("(In the studio the browser then test-plays each new version and asks the AI to fix any crash.)\n")
    return {"n": n, "first": first, "applied": applied, "working": working, "avg_s": avg, "tok_s": tok_s}


def show(label: str, reply: str) -> None:
    print(f"    ┌─ {label} " + "─" * max(4, 58 - len(label)))
    for line in reply.splitlines():
        print("    │ " + line)
    print("    └" + "─" * 61)


# --------------------------------------------------------------------------- "does it still work?"

SCRIPT_RE = re.compile(r"<script(?:\s[^>]*)?>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def looks_broken(html: str) -> str | None:
    """A quick check that the game's JavaScript still parses. None means it looks fine.

    Uses Node.js when it's installed (exact), otherwise a bracket check that
    catches the usual small-model slips (a missing or extra { } ( ) [ ]).
    The studio's in-browser test-play is the real check; this is for scoring.
    """
    js = "\n".join(SCRIPT_RE.findall(html))
    node = shutil.which("node")
    if node:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(js)
        try:
            out = subprocess.run([node, "--check", f.name], capture_output=True, text=True, timeout=20)
        finally:
            os.unlink(f.name)
        if out.returncode != 0:
            lines = [ln for ln in out.stderr.splitlines() if "Error" in ln]
            return lines[0].strip() if lines else "JavaScript syntax error"
        return None
    return bracket_problem(js)


def bracket_problem(js: str) -> str | None:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    i, n = 0, len(js)
    while i < n:
        c = js[i]
        nxt = js[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            i = js.find("\n", i)
            if i == -1:
                break
            continue
        if c == "/" and nxt == "*":
            end = js.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if c in "'\"`":
            i += 1
            while i < n and js[i] != c:
                if js[i] == "\\":
                    i += 1
                elif c != "`" and js[i] == "\n":
                    return "a string is missing its closing quote"
                i += 1
            i += 1
            continue
        if c in "([{":
            stack.append(c)
        elif c in ")]}":
            if not stack or stack[-1] != pairs[c]:
                return f"unexpected '{c}'"
            stack.pop()
        i += 1
    if stack:
        return f"missing a closing bracket for '{stack[-1]}'"
    return None


# --------------------------------------------------------------------------- comparing models

def model_path(name: str) -> Path:
    if name.lower() in MODEL_FILES:
        return MODELS_DIR / MODEL_FILES[name.lower()]
    return Path(name)


def systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, check=check)


def switch_model(path: Path) -> None:
    link = MODELS_DIR / "current.gguf"
    tmp = MODELS_DIR / ".current.gguf.new"
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    tmp.symlink_to(path)
    os.replace(tmp, link)  # swap the link in one step
    systemctl("restart", "scout-llm")


# --- crash safety: if the Pi dies mid-compare, the next run (or update-services.sh) puts the model back

def restore_marker() -> Path:
    return MODELS_DIR / ".compare-restore"


def restore_after_crash() -> bool:
    marker = restore_marker()
    if not marker.exists():
        return False
    target = Path(marker.read_text().strip())
    print(f"⚠️  A model comparison didn't finish last time (the Pi may have restarted).\n"
          f"   Putting the AI back on {target.name}…")
    if os.geteuid() != 0:
        sys.exit("   Please run this once with sudo so it can switch the model back.")
    switch_model(target)
    marker.unlink()
    print("   Done.\n")
    return True


# --- "will this model fit in the Pi's memory?"

CTX_SIZE = 8192          # matches setup/systemd/scout-llm.service
CACHE_RAM = 2048 * 2**20  # --cache-ram 2048
HEADROOM = 2**30          # the system, the website and llama.cpp's working buffers
SAFE_FRACTION = 0.8       # keep a fifth of the RAM free: a Pi that runs out simply freezes


def gguf_metadata(path: Path, wanted: tuple[str, ...] = ("block_count", "head_count_kv", "head_count",
                                                          "key_length", "value_length", "embedding_length")) -> dict:
    """Read the few numbers we need from a GGUF file's header (no libraries needed)."""
    import struct

    scalar = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
    found: dict = {}
    with open(path, "rb") as f:
        def read(fmt):
            size = struct.calcsize("<" + fmt)
            return struct.unpack("<" + fmt, f.read(size))[0]

        def read_str():
            return f.read(read("Q")).decode("utf-8", "replace")

        def read_value(vtype):
            if vtype in scalar:
                return read(scalar[vtype])
            if vtype == 8:
                return read_str()
            if vtype == 9:
                item_type, count = read("I"), read("Q")
                if item_type in scalar:  # numbers: keep small arrays, skip big ones
                    size = struct.calcsize("<" + scalar[item_type])
                    if count <= 1024:
                        return [read(scalar[item_type]) for _ in range(count)]
                    f.seek(size * count, 1)
                    return None
                for _ in range(count):  # strings, e.g. the tokenizer's vocabulary
                    read_value(item_type) if item_type != 8 else f.seek(read("Q"), 1)
                return None
            raise ValueError(f"unknown GGUF value type {vtype}")

        if f.read(4) != b"GGUF":
            raise ValueError("not a GGUF file")
        try:
            read("I")  # version
            read("Q")  # tensor count
            n_keys = read("Q")
        except struct.error as e:
            raise ValueError("GGUF header is cut short") from e
        for _ in range(n_keys):
            key, value = read_str(), read_value(read("I"))
            if key == "general.architecture":
                found["architecture"] = value
            elif key.split(".")[-1] in wanted and key.startswith(found.get("architecture", "") + "."):
                found[key.split(".")[-1]] = value
    return found


def estimated_memory(path: Path) -> int:
    """Bytes the AI service needs with this model: weights + context + prompt cache + headroom."""
    size = path.stat().st_size
    try:
        meta = gguf_metadata(path)
        kv_heads = meta.get("head_count_kv") or meta["head_count"]
        kv_heads = max(kv_heads) if isinstance(kv_heads, list) else kv_heads
        head_count = meta["head_count"]
        head_count = max(head_count) if isinstance(head_count, list) else head_count
        k_dim = meta.get("key_length") or meta["embedding_length"] // head_count
        v_dim = meta.get("value_length") or k_dim
        kv_per_token = meta["block_count"] * kv_heads * (k_dim + v_dim) * 2  # f16
        return size + kv_per_token * CTX_SIZE + CACHE_RAM + HEADROOM
    except Exception:  # can't read it (truncated, unknown type, ...): assume the worst
        return int(size * 2.5) + CACHE_RAM


def total_memory() -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def too_big(path: Path) -> str | None:
    need, have = estimated_memory(path), total_memory()
    if have and need > have * SAFE_FRACTION:
        return (f"needs about {need / 2**30:.1f} GB but this Pi has {have / 2**30:.1f} GB "
                f"and should keep a fifth free")
    return None


def compare_models(client: httpx.Client, args) -> None:
    if os.geteuid() != 0:
        sys.exit("--compare switches the AI model, so run it with sudo:\n"
                 "  sudo /opt/scout/venv/bin/python setup/benchmark.py --compare 3b 4b")
    paths = [model_path(m) for m in args.compare]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        sys.exit("Not downloaded yet: " + ", ".join(missing) + "\nRun: ./setup/download-models.sh "
                 + " ".join(args.compare))

    link = MODELS_DIR / "current.gguf"
    original = Path(os.readlink(link)) if link.is_symlink() else None
    if original:
        restore_marker().write_text(str(original))  # in case the Pi dies before we put it back
    portal_was_running = systemctl("is-active", "--quiet", "scout-portal", check=False).returncode == 0
    summaries = {}
    try:
        if portal_was_running:
            print("Pausing the website while models are compared (it'll be restarted at the end).\n")
            systemctl("stop", "scout-portal")
        for name, path in zip(args.compare, paths):
            print(f"=================== {name}: {path.name} ===================")
            problem = too_big(path)
            if problem and not getattr(args, "force", False):
                print(f"Skipping {name}: it {problem}. (Use --force to try anyway.)\n")
                continue
            switch_model(path)
            if not wait_until_ready(client, limit=600):
                print(f"{name} didn't load; skipping it. (sudo journalctl -u scout-llm -n 30)\n")
                continue
            warm_up(client, CASES[: args.cases])
            results = run_cases(client, args, save_to=SAVE_DIR / name)
            summaries[name] = summarise(results)
    except KeyboardInterrupt:
        print("\nStopped early.")
    finally:
        print("Putting things back as they were…")
        if original:
            switch_model(original)
        restore_marker().unlink(missing_ok=True)
        if portal_was_running:
            systemctl("start", "scout-portal")

    if summaries:
        print_comparison(summaries)
        print(f"\nThe edited games are saved in {SAVE_DIR}/<model>/ if you want to play them.")


def print_comparison(summaries: dict[str, dict]) -> None:
    print("\n" + "=" * 70)
    print(f"{'model':<8} {'first try':>10} {'with retry':>11} {'working games':>14} {'avg s':>7} {'tok/s':>6}")
    for name, s in summaries.items():
        print(f"{name:<8} {s['first']:>7}/{s['n']:<2} {s['applied']:>8}/{s['n']:<2} {s['working']:>11}/{s['n']:<2} "
              f"{s['avg_s']:>7.0f} {s['tok_s']:>6.1f}")
    best = min(summaries, key=lambda k: (-summaries[k]["working"], summaries[k]["avg_s"]))
    print(f"\nMost working games: {best}"
          + (" (the fastest of those that tied)" if sum(s["working"] == summaries[best]["working"]
                                                       for s in summaries.values()) > 1 else ""))
    print("To use it:  sudo ln -sf " + str(model_path(best)) + " " + str(MODELS_DIR / "current.gguf")
          + " && sudo systemctl restart scout-llm   (on both Pis)")


if __name__ == "__main__":
    main()
