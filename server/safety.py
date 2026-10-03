"""A simple word filter for prompts, team names and game titles.

This is a first line of defence for a supervised event, not a guarantee.
Leaders can hide any game from the dashboard, and they can add words to
`data/blocked-words.txt`, one per line.
"""

from __future__ import annotations

import re
from pathlib import Path

# Deliberately short and mild: the aim is to catch obvious attempts,
# not to block ordinary game words like "shoot", "bomb" or "kill the boss".
_DEFAULT_WORDS = {
    "fuck", "shit", "bitch", "cunt", "dick", "piss", "bastard", "wank", "twat", "slut",
    "whore", "porn", "sex", "sexy", "nude", "naked", "boobs", "penis", "vagina",
    "nazi", "hitler", "suicide", "self harm", "drugs", "cocaine", "weed",
    "blood", "gore", "behead",
}

_extra: set[str] = set()


def load_extra_words(path: Path) -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            word = line.strip().lower()
            if word and not word.startswith("#"):
                _extra.add(word)


def _normalise(text: str) -> str:
    text = text.lower()
    text = text.translate(str.maketrans("013457@$!", "oieastasi"))
    return re.sub(r"[^a-z ]+", " ", text)


def _join_spaced_letters(tokens: list[str]) -> list[str]:
    """Turn "f u c k" back into "fuck" without gluing real words together."""
    out: list[str] = []
    run = ""
    for tok in tokens:
        if len(tok) == 1:
            run += tok
            continue
        if run:
            out.append(run)
            run = ""
        out.append(tok)
    if run:
        out.append(run)
    return out


def is_blocked(text: str) -> bool:
    tokens = _join_spaced_letters(_normalise(text).split())
    padded = " " + " ".join(tokens) + " "
    return any(f" {word} " in padded for word in _DEFAULT_WORDS | _extra)
