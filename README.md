# 🎮🤖 Scout Code

**An offline AI game studio for Scouts aged 10-14.** Teams pick a starter game, then tell a local AI what to change: *"make the player a dragon"*, *"add a boss every 100 points"*. They watch the AI plan, write, test and fix the code, and see exactly which lines changed. Then they publish to a shared **Arcade**, where everyone plays and rates each other's games, and finish with an awards ceremony.

Everything runs on **two Raspberry Pi 5s with no internet**.

```
 Leader laptops (any browser) ──Wi-Fi──► travel router (no internet)
                                             │ ethernet
               ┌─────────────────────────────┴──────────────────────────┐
   Pi 1 "scout" (basecamp)                                    Pi 2 "scout-worker"
   • website: studio, arcade, leader dashboard                • AI (llama.cpp)
   • job queue
   • AI (llama.cpp)
```

## What the scouts do

1. **Join**: team name, emoji and the join code on the big screen. They get a 4-digit team PIN.
2. **Pick a starter**: Space Shooter, Coin Jumper, Snake, Maze Escape, Fruit Catcher, Flappy Chick, Brick Breaker or Meteor Dodge.
3. **Ask the AI** in plain English (idea cards help). They see it work through each step:
   ⏳ Waiting → 🤔 Planning → ✍️ Writing code → 🧪 Testing → 🔧 Fixing a bug → ✅ Done
4. **Read the code**: changed lines glow green. Highlight any code and press **💬 Explain this** for a kid-friendly explanation.
5. **History** lets them go back to any version that worked.
6. **Publish** to the Arcade, **play and rate** other teams' games (stars, reactions, award votes), then the **awards ceremony** on the projector.

## Why it's built this way

- **Speed on a Pi.** A Pi 5 writes roughly 5-8 words a second with a 3B model, far too slow to write a whole game. So teams start from a working, commented game, and the AI only writes **small SEARCH/REPLACE edits**. A request takes roughly 30-120 seconds (measure yours with `setup/benchmark.py`).
- **A real agent loop.** Each new version is **test-played automatically** in the scouts' browser. It gets a syntax check, then 3.5 seconds of play with simulated key presses. If it crashes, the AI gets the error and **fixes its own bug** once. If that fails too, the game stays on the last working version.
- **Two Pis, one queue.** One job per team at a time. Fixes jump the queue, and "explain" requests go last. Jobs go to whichever Pi is free, preferring the one that served that team last (its cache may still hold their game). If a Pi dies, its job moves to the other.
- **Safe by default.**
  - Games run in sandboxed iframes with no network access.
  - A word filter checks names, titles and requests (extend it in `data/blocked-words.txt`), and the system prompt keeps the AI on task.
  - The AI servers need a key, so nobody can chat to them directly.
  - No personal data is collected: just team names.
  - Leaders can hide games, pause the AI and stop jobs.

## Quick start for leaders

Full details are in **[docs/hardware.md](docs/hardware.md)** (what to buy and how to set it up) and **[docs/run-sheet.md](docs/run-sheet.md)** (how to run the session).

```bash
# On each Pi, while it still has internet:
git clone https://github.com/ijmok/scout-code.git && cd scout-code
sudo ./setup/install.sh --role basecamp              # first Pi (prints a key)
sudo ./setup/install.sh --role worker --key <KEY>    # second Pi

# Check speed and quality of the AI on each Pi
/opt/scout/venv/bin/python setup/benchmark.py
/opt/scout/venv/bin/python setup/benchmark.py --url http://scout-worker.local:8080
```

On the day:
- Scouts open **http://scout.local**, or the basecamp Pi's IP address if `.local` doesn't work on your laptops.
- Leaders open **http://scout.local/leader**. The PIN is printed at the end of the install and stored in `/opt/scout/data/leader-pin.txt`.
- Put **/leader** on the projector for the join code, then **/awards** at the end.
- **💾 Download all games** on the dashboard gives a zip of every game as a stand-alone HTML file, ready for USB sticks.
- **🔄 Start a new event** saves everything to *Past events*, then clears teams, games and votes for the next group. The Pis don't need restarting.

## Developing on a normal computer

No Pi or model needed: `SCOUT_MOCK=1` swaps in a fake AI that makes simple, sensible edits.

```bash
pip install -r requirements-dev.txt
SCOUT_MOCK=1 uvicorn server.app:create_app --factory --reload
# open http://127.0.0.1:8000  (leader PIN is in data/leader-pin.txt)

pytest                                 # unit, API and (if Playwright is installed) browser tests
python setup/load_test.py --url http://127.0.0.1:8000 --leader-pin <PIN> --teams 12
```

The mock understands emoji ("make the player a 🐸"), colours, "faster" and "slower". `BREAK` makes it write a crashing change, so you can watch the auto-fix, and `NOMATCH` makes it write an edit that can't be applied.

## Layout

| Path | What's there |
|---|---|
| `server/app.py` | FastAPI routes: teams, studio, arcade, leader, export |
| `server/jobqueue.py` | Queue, worker scheduling, the plan → write → test → fix loop, live events |
| `server/edits.py` | Forgiving SEARCH/REPLACE parser for small models |
| `server/prompts.py` | Everything the AI is told |
| `server/llm.py` | llama-server streaming client + the mock AI |
| `server/starters/` | The 8 starter games and their idea cards |
| `server/stats_agent.py` | Pi temperature/load reporter for the dashboard |
| `web/` | The pages (plain HTML/JS, no build step, no CDNs; libraries vendored in `web/vendor/`) |
| `setup/` | Pi install script, systemd units, model download, benchmark, load test |
| `.claude/skills/` | Guides for Claude Code when adding starter games or deploying |
