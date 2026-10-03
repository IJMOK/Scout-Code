from server.edits import apply_reply, parse_reply

GAME = """<!DOCTYPE html>
<html>
<script>
const CONFIG = {
  player: "🙂",
  speed: 5,
};
function update() {
  x += CONFIG.speed;
}
</script>
</html>
"""


def test_exact_block():
    reply = parse_reply(
        'PLAN: Make the player a dinosaur.\n'
        '<<<<<<< SEARCH\n  player: "🙂",\n=======\n  player: "🦖",\n>>>>>>> REPLACE\n'
    )
    assert reply.plan == "Make the player a dinosaur."
    res = apply_reply(GAME, reply)
    assert res.ok
    assert 'player: "🦖"' in res.code
    assert 'player: "🙂"' not in res.code


def test_indentation_forgiven_and_reindented():
    reply = parse_reply(
        "<<<<<<< SEARCH\nfunction update() {\nx += CONFIG.speed;\n}\n=======\n"
        "function update() {\n  x += CONFIG.speed * 2;\n}\n>>>>>>> REPLACE"
    )
    res = apply_reply(GAME, reply)
    assert res.ok, res.errors
    assert "  x += CONFIG.speed * 2;" in res.code


def test_fences_and_sloppy_markers():
    reply = parse_reply(
        "Sure!\n```js\n<<<<<<<SEARCH\n  speed: 5,\n=========\n  speed: 9,\n>>>>>>>REPLACE\n```"
    )
    res = apply_reply(GAME, reply)
    assert res.ok
    assert "speed: 9" in res.code


def test_missing_search_reports_error():
    reply = parse_reply("<<<<<<< SEARCH\n  lives: 3,\n=======\n  lives: 5,\n>>>>>>> REPLACE")
    res = apply_reply(GAME, reply)
    assert not res.ok
    assert "could not find" in res.errors[0]
    assert res.code == GAME


def test_multiple_blocks_partial_failure_is_not_ok():
    reply = parse_reply(
        "<<<<<<< SEARCH\n  speed: 5,\n=======\n  speed: 7,\n>>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\nnope\n=======\nyes\n>>>>>>> REPLACE\n"
    )
    res = apply_reply(GAME, reply)
    assert res.applied == 1
    assert not res.ok


def test_full_file_fallback():
    reply = parse_reply("Here you go:\n```html\n<!DOCTYPE html><html><body>hi</body></html>\n```")
    res = apply_reply(GAME, reply)
    assert res.ok
    assert res.code.startswith("<!DOCTYPE html><html><body>hi")


def test_unfinished_block_is_dropped():
    reply = parse_reply("<<<<<<< SEARCH\n  speed: 5,\n=======\n  speed: 7,\n")
    assert reply.blocks == []
    assert not apply_reply(GAME, reply).ok


def test_no_edits():
    res = apply_reply(GAME, parse_reply("I think the game is great already!"))
    assert not res.ok


def test_deleting_lines_leaves_no_blank_line():
    reply = parse_reply("<<<<<<< SEARCH\n  speed: 5,\n=======\n>>>>>>> REPLACE")
    res = apply_reply(GAME, reply)
    assert res.ok
    assert '  player: "🙂",\n};' in res.code


CONFIG_GAME = """<script>
const CONFIG = {
  title: "Space Shooter",
  player: "🚀",          // the emoji you fly
  enemy: "👾",           // the emoji you shoot
  playerSpeed: 6,        // how fast you move
};
function update() {
  x += CONFIG.playerSpeed;
}
</script>
"""


def test_search_without_comments_still_matches():
    # Typical 3B slip: it retypes the CONFIG lines but drops the aligned comments.
    reply = parse_reply(
        'PLAN: Make the player a dragon.\n<<<<<<< SEARCH\nconst CONFIG = {\n  title: "Space Shooter",\n'
        '  player: "🚀",\n=======\nconst CONFIG = {\n  title: "Space Shooter",\n  player: "🐉",\n>>>>>>> REPLACE\n'
    )
    res = apply_reply(CONFIG_GAME, reply)
    assert res.ok, res.errors
    assert 'player: "🐉"' in res.code
    assert 'enemy: "👾",           // the emoji you shoot' in res.code


def test_collapsed_spacing_matches():
    reply = parse_reply('<<<<<<< SEARCH\n  enemy: "👾", // the emoji you shoot\n=======\n  enemy: "👻", // the emoji you shoot\n>>>>>>> REPLACE')
    res = apply_reply(CONFIG_GAME, reply)
    assert res.ok, res.errors
    assert '"👻"' in res.code


def test_short_markers():
    reply = parse_reply("<<< SEARCH\n  playerSpeed: 6,        // how fast you move\n===\n  playerSpeed: 9,\n>>> REPLACE")
    res = apply_reply(CONFIG_GAME, reply)
    assert res.ok and "playerSpeed: 9," in res.code


