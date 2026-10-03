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

SEARCH_RE = re.compile(r"^\s*(?:<{3,}\s*SEARCH|SEARCH\s*:)\s*$", re.IGNORECASE)
DIVIDER_RE = re.compile(r"^\s*(?:={3,}|REPLACE\s*:)\s*$", re.IGNORECASE)
REPLACE_RE = re.compile(r"^\s*(?:>{3,}\s*REPLACE|END\s*REPLACE)\s*$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*```")
CODE_BLOCK_RE = re.compile(r"```[\w+-]*[^\n]*\n(.*?)```", re.DOTALL)
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
    snippets: list[str] = field(default_factory=list)


@dataclass
class ApplyResult:
    code: str
    applied: int
    errors: list[str]
    skipped: list[str] = field(default_factory=list)
    partial: bool = False  # some edits were left out (only allowed on the last try)

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
    reply.plan = " ".join(p for p in plan_lines if p) or _first_sentence(text)

    if not reply.blocks:
        reply.full_file = _find_full_file(text)
        if not reply.full_file:
            # Small models often just re-print the changed bit in a code block.
            reply.snippets = [m.group(1).rstrip("\n") for m in CODE_BLOCK_RE.finditer(text) if m.group(1).strip()]
    return reply


def _first_sentence(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("```", "<", "=", ">")) and not SEARCH_RE.match(line):
            return line[:200]
    return ""


def _strip_fences(lines: list[str]) -> str:
    kept = [ln for ln in lines if not FENCE_RE.match(ln)]
    return "\n".join(kept)


