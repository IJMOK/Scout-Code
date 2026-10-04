"""Putting games online: the built site, a real git push (to a local repo), GitHub API handling and clear-down."""

import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from server import publish
from server.app import create_app
from server.config import Settings

TOKEN = "github_pat_SECRET_token_1234"


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path / "data", mock=True, mock_delay=0, leader_pin="123456", warmup=False))


def team(app, name, emoji="🦊"):
    c = TestClient(app)
    code = app.state.db.get_setting("join_code")
    assert c.post("/api/teams", json={"name": name, "emoji": emoji, "join_code": code}).status_code == 200
    return c


def game(c, starter, title, publish_it=True):
    gid = c.post("/api/games", json={"starter": starter}).json()["id"]
    if publish_it:
        c.post(f"/api/games/{gid}/publish", json={"title": title, "description": "Arrows to move"})
    return gid


@pytest.fixture
def event(app):
    """An evening: two real teams, a hidden game, an unpublished game and the leaders' demo game."""
    a, b = team(app, "Pixel Wolves", "🐺"), team(app, "Owl Squad", "🦉")
    ga = game(a, "flappy", "Chick Rush")
    gb = game(b, "maze", "Mouse Run")
    hidden = game(b, "snake", "Hidden Snake")
    game(a, "catch", "Draft", publish_it=False)
    b.post(f"/api/arcade/{ga}/rate", json={"stars": 5})
    b.post(f"/api/arcade/{ga}/vote", json={"category": "fun"})
    leader = TestClient(app)
    leader.post("/api/leader/login", json={"pin": "123456"})
    leader.post(f"/api/leader/games/{hidden}/hide", json={"hidden": True})
    leader.post("/api/leader/settings", json={"event_name": "Wolves Game Night"})
    demo = TestClient(app)
    demo.post("/api/leader/login", json={"pin": "123456"})
    demo.post("/api/leader/demo-team")
    game(demo, "breakout", "Leaders Demo Game")
    return {"leader": leader, "ga": ga, "gb": gb}


