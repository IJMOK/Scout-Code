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