def test_code_block_snippet_fallback():
    # No markers at all: the model just re-prints the changed CONFIG in a code block.
    reply = parse_reply(
        "Sure! Here is the updated settings:\n```javascript\nconst CONFIG = {\n  title: \"Space Shooter\",\n"
        "  player: \"🦖\",\n  enemy: \"👾\",\n  playerSpeed: 12,\n};\n```\nHave fun!"
    )
    assert reply.plan == "Sure! Here is the updated settings:"
    res = apply_reply(CONFIG_GAME, reply)
    assert res.ok, res.errors
    assert 'player: "🦖"' in res.code and "playerSpeed: 12" in res.code
    assert "function update()" in res.code


def test_vague_search_is_not_guessed():
    reply = parse_reply("<<<<<<< SEARCH\nconst SETTINGS = {\n  speed: 99,\n=======\nx\n>>>>>>> REPLACE")
    assert not apply_reply(CONFIG_GAME, reply).ok


# ---- Real replies from Qwen2.5-Coder-3B on a Pi 5 (benchmark.py --show) ----
from pathlib import Path  # noqa: E402

STARTERS = Path(__file__).resolve().parent.parent / "server" / "starters"

SNAKE_REPLY = """PLAN: Change the snake's colour to rainbow.
<<<<<<< SEARCH
  snakeColour: "#7cfc00",
=======
  snakeColour: "#ff0000",
>>>>>>> REPLACE
<<<<<<< SEARCH
  headColour: "#c6ff7a",
=======
  headColour: "#00ff00",
>>>>>>> REPLACE
<<<<<<< SEARCH
  snakeColour: "#7cfc00",
=======
  snakeColour: "#0000ff",
>>>>>>> REPLACE
<<<<<<< SEARCH
  snakeColour: "#7cfc00",
=======
  snakeColour: "#ffff00",
>>>>>>> REPLACE
"""

DODGE_REPLY = """PLAN: Add a shield power-up that protects you for 3 seconds.
<<<<<<< SEARCH
  safeTime: 60, // a second of safety after being hit
=======
  safeTime: 60, // a second of safety after being hit
  shieldTime: 3, // new shield time in seconds
>>>>>>> REPLACE
<<<<<<< SEARCH
  if (safeTime === 0 && touching(m, player, 30)) {
=======
  if (safeTime === 0 && touching(m, player, 30) || (safeTime > 0 && touching(m, player, 30))) {
>>>>>>> REPLACE
<<<<<<< SEARCH
    m.gone = true;
    lives--;
    safeTime = 60; // a second of safety after being hit
=======
    m.gone = true;
    lives--;
    safeTime = 60 - shieldTime; // a second of safety after being hit
>>>>>>> REPLACE
<<<<<<< SEARCH
    beep(110, 0.3);
=======
    beep(110, 0.3);
    if (safeTime === 0) beep(990, 0.1); // new sound for shield
>>>>>>> REPLACE
"""


def test_real_snake_reply_skips_duplicate_edits():
    code = (STARTERS / "snake.html").read_text(encoding="utf-8")
    res = apply_reply(code, parse_reply(SNAKE_REPLY))
    assert res.ok, res.errors
    assert res.applied == 2 and len(res.skipped) == 2
    assert 'snakeColour: "#ff0000"' in res.code and 'headColour: "#00ff00"' in res.code


def test_real_dodge_reply_needs_retry_then_partial():
    code = (STARTERS / "dodge.html").read_text(encoding="utf-8")
    first_try = apply_reply(code, parse_reply(DODGE_REPLY))
    assert not first_try.ok and "safeTime: 60" in first_try.errors[0]

    last_try = apply_reply(code, parse_reply(DODGE_REPLY), allow_partial=True)
    assert last_try.ok and last_try.partial
    assert last_try.applied == 3
    assert "60 - shieldTime" in last_try.code  # will crash -> browser test -> fix job


def test_unrelated_miss_is_still_an_error():
    code = (STARTERS / "snake.html").read_text(encoding="utf-8")
    reply = SNAKE_REPLY + "<<<<<<< SEARCH\n  rainbowMode: true,\n=======\n  rainbowMode: false,\n>>>>>>> REPLACE\n"
    res = apply_reply(code, parse_reply(reply))
    assert not res.ok and "rainbowMode" in res.errors[0]


# ---- Round 3: more real replies from the Pi (warm cache, grammar on) ----