def _find_full_file(text: str) -> str | None:
    """Fallback: the model ignored instructions and wrote the whole game."""
    m = re.search(r"(<!DOCTYPE html>.*</html>)", text, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() + "\n" if m else None


def apply_blocks(code: str, blocks: list[Block]) -> ApplyResult:
    original = code
    applied = 0
    errors: list[str] = []
    skipped: list[str] = []
    changed_lines: set[str] = set()  # lines earlier edits in this reply have already changed
    for i, block in enumerate(blocks, 1):
        if not block.search.strip():
            errors.append(f"Edit {i}: the SEARCH part was empty.")
            continue
        first = block.search.strip().splitlines()[0][:80]
        search_keys = {_loose(ln) for ln in block.search.split("\n") if _loose(ln)}
        # Small models often edit the same line twice. The first edit already changed
        # it, so skip this one (before fuzzy matching could land it on the new line).
        if (search_keys & changed_lines and _replace_once(code, block.search, block.replace, fuzzy=False) is None
                and _replace_once(original, block.search, block.replace) is not None):
            skipped.append(f"Edit {i}: changes a line that an earlier edit already changed: {first!r}")
            continue
        new_code = _replace_once(code, block.search, block.replace)
        if new_code is None:
            errors.append(f"Edit {i}: could not find this code to change: {first!r}")
            continue
        code = new_code
        changed_lines |= search_keys
        applied += 1
    return ApplyResult(code=code, applied=applied, errors=errors, skipped=skipped)


def apply_reply(code: str, reply: ParsedReply, allow_partial: bool = False) -> ApplyResult:
    """Apply the AI's reply. With allow_partial, keep the edits that fit even if others didn't."""
    if reply.blocks:
        result = apply_blocks(code, reply.blocks)
        if allow_partial and result.applied and result.errors:
            result.skipped += result.errors
            result.errors = []
            result.partial = True
        return result
    if reply.full_file:
        return ApplyResult(code=reply.full_file, applied=1, errors=[])
    if reply.snippets:
        return apply_snippets(code, reply.snippets)
    return ApplyResult(code=code, applied=0, errors=["The AI did not suggest any code changes."])


def apply_snippets(code: str, snippets: list[str]) -> ApplyResult:
    """Apply code blocks that re-print part of the game, matched by first and last line."""
    applied = 0
    for snippet in snippets:
        new_code = _anchor_replace(code, snippet)
        if new_code is not None and new_code != code:
            code = new_code
            applied += 1
    if not applied:
        return ApplyResult(code=code, applied=0, errors=[
            "The AI wrote some code, but it didn't say where in the game it goes."])
    return ApplyResult(code=code, applied=applied, errors=[])


def _norm(line: str) -> str:
    """Compare lines ignoring all spacing differences."""
    return " ".join(line.split())


def _anchor_replace(code: str, snippet: str) -> str | None:
    snip_lines = snippet.split("\n")
    content = [ln for ln in snip_lines if ln.strip()]
    if len(content) < 2:
        return None
    first, last = _norm(content[0]), _norm(content[-1])
    # Anchors that are too generic ("}" or "};") would match almost anywhere.
    if len(first) < 6:
        return None
    code_lines = code.split("\n")
    for start, line in enumerate(code_lines):
        if _norm(line) != first:
            continue
        limit = min(len(code_lines), start + len(snip_lines) + 40)
        for end in range(start + 1, limit):
            if _norm(code_lines[end]) == last:
                indent = _reindent(code_lines[start], content[0])
                body = [_shift(ln, indent) for ln in snip_lines]
                while body and not body[0].strip():
                    body.pop(0)
                while body and not body[-1].strip():
                    body.pop()
                return "\n".join(code_lines[:start] + body + code_lines[end + 1:])
        return None
    return None


def _replace_once(code: str, search: str, replace: str, fuzzy: bool = True) -> str | None:
    # 1. Exact match.
    idx = code.find(search)
    if idx != -1:
        end = idx + len(search)
        whole_lines = (idx == 0 or code[idx - 1] == "\n") and code[end:end + 1] == "\n"
        if not replace and whole_lines:
            end += 1  # deleting whole lines: don't leave a blank line behind
        return code[:idx] + replace + code[end:]

    # 2. Line-by-line match ignoring indentation and trailing spaces.
    code_lines = code.split("\n")
    search_lines = [ln for ln in search.split("\n")]
    while search_lines and not search_lines[0].strip():
        search_lines.pop(0)
    while search_lines and not search_lines[-1].strip():
        search_lines.pop()
    if not search_lines:
        return None
    want = [_norm(ln) for ln in search_lines]
    n = len(want)
    for start in range(len(code_lines) - n + 1):
        if all(_norm(code_lines[start + k]) == want[k] for k in range(n)):
            indent = _reindent(code_lines[start], search_lines[0])
            repl_lines = replace.split("\n") if replace else []
            repl_lines = [_shift(ln, indent) for ln in repl_lines]
            return "\n".join(code_lines[:start] + repl_lines + code_lines[start + n:])

    # 3. Small models often retype lines without their // comments, or with
    #    small slips. Find the stretch of the game that matches best.
    if not fuzzy:
        return None
    start = _best_window(code_lines, search_lines)
    if start is None:
        return None
    indent = _reindent(code_lines[start], search_lines[0])
    repl_lines = [_shift(ln, indent) for ln in (replace.split("\n") if replace else [])]
    return "\n".join(code_lines[:start] + repl_lines + code_lines[start + n:])


def _loose(line: str) -> str:
    """A line without its // comment, spacing or trailing commas/semicolons."""
    line = re.sub(r"\s//.*$|^\s*//.*$", "", line)
    return _norm(line).rstrip(",; ")


def _best_window(code_lines: list[str], search_lines: list[str]) -> int | None:
    """Start of the stretch of code that best matches the SEARCH lines, if it's a confident match.

    Every SEARCH line must be at least a close match (so the model can't just
    point vaguely at the right area), the first line must match closely, and
    the winner must be clearly unique.
    """
    import difflib

    want = [_loose(ln) for ln in search_lines]
    n = len(want)
    scored: list[tuple[float, int]] = []
    for start in range(len(code_lines) - n + 1):
        ratios = []
        for k in range(n):
            have = _loose(code_lines[start + k])
            if have == want[k]:
                ratios.append(1.0)
            elif not have or not want[k]:
                ratios.append(1.0 if have == want[k] else 0.0)
            else:
                ratios.append(difflib.SequenceMatcher(None, have, want[k]).ratio())
        if ratios[0] >= 0.9 and min(ratios) >= 0.75:
            scored.append((sum(ratios) / n, start))
    if not scored:
        return None
    scored.sort(reverse=True)
    best, start = scored[0]
    if best < 0.9:
        return None
    if len(scored) > 1 and scored[1][0] >= best - 0.02 and scored[1][1] != start:
        return None  # two places match equally well: too risky to guess
    return start


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
