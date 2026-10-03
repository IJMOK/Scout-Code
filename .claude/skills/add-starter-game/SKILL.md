---
name: add-starter-game
description: Add or change a Scout Code starter game in server/starters/. Use when asked to create a new starter template, edit an existing one, or update the idea cards scouts see in the studio.
---

# Adding a starter game

Starter games are what scouts (aged 10-14, no coding experience) begin from.
A small local AI on a Raspberry Pi then edits them with SEARCH/REPLACE blocks,
so starters must be **short, clear and easy for a 3B model to edit**.

## Rules every starter must follow

1. **One self-contained HTML file** at `server/starters/<id>.html`. No `<script src>`, no images, no fonts, no fetch: it must work offline in a sandboxed iframe (`sandbox="allow-scripts"`, CSP `default-src 'none'`). Draw with emoji and canvas shapes. Sound only via the `beep()` Web Audio helper.
2. **Copy the skeleton of an existing starter** (e.g. `catch.html`): the same `<style>`, an 800×500 canvas, `keys` handling on `window`, `beep`, `drawEmoji`, `drawText`, `state` = `"start" | "playing" | "gameover"`, and `function loop() { update(); draw(); requestAnimationFrame(loop); }`. The mock AI and the test harness rely on `requestAnimationFrame(loop);` being present.
3. **`const CONFIG = { ... };` comes first in the script**, with every tweakable value in it: emojis as strings, colours as `"#rrggbb"`, numbers with a short `//` comment. The idea cards and many scout requests only need CONFIG edits.
4. **Space starts or restarts the game.** Arrow keys and space are the only controls (the browser test presses exactly these).
5. **Keep it under ~210 lines.** Every line is re-read by the Pi on every request, so long files make every request slower.
6. Comments are for kids: short, friendly, and saying *what* happens ("// Gravity pulls you down").
7. Nothing scary or violent beyond cartoon arcade fare.

## Register it

Add an entry to `server/starters/starters.json`: `id` (the filename without `.html`), `title`, `emoji`, a one-line `blurb`, and 4 `ideas`. Ideas should be small, achievable in one AI edit, and fun.

## Check it

```bash
pytest tests/test_browser.py -k starter   # loads every starter, presses keys, fails on any JS error
pytest                                     # everything else
```

If a real Pi is available, also run `setup/benchmark.py` with a case for the new game (add one to `CASES`) and check that the edits apply.
