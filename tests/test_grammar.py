"""Check EDIT_GRAMMAR with llama.cpp's own grammar validator (no model needed).

Build it once from a llama.cpp checkout:
    cmake -B build -DLLAMA_BUILD_TESTS=ON && cmake --build build --target test-gbnf-validator
then point SCOUT_GBNF_VALIDATOR at build/bin/test-gbnf-validator. Skipped otherwise.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from server.grammar import EDIT_GRAMMAR

VALIDATOR = os.environ.get("SCOUT_GBNF_VALIDATOR") or shutil.which("test-gbnf-validator")
pytestmark = pytest.mark.skipif(not VALIDATOR or not Path(VALIDATOR).exists(),
                                reason="llama.cpp test-gbnf-validator not available")

GOOD = {
    "simple": 'PLAN: Make it a dragon.\n<<<<<<< SEARCH\n  player: "🚀",          // the emoji you fly\n'
              '=======\n  player: "🐉",\n>>>>>>> REPLACE\n',
    "html, arrows, blank lines": 'PLAN: Bigger.\n<<<<<<< SEARCH\n<canvas id="game" width="800"></canvas>\n\n'
                                 'const f = (a) => a == 1;\n=======\n<canvas id="game" width="900"></canvas>\n'
                                 '>>>>>>> REPLACE\n',
    "two blocks, one deletes": 'PLAN: Two things.\n<<<<<<< SEARCH\n  lives: 3,\n=======\n  lives: 5,\n'
                               '>>>>>>> REPLACE\n<<<<<<< SEARCH\n  boom();\n=======\n>>>>>>> REPLACE\n',
    "refusal": "PLAN: Let's try a different idea!\n",
}
BAD = {
    "prose only": "Sure! Here is the code:\n```js\nx\n```\n",
    "plan only": "PLAN: I will do it.\n",
    "marker as a code line": "PLAN: x\n<<<<<<< SEARCH\n=======\n=======\n>>>>>>> REPLACE\n",
}


def valid(tmp_path, text: str) -> bool:
    g = tmp_path / "edit.gbnf"
    g.write_text(EDIT_GRAMMAR)
    f = tmp_path / "reply.txt"
    f.write_text(text)
    out = subprocess.run([VALIDATOR, str(g), str(f)], capture_output=True, text=True)
    return "Input string is valid" in out.stdout + out.stderr


@pytest.mark.parametrize("name", GOOD)
def test_accepts(tmp_path, name):
    assert valid(tmp_path, GOOD[name])


@pytest.mark.parametrize("name", BAD)
def test_rejects(tmp_path, name):
    assert not valid(tmp_path, BAD[name])
