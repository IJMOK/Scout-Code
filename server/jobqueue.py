"""The AI job queue and the agent loop.

Each team can have one job on the go at a time. Jobs go to whichever Pi is
free, preferring the Pi that served that team last time, because llama.cpp
may still hold that team's game in its prompt cache.

Agent loop for an edit:
  plan + write  ->  apply edits  ->  browser tests the new version
       ^                                   |
       +------ one automatic fix  <--------+ (if it crashed)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import prompts
from .db import DB, now
from .edits import apply_reply, parse_reply

log = logging.getLogger("scout.queue")

PRIORITY = {"fix": 0, "edit": 1, "explain": 2}
ACTIVE = ("queued", "running", "testing")
STALE_TEST_SECONDS = 180
MAX_FIX_ATTEMPTS = 1


@dataclass
class Worker:
    name: str
    client: Any
    stats_url: str | None = None
    busy_job: int | None = None
    healthy: bool = True
    tokens_per_sec: float = 0.0
    jobs_done: int = 0
    stats: dict = field(default_factory=dict)


class Hub:
    """Fan-out of live events to each team's open browser tabs (Server-Sent Events).

    `publish` may be called from FastAPI's worker threads, so it always hands
    the event over to the server's event loop.
    """

    def __init__(self) -> None:
        self.subs: dict[int, set[asyncio.Queue]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, team_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.subs.setdefault(team_id, set()).add(q)
        return q

    def unsubscribe(self, team_id: int, q: asyncio.Queue) -> None:
        self.subs.get(team_id, set()).discard(q)

    def publish(self, team_id: int, event: dict) -> None:
        _in_loop(self.loop, self._publish, team_id, event)

    def _publish(self, team_id: int, event: dict) -> None:
        for q in list(self.subs.get(team_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


class JobQueue:
    def __init__(self, db: DB, workers: list[Worker], hub: Hub, settings: Any):
        self.db = db
        self.workers = workers
        self.hub = hub
        self.settings = settings
        self.wake: asyncio.Event | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.tasks: set[asyncio.Task] = set()
        self.durations: list[float] = []
        self.infra_retries: dict[int, int] = {}

    # ------------------------------------------------------------------ setup
    def start(self) -> None:
        """Call from inside the running event loop (the app's startup)."""
        self.loop = asyncio.get_running_loop()
        self.hub.loop = self.loop
        self.wake = asyncio.Event()
        # Anything that was running when the server stopped goes back in the queue.
        self.db.execute("UPDATE jobs SET status='queued', worker=NULL WHERE status='running'")
        self._spawn(self._scheduler())
        self._spawn(self._health_loop())
        self.notify()

    def notify(self) -> None:
        """Ask the scheduler to look for work. Safe to call from any thread."""
        if self.wake is not None:
            _in_loop(self.loop, self.wake.set)

    async def stop(self) -> None:
        for t in list(self.tasks):
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    # ------------------------------------------------------------- submitting
    def active_job(self, team_id: int, kinds: tuple[str, ...] = ("edit", "fix")) -> dict | None:
        marks = ",".join("?" * len(kinds))
        job = self.db.one(
            f"SELECT * FROM jobs WHERE team_id=? AND kind IN ({marks}) AND status IN ('queued','running','testing') "
            "ORDER BY id DESC LIMIT 1",
            (team_id, *kinds),
        )
        if job and job["status"] == "testing" and now() - (job["finished_at"] or 0) > STALE_TEST_SECONDS:
            # Nobody reported a test result (tab closed?). Don't block the team forever.
            return None
        return job

    def submit(self, *, team_id: int, game_id: int, kind: str, request: str, base_version_id: int | None,
               snippet: str = "", error_in: str = "", attempt: int = 0) -> int:
        job_id = self.db.execute(
            "INSERT INTO jobs(team_id, game_id, kind, priority, request, snippet, error_in, base_version_id, "
            "attempt, status, created_at) VALUES(?,?,?,?,?,?,?,?,?, 'queued', ?)",
            (team_id, game_id, kind, PRIORITY[kind], request, snippet, error_in, base_version_id, attempt, now()),
        )
        self._event(team_id, job_id, "queued")
        self.broadcast_positions()
        self.notify()
        return job_id

    def cancel(self, job_id: int) -> bool:
        job = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] not in ACTIVE:
            return False
        self.db.execute("UPDATE jobs SET status='cancelled', finished_at=?, message='Stopped by a leader' WHERE id=?",
                        (now(), job_id))
        self._event(job["team_id"], job_id, "cancelled", message="A leader stopped this job.")
        self.broadcast_positions()
        return True

    # ------------------------------------------------------------- scheduling
    async def _scheduler(self) -> None:
        while True:
            await self.wake.wait()
            self.wake.clear()
            try:
                self._dispatch()
            except Exception:  # never let the scheduler die
                log.exception("dispatch failed")

    def _dispatch(self) -> None:
        if self.db.flag("ai_paused"):
            return
        while True:
            free = [w for w in self.workers if w.busy_job is None and w.healthy]
            if not free:
                return
            job = self.db.one("SELECT * FROM jobs WHERE status='queued' ORDER BY priority, id LIMIT 1")
            if not job:
                return
            last = self.db.value("SELECT last_worker FROM teams WHERE id=?", (job["team_id"],))
            worker = next((w for w in free if w.name == last), free[0])
            worker.busy_job = job["id"]
            self.db.execute("UPDATE jobs SET status='running', worker=?, started_at=? WHERE id=?",
                            (worker.name, now(), job["id"]))
            self.db.execute("UPDATE teams SET last_worker=? WHERE id=?", (worker.name, job["team_id"]))
            self._spawn(self._run(job, worker))

    def queue_snapshot(self) -> list[dict]:
        return self.db.all(
            "SELECT j.id, j.team_id, j.kind, j.status, j.worker, j.request, j.created_at, j.started_at, "
            "t.name AS team_name, t.emoji AS team_emoji FROM jobs j JOIN teams t ON t.id=j.team_id "
            "WHERE j.status IN ('queued','running','testing') ORDER BY j.priority, j.id"
        )

    def average_seconds(self) -> float:
        if not self.durations:
            return 90.0
        recent = self.durations[-10:]
        return sum(recent) / len(recent)

    def broadcast_positions(self) -> None:
        queued = self.db.all("SELECT id, team_id FROM jobs WHERE status='queued' ORDER BY priority, id")
        n_workers = max(1, sum(1 for w in self.workers if w.healthy))
        avg = self.average_seconds()
        for pos, job in enumerate(queued, 1):
            eta = int(avg * ((pos - 1) // n_workers + 1))
            self.hub.publish(job["team_id"], {"type": "position", "job_id": job["id"], "position": pos, "eta": eta})

    # ---------------------------------------------------------------- running
    async def _run(self, job: dict, worker: Worker) -> None:
        started = time.monotonic()
        team_id, job_id = job["team_id"], job["id"]
        try:
            messages, max_tokens = self._messages_for(job)
            self._event(team_id, job_id, "thinking", worker=worker.name)
            self.broadcast_positions()

            reply_parts: list[str] = []
            first_token_at: float | None = None
            n_chunks = 0
            async for chunk in worker.client.stream_chat(messages, max_tokens, self.settings.temperature):
                if self._cancelled(job_id):
                    return
                if first_token_at is None:
                    first_token_at = time.monotonic()
                    self._event(team_id, job_id, "writing")
                reply_parts.append(chunk)
                n_chunks += 1
                self.hub.publish(team_id, {"type": "token", "job_id": job_id, "text": chunk})
            reply = "".join(reply_parts)

            if first_token_at:
                gen_time = max(0.001, time.monotonic() - first_token_at)
                worker.tokens_per_sec = round(n_chunks / gen_time, 1)
            worker.jobs_done += 1
            self.db.execute("UPDATE jobs SET reply=?, tokens=? WHERE id=?", (reply, n_chunks, job_id))

            if self._cancelled(job_id):
                return
            if job["kind"] == "explain":
                self._finish(job_id, "done", message=reply.strip())
                self.hub.publish(team_id, {"type": "explain", "job_id": job_id, "text": reply.strip()})
            else:
                self._handle_edit_reply(job, reply)
        except Exception as e:  # the Pi fell over, the network dropped, etc.
            log.exception("job %s failed on %s", job_id, worker.name)
            worker.healthy = False
            retries = self.infra_retries.get(job_id, 0)
            if retries < 2 and not self._cancelled(job_id):
                # Put it back for the other Pi (or this one, once it recovers) to try.
                self.infra_retries[job_id] = retries + 1
                self.db.execute("UPDATE jobs SET status='queued', worker=NULL WHERE id=?", (job_id,))
                self._event(team_id, job_id, "queued", message=f"The AI on {worker.name} had a problem, trying again.")
            else:
                self._finish(job_id, "failed", message=f"The AI had a problem: {e}")
                self._event(team_id, job_id, "failed", message="The AI had a problem. Please try again.")
        finally:
            self.durations.append(time.monotonic() - started)
            worker.busy_job = None
            self.broadcast_positions()
            self.notify()

    def _messages_for(self, job: dict) -> tuple[list[dict], int]:
        if job["kind"] == "explain":
            return prompts.explain_messages(job["snippet"]), self.settings.explain_max_tokens
        code = self.db.value("SELECT code FROM versions WHERE id=?", (job["base_version_id"],)) or ""
        if job["kind"] == "fix":
            return prompts.fix_messages(code, job["request"], job["error_in"]), self.settings.edit_max_tokens
        return prompts.edit_messages(code, job["request"]), self.settings.edit_max_tokens

    def _handle_edit_reply(self, job: dict, reply_text: str) -> None:
        team_id, job_id = job["team_id"], job["id"]
        base = self.db.one("SELECT * FROM versions WHERE id=?", (job["base_version_id"],))
        reply = parse_reply(reply_text)
        self.db.execute("UPDATE jobs SET plan=? WHERE id=?", (reply.plan, job_id))
        result = apply_reply(base["code"], reply)

        if not result.ok:
            error = " ".join(result.errors)
            if reply.plan.lower().startswith("let's try a different idea"):
                self._finish(job_id, "failed", message=reply.plan)
                self._event(team_id, job_id, "failed", message="Let's try a different idea!")
                return
            self._retry_or_give_up(job, error, retry_from=base["id"])
            return

        version_id = self.db.execute(
            "INSERT INTO versions(game_id, parent_id, code, request, plan, status, job_id, created_at) "
            "VALUES(?,?,?,?,?, 'testing', ?, ?)",
            (job["game_id"], base["id"], result.code, job["request"], reply.plan, job_id, now()),
        )
        self.db.execute("UPDATE jobs SET status='testing', result_version_id=?, finished_at=? WHERE id=?",
                        (version_id, now(), job_id))
        self._event(team_id, job_id, "testing", version_id=version_id, plan=reply.plan)

    def report_test(self, version_id: int, ok: bool, error: str) -> dict:
        """Called when the scouts' browser has tried running the new version."""
        version = self.db.one("SELECT * FROM versions WHERE id=?", (version_id,))
        if not version or version["status"] != "testing":
            return {"status": version["status"] if version else "missing"}
        job = self.db.one("SELECT * FROM jobs WHERE id=?", (version["job_id"],))

        if ok:
            self.db.execute("UPDATE versions SET status='ok' WHERE id=?", (version_id,))
            self.db.execute("UPDATE games SET current_version_id=? WHERE id=?", (version_id, version["game_id"]))
            if job:
                self._finish(job["id"], "done")
                self._event(job["team_id"], job["id"], "done", version_id=version_id, plan=version["plan"])
            return {"status": "ok"}

        self.db.execute("UPDATE versions SET status='broken', error=? WHERE id=?", (error[:1000], version_id))
        if job:
            self._retry_or_give_up(job, error, retry_from=version_id)
        return {"status": "broken"}

    def _retry_or_give_up(self, job: dict, error: str, retry_from: int) -> None:
        team_id = job["team_id"]
        fixes_so_far = job["attempt"] if job["kind"] == "fix" else 0
        if fixes_so_far < MAX_FIX_ATTEMPTS and job["status"] != "cancelled":
            self._finish(job["id"], "failed", message=f"Needed fixing: {error[:300]}")
            self._event(team_id, job["id"], "fixing", message=error[:300])
            self.submit(team_id=team_id, game_id=job["game_id"], kind="fix", request=job["request"],
                        base_version_id=retry_from, error_in=error[:1000], attempt=fixes_so_far + 1)
        else:
            self._finish(job["id"], "failed", message=error[:300])
            self._event(team_id, job["id"], "gave_up",
                        message="The AI got confused. Your game is safe. Try saying it a different way!")

    # ----------------------------------------------------------------- helpers
    def _cancelled(self, job_id: int) -> bool:
        return self.db.value("SELECT status FROM jobs WHERE id=?", (job_id,)) == "cancelled"

    def _finish(self, job_id: int, status: str, message: str = "") -> None:
        self.db.execute("UPDATE jobs SET status=?, message=?, finished_at=? WHERE id=?",
                        (status, message, now(), job_id))

    def _event(self, team_id: int, job_id: int, stage: str, **extra) -> None:
        self.hub.publish(team_id, {"type": "job", "job_id": job_id, "stage": stage, **extra})

    # ------------------------------------------------------------------ health
    async def _health_loop(self) -> None:
        while True:
            for w in self.workers:
                if w.busy_job is None:
                    was = w.healthy
                    w.healthy = await w.client.healthy()
                    if w.healthy and not was:
                        log.info("worker %s is back", w.name)
                        self.notify()
                if w.stats_url:
                    w.stats = await _fetch_stats(w.stats_url)
            await asyncio.sleep(10)


def _in_loop(loop: asyncio.AbstractEventLoop | None, fn, *args) -> None:
    """Run fn now if we're on the loop's thread, otherwise schedule it there."""
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if loop is None or running is loop:
        fn(*args)
    elif not loop.is_closed():
        loop.call_soon_threadsafe(fn, *args)


async def _fetch_stats(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url.rstrip("/") + "/stats")
            return r.json()
    except Exception:
        return {}
