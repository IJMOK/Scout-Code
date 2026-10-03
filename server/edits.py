"""Parse and apply the AI's SEARCH/REPLACE edit blocks.

Small local models only output the *changes* to a game, not the whole file,
because a Raspberry Pi writes about 5-8 words a second. The reply looks like:

    PLAN: Make the player a dinosaur.
    <<<<<<< SEARCH
      player: "🙂",
    =======
      player: "🦖",
    >>>>>>> REPLACE

Small models are sloppy, so the parser is forgiving: marker lengths can vary,
code fences are ignored, and the SEARCH text matches even when the
indentation or trailing spaces differ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SEARCH_RE = re.compile(r"^\s*<{5,}\s*SEARCH\s*$", re.IGNORECASE)
DIVIDER_RE = re.compile(r"^\s*={5,}\s*$")
REPLACE_RE = re.compile(r"^\s*>{5,}\s*REPLACE\s*$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*```")
PLAN_RE = re.compile(r"^\s*PLAN\s*:\s*(.*)$", re.IGNORECASE)


@dataclass
class Block:
    search: str
    replace: str


@dataclass
class ParsedReply:
    plan: str = ""
    blocks: list[Block] = field(default_factory=list)
    full_file: str | None = None


@dataclass
class ApplyResult:
    code: str
    applied: int
    errors: list[str]

    @property
    def ok(self) -> bool:
        return self.applied > 0 and not self.errors


def parse_reply(text: str) -> ParsedReply:
    """Pull the plan, the edit blocks, or a whole replacement file out of a reply."""
    reply = ParsedReply()
    lines = text.splitlines()
    state = "text"
    search: list[str] = []
    replace: list[str] = []
    plan_lines: list[str] = []

    for line in lines:
        if state == "text":
            if SEARCH_RE.match(line):
                state, search, replace = "search", [], []
            elif m := PLAN_RE.match(line):
                plan_lines.append(m.group(1).strip())
        elif state == "search":
            if DIVIDER_RE.match(line):
                state = "replace"
            elif REPLACE_RE.match(line):
                # Model forgot the divider: nothing we can safely do with it.
                state = "text"
            else:
                search.append(line)
        elif state == "replace":
            if REPLACE_RE.match(line):
                reply.blocks.append(Block(_strip_fences(search), _strip_fences(replace)))
                state = "text"
            else:
                replace.append(line)

    # A block that ran out of tokens before >>>>>>> REPLACE is still usable
    # if the replacement looks finished, but it is safer to drop it.
    reply.plan = " ".join(p for p in plan_lines if p)

    if not reply.blocks:
        reply.full_file = _find_full_file(text)
    return reply


def _strip_fences(lines: list[str]) -> str:
    kept = [ln for ln in lines if not FENCE_RE.match(ln)]
    return "\n".join(kept)


def _find_full_file(text: str) -> str | None:
    """Fallback: the model ignored instructions and wrote the whole game."""
    m = re.search(r"(<!DOCTYPE html>.*</html>)", text, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() + "\n" if m else None


def apply_blocks(code: str, blocks: list[Block]) -> ApplyResult:
    applied = 0
    errors: list[str] = []
    for i, block in enumerate(blocks, 1):
        if not block.search.strip():
            errors.append(f"Edit {i}: the SEARCH part was empty.")
            continue
        new_code = _replace_once(code, block.search, block.replace)
        if new_code is None:
            first = block.search.strip().splitlines()[0][:80]
            errors.append(f"Edit {i}: could not find this code to change: {first!r}")
            continue
        code = new_code
        applied += 1
    return ApplyResult(code=code, applied=applied, errors=errors)


def apply_reply(code: str, reply: ParsedReply) -> ApplyResult:
    if reply.blocks:
        return apply_blocks(code, reply.blocks)
    if reply.full_file:
        return ApplyResult(code=reply.full_file, applied=1, errors=[])
    return ApplyResult(code=code, applied=0, errors=["The AI did not suggest any code changes."])


def _replace_once(code: str, search: str, replace: str) -> str | None:
    # 1. Exact match.
    idx = code.find(search)
    if idx != -1:
        return code[:idx] + replace + code[idx + len(search):]

    # 2. Line-by-line match ignoring indentation and trailing spaces.
    code_lines = code.split("\n")
    search_lines = [ln for ln in search.split("\n")]
    while search_lines and not search_lines[0].strip():
        search_lines.pop(0)
    while search_lines and not search_lines[-1].strip():
        search_lines.pop()
    if not search_lines:
        return None
    want = [ln.strip() for ln in search_lines]
    n = len(want)
    for start in range(len(code_lines) - n + 1):
        if all(code_lines[start + k].strip() == want[k] for k in range(n)):
            indent = _reindent(code_lines[start], search_lines[0])
            repl_lines = replace.split("\n") if replace else []
            repl_lines = [_shift(ln, indent) for ln in repl_lines]
            return "\n".join(code_lines[:start] + repl_lines + code_lines[start + n:])
    return None


def _leading(s: str) -> str:
    return s[: len(s) - len(s.lstrip())]


def _reindent(real_line: str, model_line: str) -> tuple[str, str]:
    """Work out how the model's indentation differs from the real file's."""
    return _leading(model_line), _leading(real_line)


def _shift(line: str, indent: tuple[str, str]) -> str:
    model_indent, real_indent = indent
    if not line.strip():
        return line
    if line.startswith(model_indent):
        return real_indent + line[len(model_indent):]
    return line


def changed_line_count(old: str, new: str) -> int:
    """Rough size of a change, for the leader dashboard."""
    import difflib

    return sum(
        1
        for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
        if ln[:1] in "+-" and not ln.startswith(("+++", "---"))
    )