def bare_repo(tmp_path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    return bare


def git(bare: Path, *args) -> str:
    return subprocess.run(["git", "--git-dir", str(bare), *args], capture_output=True, text=True, check=True).stdout


def configure(leader, app, bare, **extra):
    body = {"repo": "1st-anytown/scout-games", "token": TOKEN, "checklist_done": True, **extra}
    assert leader.post("/api/leader/publish/settings", json=body).status_code == 200
    s = publish.load_settings(app.state.settings.data_dir)
    s.git_url = bare.as_uri()  # push to a local repo instead of GitHub
    publish.save_settings(app.state.settings.data_dir, s)


def test_full_publish_to_a_repo(app, event, tmp_path):
    leader = event["leader"]
    bare = bare_repo(tmp_path)
    configure(leader, app, bare)

    session = leader.post("/api/leader/publish/tonight").json()["session"]
    assert session["online"] and session["expires"] > time.time() + 29 * publish.DAY
    app.state.publisher.sync(wait=True)
    assert app.state.publisher.status["state"] == "ok", app.state.publisher.status

    files = set(git(bare, "ls-tree", "-r", "--name-only", "main").split())
    slug = session["slug"]
    assert {"index.html", "sessions.json", "robots.txt", ".nojekyll", "404.html", "tools/expire.py",
            ".github/workflows/expire.yml", f"s/{slug}/index.html"} <= files
    games = {f for f in files if "/games/" in f}
    assert games == {f"s/{slug}/games/{event['ga']}.html", f"s/{slug}/games/{event['gb']}.html"}

    def show(path):
        return git(bare, "show", f"main:{path}")

    page = show(f"s/{slug}/index.html")
    assert "Chick Rush" in page and "Mouse Run" in page and "Pixel Wolves" in page
    for absent in ("Hidden Snake", "Leaders Demo Game", "Draft", "Leaders' demo"):
        assert absent not in page
    assert "Most Fun" in page  # the evening's awards
    for path in [f for f in files if f.endswith(".html")]:
        assert 'name="robots" content="noindex, nofollow"' in show(path), path
    game_html = show(f"s/{slug}/games/{event['ga']}.html")
    assert "default-src 'none'" in game_html and "ontouchstart" in game_html
    assert show("robots.txt") == "User-agent: *\nDisallow: /\n"
    sessions = json.loads(show("sessions.json"))
    assert sessions == [{"slug": slug, "title": "Wolves Game Night", "games": 2,
                         "expires": session["expires"], "date": time.strftime("%Y-%m-%d")}]

    # The token never leaks: not in the site, the API, or the git history.
    assert TOKEN not in json.dumps(leader.get("/api/leader/publish").json())
    assert TOKEN not in git(bare, "log", "-p", "main")
    assert git(bare, "rev-list", "--count", "main").strip() == "1"


def test_taking_offline_leaves_no_trace(app, event, tmp_path):
    leader = event["leader"]
    bare = bare_repo(tmp_path)
    configure(leader, app, bare)
    slug = leader.post("/api/leader/publish/tonight").json()["session"]["slug"]
    app.state.publisher.sync(wait=True)
    assert f"s/{slug}/index.html" in git(bare, "ls-tree", "-r", "--name-only", "main")

    leader.post("/api/leader/publish/offline")
    for _ in range(100):
        if app.state.publisher.status["state"] != "syncing":
            break
        time.sleep(0.05)
    files = git(bare, "ls-tree", "-r", "--name-only", "main")
    assert not any(f.startswith("s/") for f in files.split()) and json.loads(git(bare, "show", "main:sessions.json")) == []
    # Force-pushed as a single fresh commit: the old session isn't in the branch's history either.
    assert git(bare, "rev-list", "--count", "main").strip() == "1"
    assert "Chick Rush" not in git(bare, "log", "-p", "main")


def test_options_hide_names_exclude_games_and_expiry(app, event, tmp_path):
    leader = event["leader"]
    data_dir = app.state.settings.data_dir
    leader.post("/api/leader/publish/settings", json={"repo": "a/b", "hide_team_names": True})
    session = leader.post("/api/leader/publish/tonight").json()["session"]
    games = leader.get(f"/api/leader/publish/sessions/{session['name']}/games").json()
    assert {g["title"] for g in games} == {"Chick Rush", "Mouse Run"}
    leader.post(f"/api/leader/publish/sessions/{session['name']}", json={"excluded": [event["gb"]]})

    out = tmp_path / "site"
    built = publish.build_site(data_dir, out, publish.load_settings(data_dir))
    page = (out / "s" / session["slug"] / "index.html").read_text()
    assert "Team 1" in page and "Pixel Wolves" not in page and "Owl Squad" not in page
    assert "Mouse Run" not in page and built[0]["games"] == 1

    # Expired sessions are left out of the next build.
    built = publish.build_site(data_dir, out, publish.load_settings(data_dir), now=session["expires"] + 1)
    assert built == [] and not (out / "s").exists()


def test_republishing_refreshes_the_same_session(app, event):
    leader = event["leader"]
    first = leader.post("/api/leader/publish/tonight").json()["session"]
    second = leader.post("/api/leader/publish/tonight").json()["session"]
    assert first["name"] == second["name"] and first["slug"] == second["slug"]
    # ...and "Start a new event" later refreshes that same snapshot too.
    archived = leader.post("/api/leader/new-event", json={"event_name": "Next"}).json()["archive"]
    assert archived["name"] == first["name"]
    sessions = leader.get("/api/leader/publish").json()["sessions"]
    assert len(sessions) == 1 and sessions[0]["online"]


def test_expire_script_removes_old_sessions(app, event, tmp_path):
    leader = event["leader"]
    data_dir = app.state.settings.data_dir
    session = leader.post("/api/leader/publish/tonight").json()["session"]
    out = tmp_path / "site"
    publish.build_site(data_dir, out, publish.load_settings(data_dir))
    # Pretend time has passed: mark it expired in the published index.
    index = json.loads((out / "sessions.json").read_text())
    index[0]["expires"] = time.time() - 60
    (out / "sessions.json").write_text(json.dumps(index))
    run = subprocess.run([sys.executable, str(out / "tools" / "expire.py")], capture_output=True, text=True, check=True)
    assert "Removed expired session" in run.stdout
    assert not (out / "s" / session["slug"]).exists()
    assert json.loads((out / "sessions.json").read_text()) == []


def test_sync_refuses_without_setup_or_checklist(app, event):
    leader = event["leader"]
    app.state.publisher.sync(wait=True)
    assert "repository and token" in app.state.publisher.status["message"]
    leader.post("/api/leader/publish/settings", json={"repo": "a/b", "token": "t"})
    app.state.publisher.sync(wait=True)
    assert "checklist" in app.state.publisher.status["message"]


def test_preview_and_zip(app, event):
    leader = event["leader"]
    leader.post("/api/leader/publish/tonight")
    url = leader.post("/api/leader/publish/preview").json()["url"]
    assert "Our Scout Code games" in leader.get(url).text
    sessions = leader.get("/api/leader/publish").json()["sessions"]
    page = leader.get(f"/leader/site-preview/s/{sessions[0]['slug']}/").text
    assert "Chick Rush" in page
    game_page = leader.get(f"/leader/site-preview/s/{sessions[0]['slug']}/games/{event['ga']}.html")
    assert "sandbox allow-scripts" in game_page.headers["content-security-policy"]
    assert leader.get("/leader/site-preview/../publish.json").status_code == 404
    assert TestClient(app).get(url).status_code == 404  # leaders only
    z = leader.get("/api/leader/publish/site.zip")
    assert z.status_code == 200 and z.content[:2] == b"PK"


def test_settings_validation_and_token_masking(app, event):
    leader = event["leader"]
    assert leader.post("/api/leader/publish/settings", json={"repo": "not a repo"}).status_code == 400
    r = leader.post("/api/leader/publish/settings",
                    json={"repo": "https://github.com/1st-anytown/scout-games/", "token": TOKEN}).json()
    assert r["settings"]["repo"] == "1st-anytown/scout-games"
    assert r["settings"]["token_hint"] == "••••1234" and "token" not in r["settings"]
    # Saving other settings without a token keeps the saved one.
    leader.post("/api/leader/publish/settings", json={"site_title": "Our games", "token": ""})
    assert publish.load_settings(app.state.settings.data_dir).token == TOKEN
    status = leader.get("/api/leader/publish").json()
    assert status["site_url"] == "https://1st-anytown.github.io/scout-games/"
    assert TestClient(app).get("/api/leader/publish").status_code == 401


# --------------------------------------------------------------------------- fake GitHub API

@pytest.fixture
def fake_github():
    gh = FastAPI()
    gh.state.pages = set()

    @gh.get("/repos/{owner}/{repo}")
    def repo(owner: str, repo: str, request: Request):
        token = request.headers.get("authorization", "")
        if token == "Bearer bad":
            return JSONResponse({"message": "Bad credentials"}, 401)
        if repo == "missing":
            return JSONResponse({"message": "Not Found"}, 404)
        return {"full_name": f"{owner}/{repo}", "permissions": {"push": token != "Bearer readonly"}}

    @gh.get("/repos/{owner}/{repo}/pages")
    def pages(owner: str, repo: str):
        if f"{owner}/{repo}" not in gh.state.pages:
            return JSONResponse({"message": "Not Found"}, 404)
        return {"html_url": f"https://{owner}.github.io/{repo}/"}

    @gh.post("/repos/{owner}/{repo}/pages")
    async def enable(owner: str, repo: str, request: Request):
        if request.headers.get("authorization") == "Bearer nopages":
            return JSONResponse({"message": "Resource not accessible"}, 403)
        assert (await request.json())["source"] == {"branch": "main", "path": "/"}
        gh.state.pages.add(f"{owner}/{repo}")
        return JSONResponse({"html_url": f"https://{owner}.github.io/{repo}/"}, 201)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(gh, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def gh_settings(api, token="good", repo="scouts/games"):
    return publish.PublishSettings(repo=repo, token=token, api_url=api)


def test_connection_messages(fake_github):
    assert publish.test_connection(gh_settings(fake_github)) == "Connected to scouts/games."
    cases = [("bad", "scouts/games", "didn't accept the token"), ("good", "scouts/missing", "Can't find"),
             ("readonly", "scouts/games", "can't change it"), ("good", "nope", "owner/name")]
    for token, repo, message in cases:
        with pytest.raises(publish.PublishError, match=message):
            publish.test_connection(gh_settings(fake_github, token, repo))
    with pytest.raises(publish.PublishError, match="connected to the internet"):
        publish.test_connection(gh_settings("http://127.0.0.1:1"))


def test_enable_pages(fake_github):
    assert publish.enable_pages(gh_settings(fake_github)) == "https://scouts.github.io/games/"
    with pytest.raises(publish.PublishError, match="Settings → Pages"):
        publish.enable_pages(gh_settings(fake_github, token="nopages", repo="other/site"))