SHOOTER_REPLY = """PLAN: Change the player emoji to a dragon 🐉 and the enemy emoji to ghosts 👻.
<<<<<<< SEARCH
  player: "🚀",          // the emoji you fly
  enemy: "👾",           // the emoji you shoot
=======
  player: "🐉",          // the emoji you fly
  enemy: "👻",           // the emoji you shoot
>>>>>>> REPLACE
<<<<<<< SEARCH
  drawEmoji(CONFIG.player, player.x, player.y, 40);
=======
  drawEmoji(CONFIG.player, player.x, player.y, 40);
>>>>>>> REPLACE
<<<<<<< SEARCH
  drawEmoji(CONFIG.enemy, e.x, e.y, 36);
=======
  drawEmoji(CONFIG.enemy, e.x, e.y, 36);
>>>>>>> REPLACE
<<<<<<< SEARCH
  drawText("Score: " + score + "  -  press SPACE to play again", W / 2, H / 2 + 40, 24);
=======
  drawText("Score: " + score + "  -  press SPACE to play again", W / 2, H / 2 + 40, 24);
>>>>>>> REPLACE
"""

SWEETS_REPLY = """PLAN: Change the good things to sweets and the bad things to bombs.
<<<<<<< SEARCH
  goodThings: ["🍎", "🍌", "🍇", "🍓", "🍉"], // catch these
=======
  goodThings: ["🍬", "🍪", "🍰", "🎂", "🧁"], // catch these
>>>>>>> REPLACE
<<<<<<< SEARCH
  badThings: ["💣"],                          // avoid these
=======
  badThings: ["💣", "🍬"],                          // avoid these
>>>>>>> REPLACE
<<<<<<< SEARCH
  drawEmoji(emoji, x, y, size) {
=======
  drawEmoji(emoji, x, y, size) {
>>>>>>> REPLACE
<<<<<<< SEARCH
    ctx.fillText(emoji, x, y);
=======
    ctx.fillText(emoji, x, y, size);
>>>>>>> REPLACE
"""

STAR_REPLY = """PLAN: Add a golden star emoji that gives an extra life when caught.
<<<<<<< SEARCH
  lives: CONFIG.lives,
=======
  lives: CONFIG.lives + 1,
>>>>>>> REPLACE
<<<<<<< SEARCH
  goodThings: ["🍎", "🍌", "🍇", "🍓", "🍉"],
=======
  goodThings: ["🍎", "🍌", "🍇", "🍓", "🍉", "⭐️"],
>>>>>>> REPLACE
<<<<<<< SEARCH
  badThings: ["💣"],
=======
  badThings: ["💣", "⭐️"],
>>>>>>> REPLACE
<<<<<<< SEARCH
  drawEmoji(emoji, x, y, size) {
=======
  drawEmoji(emoji, x, y, size) {
    if (emoji === "⭐️") {
>>>>>>> REPLACE
"""


def test_real_noop_blocks_are_skipped():
    code = (STARTERS / "space-shooter.html").read_text(encoding="utf-8")
    res = apply_reply(code, parse_reply(SHOOTER_REPLY))
    assert res.ok, res.errors
    assert res.applied == 1 and len(res.skipped) == 3
    assert 'player: "🐉",          // the emoji you fly' in res.code
    assert 'enemy: "👻",           // the emoji you shoot' in res.code


def test_real_sweets_reply_with_part_of_line_edit():
    code = (STARTERS / "catch.html").read_text(encoding="utf-8")
    res = apply_reply(code, parse_reply(SWEETS_REPLY))
    assert res.ok, res.errors
    assert res.applied == 3 and len(res.skipped) == 1
    assert '"🍬", "🍪", "🍰", "🎂", "🧁"' in res.code
    assert "  ctx.fillText(emoji, x, y, size);" in res.code  # the game's own indentation kept
    assert "function drawEmoji(emoji, x, y, size) {" in res.code


def test_real_star_reply_is_not_fuzzed_into_a_syntax_error():
    code = (STARTERS / "catch.html").read_text(encoding="utf-8")
    res = apply_reply(code, parse_reply(STAR_REPLY))
    assert not res.ok
    assert "lives: CONFIG.lives" in res.errors[0]
    assert "  lives = CONFIG.lives;" in res.code  # never turned into "lives: CONFIG.lives + 1,"
    assert "lives: CONFIG.lives + 1" not in res.code
    # The part-of-a-line edit kept the "function " in front of it.
    assert 'function drawEmoji(emoji, x, y, size) {\n  if (emoji === "⭐️") {' in res.code


def test_part_of_line_guards():
    code = "a = 1;\nfoo(b, c); bar(b, c);\nfoo(b, c); baz();\nfunction drawSomethingNice(x) {\n}\n"
    # too short
    assert not apply_reply(code, parse_reply("<<<<<<< SEARCH\nbar(b, c);\n=======\nbar(1);\n>>>>>>> REPLACE")).ok
    # long enough, but appears in two lines: too risky to guess
    two = "x(); doSomething(b, c);\ny(); doSomething(b, c);\n"
    res = apply_reply(two, parse_reply("<<<<<<< SEARCH\ndoSomething(b, c);\n=======\nz();\n>>>>>>> REPLACE"))
    assert not res.ok and res.code == two
    res = apply_reply(code, parse_reply(
        "<<<<<<< SEARCH\ndrawSomethingNice(x) {\n=======\ndrawSomethingNice(x, y) {\n>>>>>>> REPLACE"))
    assert res.ok and "function drawSomethingNice(x, y) {" in res.code


