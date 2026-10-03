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
