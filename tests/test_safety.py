from server.safety import is_blocked


def test_blocks_rude_words_and_spacing():
    assert is_blocked("make it say shit")
    assert is_blocked("f u c k")
    assert is_blocked("SH1T")


def test_allows_normal_game_words():
    for ok in ["shoot the aliens", "add a bomb", "kill the boss", "happen island",
               "Sussex yard", "make the snake rainbow", "assassin bug"]:
        assert not is_blocked(ok), ok
