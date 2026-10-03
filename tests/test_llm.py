"""The llama.cpp client against a fake llama-server, including failover to a second Pi."""

import asyncio
import json
import socket
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from server.db import DB
from server.jobqueue import Hub, JobQueue, Worker
from server.llm import LlamaServer, LLMError

KEY = "test-key"
REPLY = 'PLAN: Make it a cat.\n<<<<<<< SEARCH\n  player: "🚀",\n=======\n  player: "🐱",\n>>>>>>> REPLACE\n'


def fake_llama_server() -> FastAPI:
    app = FastAPI()
    app.state.requests = []

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return JSONResponse({"error": "Invalid API Key"}, status_code=401)
        body = await request.json()
        app.state.requests.append(body)

        async def stream():
            for i in range(0, len(REPLY), 5):
                chunk = {"choices": [{"index": 0, "delta": {"content": REPLY[i:i + 5]}}]}
                yield f"data: {json.dumps(chunk)}\n\n"
            yield 'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def fake():
    app = fake_llama_server()
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", app
    server.should_exit = True
    thread.join(5)


async def collect(client, messages):
    return "".join([c async for c in client.stream_chat(messages, 100, 0.2)])


def test_streams_reply_and_sends_cache_prompt(fake):
    url, app = fake
    text = asyncio.run(collect(LlamaServer(url, api_key=KEY), [{"role": "user", "content": "hi"}]))
    assert text == REPLY
    assert app.state.requests[-1]["cache_prompt"] is True
    assert app.state.requests[-1]["stream"] is True


def test_wrong_key_is_an_error(fake):
    url, _ = fake
    with pytest.raises(LLMError, match="401"):
        asyncio.run(collect(LlamaServer(url, api_key="nope"), [{"role": "user", "content": "hi"}]))


def test_unreachable_server(fake):
    dead = LlamaServer(f"http://127.0.0.1:{free_port()}", api_key=KEY)
    assert asyncio.run(dead.healthy()) is False
    with pytest.raises(LLMError, match="Could not reach"):
        asyncio.run(collect(dead, [{"role": "user", "content": "hi"}]))


class _Settings:
    temperature = 0.2
    edit_max_tokens = 200
    explain_max_tokens = 100
    use_grammar = True


def test_job_fails_over_to_the_other_pi(fake, tmp_path):
    """One Pi is switched off: the job moves to the other one and still succeeds."""
    url, _ = fake
    db = DB(tmp_path / "t.db")
    db.execute("INSERT INTO teams(id, name, emoji, pin, token, last_worker, created_at) "
               "VALUES(1,'A','🦊','1234','tok','dead',0)")
    db.execute("INSERT INTO games(id, team_id, starter, title, created_at) VALUES(1,1,'x','X',0)")
    db.execute("INSERT INTO versions(id, game_id, code, status, created_at) "
               "VALUES(1,1,'const CONFIG = {\n  player: \"🚀\",\n};\n','ok',0)")

    async def scenario():
        workers = [Worker("dead", LlamaServer(f"http://127.0.0.1:{free_port()}", api_key=KEY)),
                   Worker("alive", LlamaServer(url, api_key=KEY))]
        q = JobQueue(db, workers, Hub(), _Settings())
        q.start()
        # The dead Pi is preferred (it served this team last), so it's tried first.
        job_id = q.submit(team_id=1, game_id=1, kind="edit", request="make it a cat", base_version_id=1)
        for _ in range(200):
            if db.value("SELECT status FROM jobs WHERE id=?", (job_id,)) == "testing":
                break
            await asyncio.sleep(0.02)
        await q.stop()
        return job_id, workers

    job_id, workers = asyncio.run(scenario())
    job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    assert job["status"] == "testing"
    assert job["worker"] == "alive"
    assert workers[0].healthy is False
    code = db.value("SELECT code FROM versions WHERE id=?", (job["result_version_id"],))
    assert '"🐱"' in code
    assert "grammar" in fake[1].state.requests[-1]  # edits are format-constrained


def test_grammar_sent_only_when_asked(fake):
    from server.grammar import EDIT_GRAMMAR

    url, app = fake
    asyncio.run(collect(LlamaServer(url, api_key=KEY), [{"role": "user", "content": "hi"}]))
    assert "grammar" not in app.state.requests[-1]

    async def with_grammar():
        client = LlamaServer(url, api_key=KEY)
        return "".join([c async for c in client.stream_chat([{"role": "user", "content": "hi"}], 50, 0.2,
                                                            grammar=EDIT_GRAMMAR)])
    asyncio.run(with_grammar())
    assert app.state.requests[-1]["grammar"] == EDIT_GRAMMAR


def test_warmup_preloads_starters_after_real_jobs(fake, tmp_path):
    """Warm-ups send each starter's first-request prompt, but never before a waiting scout."""
    from server import prompts

    url, app = fake
    db = DB(tmp_path / "w.db")
    db.execute("INSERT INTO teams(id, name, emoji, pin, token, created_at) VALUES(1,'A','🦊','1234','tok',0)")
    db.execute("INSERT INTO games(id, team_id, starter, title, created_at) VALUES(1,1,'x','X',0)")
    db.execute("INSERT INTO versions(id, game_id, code, status, created_at) "
               "VALUES(1,1,'const CONFIG = {\n  player: \"🚀\",\n};\n','ok',0)")
    sources = {"one": "<p>game one</p>", "two": "<p>game two</p>", "three": "<p>game three</p>"}
    db.set_setting("ai_paused", "1")
    before = len(app.state.requests)

    async def scenario():
        worker = Worker("pi", LlamaServer(url, api_key=KEY))
        q = JobQueue(db, [worker], Hub(), _Settings(), sources)
        q.start()
        q.start_warmup()
        q.submit(team_id=1, game_id=1, kind="edit", request="make it a cat", base_version_id=1)
        db.set_setting("ai_paused", "0")
        q.notify()
        for _ in range(300):
            if worker.warm_done == 3 and worker.busy_job is None:
                break
            await asyncio.sleep(0.02)
        await q.stop()
        return worker

    worker = asyncio.run(scenario())
    sent = app.state.requests[before:]
    assert [r["max_tokens"] for r in sent] == [200, 1, 1, 1]  # the scout's job went first
    assert [r["messages"] for r in sent[1:]] == [prompts.edit_messages(code, "") for code in sources.values()]
    assert worker.warm_done == 3 and worker.warm_todo == []
