"""Talking to the AI.

`LlamaServer` streams from llama.cpp's `llama-server` (OpenAI-compatible API).
`MockLLM` pretends to be a model so the portal can be developed and tested
on any computer, with no Pi and no model download.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncIterator

import httpx


class LLMError(Exception):
    pass


class LlamaServer:
    def __init__(self, base_url: str, timeout: float = 600.0, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def stream_chat(self, messages: list[dict], max_tokens: int, temperature: float,
                          grammar: str | None = None) -> AsyncIterator[str]:
        body = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            # Reuse the shared system prompt (and this team's game, if it is
            # still in a slot) instead of re-reading it on a slow Pi.
            "cache_prompt": True,
        }
        if grammar:
            body["grammar"] = grammar
        timeout = httpx.Timeout(self.timeout, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=self.headers) as client:
                async with client.stream("POST", f"{self.base_url}/v1/chat/completions", json=body) as resp:
                    if resp.status_code != 200:
                        raise LLMError(f"AI server said {resp.status_code}: {(await resp.aread())[:200]!r}")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or [{}]
                        text = (choices[0].get("delta") or {}).get("content")
                        if text:
                            yield text
        except httpx.HTTPError as e:
            raise LLMError(f"Could not reach the AI at {self.base_url}: {e}") from e

    async def healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self.base_url}/health")
                return r.status_code == 200
        except httpx.HTTPError:
            return False


# ---------------------------------------------------------------------------
# Mock model for development and tests
# ---------------------------------------------------------------------------

_COLOURS = {
    "red": "#c0392b", "blue": "#1e3799", "green": "#1e8449", "pink": "#ff7eb9",
    "purple": "#5b2c83", "black": "#000000", "orange": "#e67e22", "yellow": "#f4d03f",
    "white": "#ffffff", "night": "#0a0a23", "dark": "#111111",
}
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF☀-➿][️‍\U0001F300-\U0001FAFF☀-➿]*"
)


class MockLLM:
    """Fakes a coding model by making sensible CONFIG edits.

    Special words for testing the agent loop:
      "BREAK"  -> produces a game that crashes, so the auto-fix runs
      "NOMATCH" -> produces an edit whose SEARCH text is not in the game
    """

    def __init__(self, delay: float = 0.01):
        self.delay = delay

    async def healthy(self) -> bool:
        return True

    async def stream_chat(self, messages: list[dict], max_tokens: int, temperature: float,
                          grammar: str | None = None) -> AsyncIterator[str]:
        system, user = messages[0]["content"], messages[-1]["content"]
        if "explain code" in system.lower():
            text = self._explain(user)
        else:
            text = self._edit(user)
        for i in range(0, len(text), 4):
            await asyncio.sleep(self.delay)
            yield text[i:i + 4]

    def _explain(self, user: str) -> str:
        words = re.findall(r"[A-Za-z_]{4,}", user.split("\n\n", 1)[-1])
        thing = words[0] if words else "this"
        return (f"This bit of code is like a recipe step. It uses '{thing}' to keep track of "
                "something in the game, and the computer follows it every time the screen is drawn, "
                "about 60 times a second!")

    def _edit(self, user: str) -> str:
        code = user.split("Here is the current game:\n\n", 1)[-1]
        code = re.split(r"\n\n(?:The Scouts asked|Your last change broke|Your last answer could not be used)", code)[0]
        request = (re.findall(r'(?:asked|had asked): "(.*)"', user) or [""])[0]
        fixing = "Your last change broke" in user or "Your last answer could not be used" in user

        if fixing:
            bad = re.search(r"^.*mockExplodes\(\);.*\n", code, re.MULTILINE)
            if bad:
                return ("PLAN: Oops, I broke it! Removing the broken line.\n"
                        f"<<<<<<< SEARCH\n{bad.group(0).rstrip()}\n=======\n>>>>>>> REPLACE\n")
            return self._config_edit(code, request) or self._title_edit(code, request)

        if "BREAK" in request:
            return ("PLAN: Add something that will crash.\n<<<<<<< SEARCH\n  requestAnimationFrame(loop);\n"
                    "=======\n  mockExplodes();\n  requestAnimationFrame(loop);\n>>>>>>> REPLACE\n")
        if "NOMATCH" in request:
            return "PLAN: Change a thing.\n<<<<<<< SEARCH\nthis line is not there\n=======\nnew\n>>>>>>> REPLACE\n"
        return self._config_edit(code, request) or self._title_edit(code, request)

    def _config_edit(self, code: str, request: str) -> str | None:
        req = request.lower()
        lines = code.split("\n")
        try:
            start = next(i for i, ln in enumerate(lines) if "const CONFIG" in ln)
        except StopIteration:
            return None
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("};")), len(lines))
        cfg = lines[start + 1:end]

        emoji = _EMOJI_RE.search(request)
        if emoji:
            for ln in cfg:
                if m := re.match(r'(\s*\w+:\s*)"([^"]+)"', ln):
                    if _EMOJI_RE.fullmatch(m.group(2)):
                        new = ln.replace(f'"{m.group(2)}"', f'"{emoji.group(0)}"', 1)
                        return self._block(f"Swap the {m.group(1).strip(' :')} for {emoji.group(0)}.", ln, new)

        for word, faster in (("fast", True), ("quick", True), ("slow", False)):
            if word in req:
                for ln in cfg:
                    if m := re.match(r"(\s*\w*[Ss]peed\w*:\s*)([\d.]+)", ln):
                        n = float(m.group(2)) * (2 if faster else 0.5)
                        val = str(int(n)) if n.is_integer() else f"{n:g}"
                        new = ln.replace(m.group(1) + m.group(2), m.group(1) + val, 1)
                        return self._block(f"Make things {'faster' if faster else 'slower'}.", ln, new)

        for word, hexval in _COLOURS.items():
            if word in req:
                for ln in cfg:
                    if m := re.match(r'(\s*\w*(?:background|sky|Colour)\w*:\s*)"(#[0-9a-fA-F]{3,6})"', ln):
                        new = ln.replace(m.group(2), hexval, 1)
                        return self._block(f"Paint it {word}.", ln, new)
        return None

    def _title_edit(self, code: str, request: str) -> str:
        m = re.search(r'^(\s*title:\s*)"([^"]*)",', code, re.MULTILINE)
        if not m:
            return "PLAN: I'm not sure how to do that yet."
        old = m.group(0)
        new = f'{m.group(1)}"{m.group(2)} Deluxe",'
        return self._block("Give the game a cooler name.", old, new)

    @staticmethod
    def _block(plan: str, old: str, new: str) -> str:
        return f"PLAN: {plan}\n<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE\n"
