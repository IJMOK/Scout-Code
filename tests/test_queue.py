import asyncio

from server.db import DB
from server.jobqueue import Hub, JobQueue, Worker
from server.llm import MockLLM


class _Settings:
    temperature = 0.2
    edit_max_tokens = 200
    explain_max_tokens = 100
    use_grammar = True


def setup_db(tmp_path, teams=4):
    db = DB(tmp_path / "q.db")
    code = 'const CONFIG = {\n  title: "Game",\n  player: "🚀",\n};\nfunction loop() {\n  requestAnimationFrame(loop);\n}\n'
    for t in range(1, teams + 1):
        db.execute("INSERT INTO teams(id, name, emoji, pin, token, created_at) VALUES(?,?,?,?,?,0)",
                   (t, f"T{t}", "🦊", "1234", f"tok{t}"))
        db.execute("INSERT INTO games(id, team_id, starter, title, created_at) VALUES(?,?,'x','X',0)", (t, t))
        db.execute("INSERT INTO versions(id, game_id, code, status, created_at) VALUES(?,?,?,'ok',0)", (t, t, code))
    return db


def test_fixes_first_then_edits_in_order_then_explains(tmp_path):
    db = setup_db(tmp_path)
    db.set_setting("ai_paused", "1")

    async def scenario():
        q = JobQueue(db, [Worker("solo", MockLLM(0))], Hub(), _Settings())
        q.start()
        ids = {
            "edit1": q.submit(team_id=1, game_id=1, kind="edit", request="make it red", base_version_id=1),
            "explain": q.submit(team_id=2, game_id=2, kind="explain", request="explain", snippet="x = 1",
                                base_version_id=2),
            "edit3": q.submit(team_id=3, game_id=3, kind="edit", request="make it blue", base_version_id=3),
            "fix": q.submit(team_id=4, game_id=4, kind="fix", request="make it green", base_version_id=4,
                            error_in="oops", attempt=1),
        }
        db.set_setting("ai_paused", "0")
        q.notify()
        for _ in range(300):
            if not db.value("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"):
                break
            await asyncio.sleep(0.01)
        await q.stop()
        return ids

    ids = asyncio.run(scenario())
    order = [r["id"] for r in db.all("SELECT id FROM jobs ORDER BY started_at")]
    assert order == [ids["fix"], ids["edit1"], ids["edit3"], ids["explain"]]


def test_two_workers_share_the_load(tmp_path):
    db = setup_db(tmp_path, teams=4)

    async def scenario():
        workers = [Worker("pi-1", MockLLM(0.002)), Worker("pi-2", MockLLM(0.002))]
        q = JobQueue(db, workers, Hub(), _Settings())
        q.start()
        for t in range(1, 5):
            q.submit(team_id=t, game_id=t, kind="edit", request="make it red", base_version_id=t)
        for _ in range(500):
            if not db.value("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"):
                break
            await asyncio.sleep(0.01)
        await q.stop()

    asyncio.run(scenario())
    used = {r["worker"] for r in db.all("SELECT worker FROM jobs")}
    assert used == {"pi-1", "pi-2"}
    assert db.value("SELECT COUNT(*) FROM jobs WHERE status='testing'") == 4
