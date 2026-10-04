import time

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Settings


@pytest.fixture
def app(tmp_path):
    settings = Settings(data_dir=tmp_path, mock=True, mock_delay=0.0, leader_pin="123456")
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def join_code(app):
    return app.state.db.get_setting("join_code")


def make_team(app, name="Foxes"):
    c = TestClient(app)
    r = c.post("/api/teams", json={"name": name, "emoji": "🦊", "join_code": join_code(app)})
    assert r.status_code == 200, r.text
    return c, r.json()


def wait_for(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        result = fn()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError("timed out")


def new_game(c, starter="space-shooter"):
    r = c.post("/api/games", json={"starter": starter})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_join_code_and_login(client, app):
    r = client.post("/api/teams", json={"name": "Owls", "emoji": "🦉", "join_code": "nope"})
    assert r.status_code == 400
    r = client.post("/api/teams", json={"name": "Owls", "emoji": "🦉", "join_code": join_code(app)})
    pin = r.json()["pin"]
    assert len(pin) == 4
    assert client.post("/api/teams", json={"name": "owls", "emoji": "🦉", "join_code": join_code(app)}).status_code == 400
    other = TestClient(app)
    assert other.post("/api/login", json={"name": "Owls", "pin": "wrong"}).status_code == 400
    assert other.post("/api/login", json={"name": "owls", "pin": pin}).status_code == 200
    assert other.get("/api/me").json()["team"]["name"] == "Owls"


def test_rude_team_name_blocked(client, app):
    r = client.post("/api/teams", json={"name": "Shit Team", "emoji": "🦉", "join_code": join_code(app)})
    assert r.status_code == 400


def test_agent_loop_success(client, app):
    c, _ = make_team(app, "Foxes")
    gid = new_game(c)
    r = c.post(f"/api/games/{gid}/ask", json={"request": "make the player a 🦖"})
    assert r.status_code == 200, r.text
    # Only one job at a time per team
    assert c.post(f"/api/games/{gid}/ask", json={"request": "and faster"}).status_code == 409

    vid = wait_for(lambda: c.get(f"/api/games/{gid}").json()["pending_test_version_id"])
    v = c.get(f"/api/versions/{vid}").json()
    assert '"🦖"' in v["code"] and v["status"] == "testing"
    assert v["plan"]

    assert c.post(f"/api/versions/{vid}/test", json={"ok": True}).json()["status"] == "ok"
    g = c.get(f"/api/games/{gid}").json()
    assert g["current"]["id"] == vid
    assert g["active_job"] is None


def test_agent_loop_auto_fix(client, app):
    c, _ = make_team(app, "Wolves")
    gid = new_game(c, "snake")
    first = c.get(f"/api/games/{gid}").json()["current"]["id"]
    c.post(f"/api/games/{gid}/ask", json={"request": "BREAK it please"})
    vid = wait_for(lambda: c.get(f"/api/games/{gid}").json()["pending_test_version_id"])
    assert "mockExplodes" in c.get(f"/api/versions/{vid}").json()["code"]

    # Browser reports a crash -> the agent queues a fix job automatically
    c.post(f"/api/versions/{vid}/test", json={"ok": False, "error": "ReferenceError: mockExplodes is not defined"})
    fixed = wait_for(lambda: (c.get(f"/api/games/{gid}").json()["pending_test_version_id"] or 0) > vid
                     and c.get(f"/api/games/{gid}").json()["pending_test_version_id"])
    code = c.get(f"/api/versions/{fixed}").json()["code"]
    assert "mockExplodes" not in code
    c.post(f"/api/versions/{fixed}/test", json={"ok": True})
    g = c.get(f"/api/games/{gid}").json()
    assert g["current"]["id"] == fixed != first
    statuses = [v["status"] for v in g["versions"]]
    assert statuses == ["ok", "broken", "ok"]


def test_agent_gives_up_after_one_fix(client, app):
    c, _ = make_team(app, "Bears")
    gid = new_game(c, "catch")
    first = c.get(f"/api/games/{gid}").json()["current"]["id"]
    c.post(f"/api/games/{gid}/ask", json={"request": "NOMATCH please"})
    # NOMATCH -> fix job -> mock fix makes a title edit... which the browser says is broken too
    vid = wait_for(lambda: c.get(f"/api/games/{gid}").json()["pending_test_version_id"])
    c.post(f"/api/versions/{vid}/test", json={"ok": False, "error": "still broken"})
    g = wait_for(lambda: (lambda g: g if g["active_job"] is None else None)(c.get(f"/api/games/{gid}").json()))
    assert g["current"]["id"] == first  # game is safe
    jobs = app.state.db.all("SELECT kind, status FROM jobs ORDER BY id")
    assert [j["kind"] for j in jobs] == ["edit", "retry"]
    assert all(j["status"] == "failed" for j in jobs)


def test_explain(client, app):
    c, _ = make_team(app, "Lions")
    gid = new_game(c)
    r = c.post(f"/api/games/{gid}/explain", json={"snippet": "player.x += CONFIG.playerSpeed;"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    msg = wait_for(lambda: app.state.db.value("SELECT message FROM jobs WHERE id=? AND status='done'", (job_id,)))
    assert "player" in msg


def test_rude_request_blocked(client, app):
    c, _ = make_team(app)
    gid = new_game(c)
    assert c.post(f"/api/games/{gid}/ask", json={"request": "add some f u c k words"}).status_code == 400


def test_cannot_touch_other_teams_games(client, app):
    a, _ = make_team(app, "Alpha")
    b, _ = make_team(app, "Bravo")
    gid = new_game(a)
    assert b.get(f"/api/games/{gid}").status_code == 404
    assert b.post(f"/api/games/{gid}/ask", json={"request": "make it red"}).status_code == 404
    vid = a.get(f"/api/games/{gid}").json()["current"]["id"]
    assert b.get(f"/play/{vid}").status_code == 404
    assert a.get(f"/play/{vid}").status_code == 200


def test_play_has_sandbox_csp(client, app):
    a, _ = make_team(app)
    gid = new_game(a)
    vid = a.get(f"/api/games/{gid}").json()["current"]["id"]
    r = a.get(f"/play/{vid}")
    assert "sandbox allow-scripts" in r.headers["content-security-policy"]
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_publish_rate_vote_awards(client, app):
    a, _ = make_team(app, "Alpha")
    b, _ = make_team(app, "Bravo")
    c, _ = make_team(app, "Charlie")
    ga = new_game(a, "flappy")
    gb = new_game(b, "maze")
    assert a.post(f"/api/games/{ga}/publish", json={"title": "Super Chick"}).status_code == 200
    assert b.post(f"/api/games/{gb}/publish", json={"title": "Mouse Run"}).status_code == 200

    games = c.get("/api/arcade").json()["games"]
    assert {g["title"] for g in games} == {"Super Chick", "Mouse Run"}
    # Published games are playable by anyone
    vid = next(g["version_id"] for g in games if g["id"] == ga)
    assert c.get(f"/play/{vid}").status_code == 200

    # Can't rate your own
    assert a.post(f"/api/arcade/{ga}/rate", json={"stars": 5}).status_code == 400
    assert b.post(f"/api/arcade/{ga}/rate", json={"stars": 4, "reaction": "🔥"}).status_code == 200
    assert c.post(f"/api/arcade/{ga}/rate", json={"stars": 5}).status_code == 200
    assert c.post(f"/api/arcade/{ga}/rate", json={"stars": 3}).status_code == 200  # changing mind is fine
    assert a.post(f"/api/arcade/{gb}/rate", json={"stars": 2}).status_code == 200
    assert c.post(f"/api/arcade/{gb}/vote", json={"category": "fun"}).status_code == 200
    assert a.post(f"/api/arcade/{gb}/vote", json={"category": "fun"}).status_code == 200

    g = next(g for g in c.get("/api/arcade").json()["games"] if g["id"] == ga)
    assert g["avg_stars"] == 3.5 and g["ratings"] == 2 and g["reactions"] == {"🔥": 1} and g["my_rating"] == 3

    # Awards hidden until a leader reveals them
    assert c.get("/api/awards").json()["awards"] == []
    leader = TestClient(app)
    assert leader.post("/api/leader/login", json={"pin": "000000"}).status_code == 400
    assert leader.post("/api/leader/login", json={"pin": "123456"}).status_code == 200
    leader.post("/api/leader/settings", json={"voting_frozen": True, "awards_revealed": True})
    assert c.post(f"/api/arcade/{gb}/rate", json={"stars": 5}).status_code == 409
    awards = {a["category"]: a for a in c.get("/api/awards").json()["awards"]}
    assert awards["stars"]["game"]["title"] == "Super Chick"
    assert awards["fun"]["game"]["title"] == "Mouse Run"

    # Hidden games vanish from the arcade
    leader.post(f"/api/leader/games/{ga}/hide", json={"hidden": True})
    assert [g["title"] for g in c.get("/api/arcade").json()["games"]] == ["Mouse Run"]


def test_leader_endpoints_need_login(client, app):
    assert client.get("/api/leader/status").status_code == 401
    assert client.get("/api/leader/export.zip").status_code == 401


def test_export_zip(client, app):
    import io
    import zipfile

    a, _ = make_team(app, "Alpha")
    new_game(a, "breakout")
    leader = TestClient(app)
    leader.post("/api/leader/login", json={"pin": "123456"})
    status = leader.get("/api/leader/status").json()
    assert status["teams"][0]["name"] == "Alpha"
    r = leader.get("/api/leader/export.zip")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "index.html" in names
    assert any(n.startswith("alpha/") and n.endswith("brick-breaker.html") for n in names)


def test_paused_ai_rejects_requests(client, app):
    a, _ = make_team(app)
    gid = new_game(a)
    leader = TestClient(app)
    leader.post("/api/leader/login", json={"pin": "123456"})
    leader.post("/api/leader/settings", json={"ai_paused": True})
    assert a.post(f"/api/games/{gid}/ask", json={"request": "make it red"}).status_code == 409


def test_restore_only_ok_versions(client, app):
    c, _ = make_team(app, "Owls")
    gid = new_game(c)
    first = c.get(f"/api/games/{gid}").json()["current"]["id"]
    c.post(f"/api/games/{gid}/ask", json={"request": "make it red"})
    vid = wait_for(lambda: c.get(f"/api/games/{gid}").json()["pending_test_version_id"])
    assert c.post(f"/api/games/{gid}/restore", json={"version_id": vid}).status_code == 400
    c.post(f"/api/versions/{vid}/test", json={"ok": True})
    assert c.post(f"/api/games/{gid}/restore", json={"version_id": first}).status_code == 200
    assert c.get(f"/api/games/{gid}").json()["current"]["id"] == first


def test_unusable_answer_gets_a_retry_prompt_on_the_original(client, app):
    """An edit that can't be applied is retried with "could not be used", not "broke the game"."""

    c, _ = make_team(app, "Retry")
    gid = new_game(c, "snake")
    first = c.get(f"/api/games/{gid}").json()["current"]["id"]
    c.post(f"/api/games/{gid}/ask", json={"request": "NOMATCH please"})
    wait_for(lambda: c.get(f"/api/games/{gid}").json()["pending_test_version_id"])
    retry = app.state.db.one("SELECT * FROM jobs WHERE kind='retry'")
    assert retry["base_version_id"] == first
    assert "could not find" in retry["error_in"]
    msgs, _ = app.state.jobs._messages_for(retry)
    assert "Your last answer could not be used" in msgs[-1]["content"]
    assert "broke the game" not in msgs[-1]["content"]


def test_partial_edit_accepted_on_the_retry(client, app):
    c, _ = make_team(app, "Half")
    gid = new_game(c, "catch")
    c.post(f"/api/games/{gid}/ask", json={"request": "HALFMATCH please"})
    vid = wait_for(lambda: c.get(f"/api/games/{gid}").json()["pending_test_version_id"])
    v = c.get(f"/api/versions/{vid}").json()
    assert 'title: "Fruit Catcher 2",' in v["code"]
    assert "didn't fit" in v["plan"]
    kinds = [j["kind"] for j in app.state.db.all("SELECT kind FROM jobs ORDER BY id")]
    assert kinds == ["edit", "retry"]


def leader_client(app):
    leader = TestClient(app)
    assert leader.post("/api/leader/login", json={"pin": "123456"}).status_code == 200
    return leader


def test_new_event_archives_then_resets(client, app, tmp_path):
    import io
    import sqlite3
    import zipfile

    a, _ = make_team(app, "Alpha")
    b, _ = make_team(app, "Bravo")
    ga = new_game(a, "flappy")
    a.post(f"/api/games/{ga}/publish", json={"title": "Chick Rush"})
    b.post(f"/api/arcade/{ga}/rate", json={"stars": 5})
    leader = leader_client(app)
    leader.post("/api/leader/settings", json={"event_name": "Wolves Night", "voting_frozen": True})
    old_code = app.state.db.get_setting("join_code")

    r = leader.post("/api/leader/new-event", json={"event_name": "Owls Night"})
    assert r.status_code == 200, r.text
    archive = r.json()["archive"]
    assert archive["event_name"] == "Wolves Night" and archive["teams"] == 2 and archive["games"] == 1

    # Everything was saved...
    folder = tmp_path / "archive" / archive["name"]
    saved = sqlite3.connect(folder / "scout.db")
    assert saved.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 2
    assert saved.execute("SELECT stars FROM ratings").fetchone()[0] == 5
    z = zipfile.ZipFile(io.BytesIO(leader.get(f"/api/leader/archives/{archive['name']}/games.zip").content))
    assert any(n.endswith("chick-rush.html") for n in z.namelist())
    assert [x["event_name"] for x in leader.get("/api/leader/archives").json()] == ["Wolves Night"]

    # ...and then cleared for the next group.
    db = app.state.db
    assert all(db.value(f"SELECT COUNT(*) FROM {t}") == 0 for t in ("teams", "games", "versions", "ratings", "votes", "jobs"))
    status = leader.get("/api/leader/status").json()  # leader is still logged in
    assert status["event_name"] == "Owls Night"
    assert status["join_code"] != old_code and status["join_code"] == r.json()["join_code"]
    assert status["voting_frozen"] is False
    assert a.get("/api/me").status_code == 401  # old teams are logged out
    assert client.get("/api/arcade").json()["games"] == []

    # The new group can join with the new code
    new = TestClient(app)
    assert new.post("/api/teams", json={"name": "Alpha", "emoji": "🦊",
                                        "join_code": status["join_code"]}).status_code == 200


def test_new_event_stops_ai_jobs_cleanly(client, app):
    c, _ = make_team(app, "Busy")
    gid = new_game(c)
    leader = leader_client(app)
    leader.post("/api/leader/settings", json={"ai_paused": True})
    c.post(f"/api/games/{gid}/ask", json={"request": "make it red"})
    assert leader.post("/api/leader/new-event", json={"event_name": "Next"}).status_code == 200
    leader.post("/api/leader/settings", json={"ai_paused": False})
    # The AI is still fine for the new group.
    n, _ = make_team(app, "Fresh")
    gid2 = new_game(n)
    n.post(f"/api/games/{gid2}/ask", json={"request": "make it blue"})
    assert wait_for(lambda: n.get(f"/api/games/{gid2}").json()["pending_test_version_id"])
    assert all(w.healthy for w in app.state.jobs.workers)


def test_archive_downloads_are_guarded(client, app):
    leader = leader_client(app)
    for bad in ["../scout.db", "..%2Fscout.db", "2026-01-01-1200/../../leader-pin.txt"]:
        assert leader.get(f"/api/leader/archives/{bad}/games.zip").status_code == 404
    leader.post("/api/leader/new-event", json={"event_name": "Next"})
    name = leader.get("/api/leader/archives").json()[0]["name"]
    assert leader.get(f"/api/leader/archives/{name}/leader-pin.txt").status_code == 404
    assert client.get(f"/api/leader/archives/{name}/games.zip").status_code == 401
    assert client.post("/api/leader/new-event", json={"event_name": "Hack"}).status_code == 401


def test_two_leaders_can_be_logged_in_at_once(client, app):
    projector, helper = TestClient(app), TestClient(app)
    projector.post("/api/leader/login", json={"pin": "123456"})
    helper.post("/api/leader/login", json={"pin": "123456"})
    assert projector.get("/api/leader/status").status_code == 200
    assert helper.get("/api/leader/status").status_code == 200


def test_demo_team_is_kept_out_of_the_competition(client, app):
    import io
    import zipfile

    leader = TestClient(app)
    leader.post("/api/leader/login", json={"pin": "123456"})
    r = leader.post("/api/leader/demo-team")
    assert r.status_code == 200 and r.json()["team"]["name"] == "Leaders' demo"
    assert leader.post("/api/leader/demo-team").json()["team"]["id"] == r.json()["team"]["id"]  # same team again
    demo_game = new_game(leader, "flappy")
    leader.post(f"/api/games/{demo_game}/publish", json={"title": "Demo Chick"})

    a, _ = make_team(app, "Alpha")
    ga = new_game(a, "maze")
    a.post(f"/api/games/{ga}/publish", json={"title": "Mouse Run"})
    # Scouts can see and play the demo game, but can't vote for it.
    assert {g["title"] for g in a.get("/api/arcade").json()["games"]} == {"Demo Chick", "Mouse Run"}
    assert a.post(f"/api/arcade/{demo_game}/rate", json={"stars": 5}).status_code == 400
    assert a.post(f"/api/arcade/{demo_game}/vote", json={"category": "fun"}).status_code == 400

    # Even if it somehow had votes, it never wins and isn't exported.
    app.state.db.execute("INSERT INTO ratings(game_id, team_id, stars, created_at) VALUES(?,?,5,0)",
                         (demo_game, a.get("/api/me").json()["team"]["id"]))
    leader.post("/api/leader/settings", json={"awards_revealed": True})
    awards = leader.get("/api/awards").json()
    assert all(x["game"]["title"] != "Demo Chick" for x in awards["awards"])
    assert all(g["title"] != "Demo Chick" for g in awards["leaderboard"])
    names = zipfile.ZipFile(io.BytesIO(leader.get("/api/leader/export.zip").content)).namelist()
    assert not any("demo" in n.lower() for n in names)


def test_old_database_gets_the_demo_column(tmp_path):
    import sqlite3

    from server.db import DB

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, emoji TEXT NOT NULL, "
                "pin TEXT NOT NULL, token TEXT NOT NULL UNIQUE, last_worker TEXT, created_at REAL NOT NULL)")
    old.execute("INSERT INTO teams VALUES (1, 'Owls', '🦉', '1234', 'tok', NULL, 0)")
    old.commit()
    old.close()
    db = DB(path)
    assert db.one("SELECT name, demo FROM teams") == {"name": "Owls", "demo": 0}


def test_slides_are_for_leaders_only(client, app):
    r = client.get("/present", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/leader"
    leader = TestClient(app)
    leader.post("/api/leader/login", json={"pin": "123456"})
    assert leader.get("/present").status_code == 200