def test_single_line_never_fuzzy_matches():
    code = "function start() {\n  lives = CONFIG.lives;\n}\n"
    res = apply_reply(code, parse_reply("<<<<<<< SEARCH\n  lives: CONFIG.lives,\n=======\n  lives: 9,\n>>>>>>> REPLACE"))
    assert not res.ok and res.code == code


def test_two_line_fuzzy_still_works():
    code = "function update() {\n  player.x += CONFIG.playerSpeed;\n  player.y += CONFIG.playerSped;\n}\n"
    res = apply_reply(code, parse_reply(
        "<<<<<<< SEARCH\n  player.x += CONFIG.playerSpeed;\n  player.y += CONFIG.playerSpeed;\n=======\n"
        "  player.x += 2 * CONFIG.playerSpeed;\n  player.y += 2 * CONFIG.playerSpeed;\n>>>>>>> REPLACE"))
    assert res.ok, res.errors
    assert "2 * CONFIG.playerSpeed;\n  player.y += 2 *" in res.code


# ---- Round 4: no guessing between identical places, and "did you mean" hints ----

BOSS_RETRY_REPLY = """PLAN: Add a boss that appears every 100 points.
<<<<<<< SEARCH
  if (frame % CONFIG.enemyEvery === 0) {
=======
  if (frame % CONFIG.enemyEvery === 0) {
    if (score % 100 === 0) {
>>>>>>> REPLACE
<<<<<<< SEARCH
      enemies.push({ x: 30 + Math.random() * (W - 60), y: -20, wobble: Math.random() * 6 });
=======
      enemies.push({ x: 30 + Math.random() * (W - 60), y: -20, wobble: Math.random() * 6, boss: true });
>>>>>>> REPLACE
<<<<<<< SEARCH
    }
=======
>>>>>>> REPLACE
<<<<<<< SEARCH
  }
=======
>>>>>>> REPLACE
"""


def test_lone_braces_are_never_guessed():
    code = (STARTERS / "space-shooter.html").read_text(encoding="utf-8")
    res = apply_reply(code, parse_reply(BOSS_RETRY_REPLY))
    assert not res.ok
    brace_errors = [e for e in res.errors if "'}'" in e]
    assert len(brace_errors) == 2 and all("places" in e and "line above" in e for e in brace_errors)

    partial = apply_reply(code, parse_reply(BOSS_RETRY_REPLY), allow_partial=True)
    assert partial.applied == 2  # only the two edits that point at one clear place
    assert partial.code.count("}") == code.count("}")  # no brace was deleted


def test_duplicate_lines_are_refused_exactly_and_after_normalising():
    code = "function a() {\n  x = 1;\n}\nfunction b() {\n  x = 1;\n}\n"
    exact = apply_reply(code, parse_reply("<<<<<<< SEARCH\n  x = 1;\n=======\n  x = 2;\n>>>>>>> REPLACE"))
    loose = apply_reply(code, parse_reply("<<<<<<< SEARCH\nx = 1 // set x\n=======\nx = 2;\n>>>>>>> REPLACE"))
    for res in (exact, loose):
        assert not res.ok and res.code == code and "2 places" in res.errors[0]
    # One line of context makes it unique, which is fine.
    ok = apply_reply(code, parse_reply("<<<<<<< SEARCH\nfunction b() {\n  x = 1;\n=======\nfunction b() {\n  x = 2;\n>>>>>>> REPLACE"))
    assert ok.ok and ok.code.count("x = 1;") == 1


def test_did_you_mean_hints():
    catch = (STARTERS / "catch.html").read_text(encoding="utf-8")
    res = apply_reply(catch, parse_reply(STAR_REPLY))
    assert "lives = CONFIG.lives;" in res.errors[0] and "Copy it exactly" in res.errors[0]

    dodge = (STARTERS / "dodge.html").read_text(encoding="utf-8")
    res = apply_reply(dodge, parse_reply(DODGE_REPLY))
    assert "safeTime = 60" in res.errors[0]

    res = apply_reply(catch, parse_reply("<<<<<<< SEARCH\nquantumFluxCapacitor.engage(9000);\n=======\nx\n>>>>>>> REPLACE"))
    assert "closest" not in res.errors[0]


def test_lines_the_agent_relies_on_are_unique_in_every_starter():
    for path in STARTERS.glob("*.html"):
        assert path.read_text(encoding="utf-8").count("  requestAnimationFrame(loop);") == 1, path.name
