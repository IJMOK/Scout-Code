"""Scout Code portal: the web app the scouts' laptops talk to.

Run (development, fake AI):   SCOUT_MOCK=1 uvicorn server.app:create_app --factory --reload
Run (on the Pi):              see setup/systemd/scout-portal.service
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from urllib.parse import urlparse
from contextlib import asynccontextmanager

import httpx
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import safety
from .config import ROOT, Settings, load_settings
from .archive import archive_event, archive_file, build_export, list_archives, reset_event
from .db import DB, now
from .jobqueue import Hub, JobQueue, Worker
from .llm import LlamaServer, MockLLM

log = logging.getLogger("scout")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

WEB = ROOT / "web"
STARTERS_DIR = ROOT / "server" / "starters"
STARTERS: list[dict] = json.loads((STARTERS_DIR / "starters.json").read_text(encoding="utf-8"))
STARTER_IDS = {s["id"] for s in STARTERS}

AWARD_CATEGORIES = {
    "fun": "🎉 Most Fun",
    "looks": "🎨 Best Looking",
    "creative": "💡 Most Creative",
}
REACTIONS = ["😂", "🤯", "🔥", "😍", "👏"]
TEAM_EMOJIS = ["🦊", "🐺", "🦉", "🐻", "🦁", "🐯", "🐸", "🐙", "🦄", "🐲", "🦅", "🐬", "🦖", "🐝", "🐧", "🦈"]

# The game runs as an opaque origin with no network at all, even if someone
# opens /play/... directly in a new tab.
PLAY_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
            "style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:")


# --------------------------------------------------------------------------- app setup

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = DB(settings.db_path)
    hub = Hub()
    safety.load_extra_words(settings.data_dir / "blocked-words.txt")

    if settings.mock:
        workers = [Worker(name="mock-1", client=MockLLM(settings.mock_delay)),
                   Worker(name="mock-2", client=MockLLM(settings.mock_delay))]
    else:
        workers = [Worker(name=w.name, client=LlamaServer(w.llm, settings.request_timeout, w.key()),
                          stats_url=w.stats, api_key=w.key())
                   for w in settings.workers]
    warm_sources = {s["id"]: (STARTERS_DIR / f"{s['id']}.html").read_text(encoding="utf-8") for s in STARTERS}
    jobs = JobQueue(db, workers, hub, settings, warm_sources)

    if not db.get_setting("join_code"):
        db.set_setting("join_code", _new_join_code())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        jobs.start()
        if settings.warmup:
            jobs.start_warmup()
        log.info("Scout Code ready. Leader PIN: %s  Join code: %s  Workers: %s",
                 settings.leader_pin, db.get_setting("join_code"), ", ".join(w.name for w in workers))
        yield
        await jobs.stop()

    app = FastAPI(title="Scout Code", lifespan=lifespan)
    app.state.db, app.state.jobs, app.state.hub, app.state.settings = db, jobs, hub, settings
    _routes(app, db, jobs, hub, settings)
    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


def _new_join_code() -> str:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(4))


# --------------------------------------------------------------------------- request bodies

class NewTeam(BaseModel):
    name: str = Field(min_length=2, max_length=24)
    emoji: str = Field(min_length=1, max_length=8)
    join_code: str


class Login(BaseModel):
    name: str
    pin: str


class NewGame(BaseModel):
    starter: str


class Ask(BaseModel):
    request: str = Field(min_length=3, max_length=300)


class Explain(BaseModel):
    snippet: str = Field(min_length=1, max_length=3000)


class TestResult(BaseModel):
    ok: bool
    error: str = ""


class Restore(BaseModel):
    version_id: int


class Publish(BaseModel):
    title: str = Field(min_length=2, max_length=40)
    description: str = Field(default="", max_length=200)
    published: bool = True


class Rate(BaseModel):
    stars: int = Field(ge=1, le=5)
    reaction: str = ""


class Vote(BaseModel):
    category: str


class LeaderLogin(BaseModel):
    pin: str


class LeaderSettings(BaseModel):
    ai_paused: bool | None = None
    voting_frozen: bool | None = None
    awards_revealed: bool | None = None
    event_name: str | None = None


class NewEvent(BaseModel):
    event_name: str = Field(min_length=2, max_length=80)


class Hide(BaseModel):
    hidden: bool


# --------------------------------------------------------------------------- routes

def _routes(app: FastAPI, db: DB, jobs: JobQueue, hub: Hub, settings: Settings) -> None:

    # ---- auth helpers ----
    def team_or_none(scout_team: str | None = Cookie(default=None)) -> dict | None:
        if not scout_team:
            return None
        return db.one("SELECT id, name, emoji FROM teams WHERE token=?", (scout_team,))

    def team(t: dict | None = Depends(team_or_none)) -> dict:
        if not t:
            raise HTTPException(401, "Please log in")
        return t

    def is_leader(scout_leader: str | None = Cookie(default=None)) -> bool:
        return bool(scout_leader) and secrets.compare_digest(scout_leader, db.get_setting("leader_token", "-"))

    def leader(ok: bool = Depends(is_leader)) -> bool:
        if not ok:
            raise HTTPException(401, "Leader login needed")
        return True

    def own_game(game_id: int, t: dict) -> dict:
        game = db.one("SELECT * FROM games WHERE id=?", (game_id,))
        if not game or game["team_id"] != t["id"]:
            raise HTTPException(404, "Game not found")
        return game

    def set_cookie(resp: Response, name: str, value: str) -> None:
        resp.set_cookie(name, value, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 7)

    def event_name() -> str:
        return db.get_setting("event_name", settings.event_name)

    # ---- pages ----
    def page(name: str) -> FileResponse:
        return FileResponse(WEB / name, headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    def home(t: dict | None = Depends(team_or_none)):
        return RedirectResponse("/studio" if t else "/login")

    @app.get("/login", include_in_schema=False)
    def login_page():
        return page("login.html")

    @app.get("/studio", include_in_schema=False)
    def studio_page(t: dict | None = Depends(team_or_none)):
        return page("studio.html") if t else RedirectResponse("/login")

    @app.get("/arcade", include_in_schema=False)
    def arcade_page():
        return page("arcade.html")

    @app.get("/leader", include_in_schema=False)
    def leader_page():
        return page("leader.html")

    @app.get("/awards", include_in_schema=False)
    def awards_page():
        return page("awards.html")

    # ---- general info ----
    @app.get("/api/info")
    def info(t: dict | None = Depends(team_or_none)):
        return {
            "event_name": event_name(),
            "team": t,
            "starters": STARTERS,
            "team_emojis": TEAM_EMOJIS,
            "reactions": REACTIONS,
            "award_categories": AWARD_CATEGORIES,
            "ai_paused": db.flag("ai_paused"),
            "voting_frozen": db.flag("voting_frozen"),
        }

    # ---- teams ----
    @app.post("/api/teams")
    def create_team(body: NewTeam, response: Response):
        if body.join_code.strip().upper() != db.get_setting("join_code"):
            raise HTTPException(400, "That join code isn't right. Check the big screen!")
        if body.emoji not in TEAM_EMOJIS:
            raise HTTPException(400, "Please pick one of the team emojis.")
        name = re.sub(r"\s+", " ", body.name).strip()
        if safety.is_blocked(name):
            raise HTTPException(400, "Please pick a different team name.")
        if db.one("SELECT id FROM teams WHERE name=?", (name,)):
            raise HTTPException(400, "That team name is taken. If it's yours, log in with your PIN.")
        pin = f"{secrets.randbelow(10000):04d}"
        token = secrets.token_urlsafe(24)
        team_id = db.execute("INSERT INTO teams(name, emoji, pin, token, created_at) VALUES(?,?,?,?,?)",
                             (name, body.emoji, pin, token, now()))
        set_cookie(response, "scout_team", token)
        return {"team": {"id": team_id, "name": name, "emoji": body.emoji}, "pin": pin}

    @app.post("/api/login")
    def login(body: Login, response: Response):
        t = db.one("SELECT * FROM teams WHERE name=?", (body.name.strip(),))
        if not t or not secrets.compare_digest(t["pin"], body.pin.strip()):
            raise HTTPException(400, "Team name or PIN not right. Ask a leader if you're stuck.")
        set_cookie(response, "scout_team", t["token"])
        return {"team": {"id": t["id"], "name": t["name"], "emoji": t["emoji"]}}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie("scout_team")
        return {"ok": True}

    @app.get("/api/teams/names")
    def team_names():
        return [r["name"] for r in db.all("SELECT name FROM teams ORDER BY name")]

    # ---- games ----
    @app.get("/api/me")
    def me(t: dict = Depends(team)):
        games = db.all("SELECT id, title, starter, published_version_id IS NOT NULL AS published, created_at "
                       "FROM games WHERE team_id=? ORDER BY id DESC", (t["id"],))
        return {"team": t, "games": games}

    @app.post("/api/games")
    def new_game(body: NewGame, t: dict = Depends(team)):
        if body.starter not in STARTER_IDS:
            raise HTTPException(400, "Unknown starter game")
        meta = next(s for s in STARTERS if s["id"] == body.starter)
        code = (STARTERS_DIR / f"{body.starter}.html").read_text(encoding="utf-8")
        game_id = db.execute("INSERT INTO games(team_id, starter, title, created_at) VALUES(?,?,?,?)",
                             (t["id"], body.starter, meta["title"], now()))
        vid = db.execute("INSERT INTO versions(game_id, code, request, plan, status, created_at) "
                         "VALUES(?,?,?,?, 'ok', ?)",
                         (game_id, code, "", f"Started from {meta['title']}", now()))
        db.execute("UPDATE games SET current_version_id=? WHERE id=?", (vid, game_id))
        return {"id": game_id}

    @app.get("/api/games/{game_id}")
    def get_game(game_id: int, t: dict = Depends(team)):
        game = own_game(game_id, t)
        current = db.one("SELECT id, code, plan, request FROM versions WHERE id=?", (game["current_version_id"],))
        versions = db.all("SELECT id, parent_id, request, plan, status, error, created_at FROM versions "
                          "WHERE game_id=? ORDER BY id", (game_id,))
        pending = db.one("SELECT id FROM versions WHERE game_id=? AND status='testing' ORDER BY id DESC LIMIT 1",
                         (game_id,))
        active = jobs.active_job(t["id"])
        starter = next((s for s in STARTERS if s["id"] == game["starter"]), None)
        return {
            "game": game,
            "current": current,
            "versions": versions,
            "pending_test_version_id": pending["id"] if pending else None,
            "active_job": active and {k: active[k] for k in ("id", "kind", "status", "request", "game_id")},
            "ideas": starter["ideas"] if starter else [],
        }

    @app.get("/api/versions/{version_id}")
    def get_version(version_id: int, t: dict = Depends(team)):
        v = db.one("SELECT v.*, g.team_id FROM versions v JOIN games g ON g.id=v.game_id WHERE v.id=?",
                   (version_id,))
        if not v or v["team_id"] != t["id"]:
            raise HTTPException(404, "Not found")
        return v

    @app.post("/api/games/{game_id}/ask")
    def ask(game_id: int, body: Ask, t: dict = Depends(team)):
        game = own_game(game_id, t)
        if safety.is_blocked(body.request):
            raise HTTPException(400, "Let's keep it friendly! Try a different idea.")
        if db.flag("ai_paused"):
            raise HTTPException(409, "The AI is having a break. Listen to your leader!")
        if jobs.active_job(t["id"]):
            raise HTTPException(409, "The AI is still working on your last idea.")
        job_id = jobs.submit(team_id=t["id"], game_id=game_id, kind="edit", request=body.request.strip(),
                             base_version_id=game["current_version_id"])
        return {"job_id": job_id}

    @app.post("/api/games/{game_id}/explain")
    def explain(game_id: int, body: Explain, t: dict = Depends(team)):
        game = own_game(game_id, t)
        if jobs.active_job(t["id"], kinds=("explain",)):
            raise HTTPException(409, "Still explaining the last bit!")
        job_id = jobs.submit(team_id=t["id"], game_id=game_id, kind="explain", request="explain",
                             snippet=body.snippet, base_version_id=game["current_version_id"])
        return {"job_id": job_id}

    @app.post("/api/versions/{version_id}/test")
    def test_result(version_id: int, body: TestResult, t: dict = Depends(team)):
        v = db.one("SELECT v.id, g.team_id FROM versions v JOIN games g ON g.id=v.game_id WHERE v.id=?",
                   (version_id,))
        if not v or v["team_id"] != t["id"]:
            raise HTTPException(404, "Not found")
        return jobs.report_test(version_id, body.ok, body.error)

    @app.post("/api/games/{game_id}/restore")
    def restore(game_id: int, body: Restore, t: dict = Depends(team)):
        own_game(game_id, t)
        v = db.one("SELECT id FROM versions WHERE id=? AND game_id=? AND status='ok'", (body.version_id, game_id))
        if not v:
            raise HTTPException(400, "You can only go back to a version that worked.")
        db.execute("UPDATE games SET current_version_id=? WHERE id=?", (v["id"], game_id))
        return {"ok": True}

    @app.post("/api/games/{game_id}/publish")
    def publish(game_id: int, body: Publish, t: dict = Depends(team)):
        game = own_game(game_id, t)
        if safety.is_blocked(body.title) or safety.is_blocked(body.description):
            raise HTTPException(400, "Let's keep it friendly! Try a different title.")
        if body.published:
            db.execute("UPDATE games SET title=?, description=?, published_version_id=?, "
                       "published_at=COALESCE(published_at, ?) WHERE id=?",
                       (body.title.strip(), body.description.strip(), game["current_version_id"], now(), game_id))
        else:
            db.execute("UPDATE games SET published_version_id=NULL WHERE id=?", (game_id,))
        return {"ok": True}

    # ---- live events ----
    @app.get("/api/events")
    async def events(request: Request, t: dict = Depends(team)):
        q = hub.subscribe(t["id"])

        async def stream():
            try:
                yield "retry: 2000\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=15)
                        if ev is None:  # the hub hung up (new event)
                            break
                        yield f"data: {json.dumps(ev)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                hub.unsubscribe(t["id"], q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- playing games ----
    @app.get("/play/{version_id}", include_in_schema=False)
    def play(version_id: int, t: dict | None = Depends(team_or_none), lead: bool = Depends(is_leader)):
        v = db.one("SELECT v.code, g.team_id, g.hidden, g.published_version_id FROM versions v "
                   "JOIN games g ON g.id=v.game_id WHERE v.id=?", (version_id,))
        if not v:
            raise HTTPException(404)
        mine = t is not None and t["id"] == v["team_id"]
        public = v["published_version_id"] == version_id and not v["hidden"]
        if not (mine or public or lead):
            raise HTTPException(404)
        return HTMLResponse(v["code"], headers={"Content-Security-Policy": PLAY_CSP, "Cache-Control": "no-store"})

    # ---- arcade ----
    def arcade_games(viewer_team: int | None, include_hidden: bool = False) -> list[dict]:
        rows = db.all(
            "SELECT g.id, g.title, g.description, g.published_version_id AS version_id, g.hidden, g.starter, "
            "g.published_at, t.id AS team_id, t.name AS team_name, t.emoji AS team_emoji, "
            "AVG(r.stars) AS avg_stars, COUNT(r.stars) AS ratings "
            "FROM games g JOIN teams t ON t.id=g.team_id LEFT JOIN ratings r ON r.game_id=g.id "
            "WHERE g.published_version_id IS NOT NULL " + ("" if include_hidden else "AND g.hidden=0 ") +
            "GROUP BY g.id ORDER BY g.published_at DESC"
        )
        reactions = db.all("SELECT game_id, reaction, COUNT(*) AS n FROM ratings WHERE reaction != '' "
                           "GROUP BY game_id, reaction")
        mine = {}
        if viewer_team:
            mine = {r["game_id"]: r for r in db.all("SELECT * FROM ratings WHERE team_id=?", (viewer_team,))}
        my_votes = {}
        if viewer_team:
            my_votes = {r["category"]: r["game_id"] for r in
                        db.all("SELECT category, game_id FROM votes WHERE team_id=?", (viewer_team,))}
        for g in rows:
            g["avg_stars"] = round(g["avg_stars"], 2) if g["avg_stars"] else None
            g["reactions"] = {r["reaction"]: r["n"] for r in reactions if r["game_id"] == g["id"]}
            g["my_rating"] = mine.get(g["id"], {}).get("stars")
            g["my_reaction"] = mine.get(g["id"], {}).get("reaction") or ""
            g["my_votes"] = [c for c, gid in my_votes.items() if gid == g["id"]]
            g["is_mine"] = viewer_team == g["team_id"]
        return rows

    @app.get("/api/arcade")
    def arcade(t: dict | None = Depends(team_or_none)):
        return {"games": arcade_games(t["id"] if t else None), "voting_frozen": db.flag("voting_frozen"),
                "team": t, "event_name": event_name()}

    def rateable(game_id: int, t: dict) -> dict:
        if db.flag("voting_frozen"):
            raise HTTPException(409, "Voting has closed!")
        game = db.one("SELECT * FROM games WHERE id=? AND published_version_id IS NOT NULL AND hidden=0",
                      (game_id,))
        if not game:
            raise HTTPException(404, "Game not found")
        if game["team_id"] == t["id"]:
            raise HTTPException(400, "No voting for your own game, nice try! 😄")
        return game

    @app.post("/api/arcade/{game_id}/rate")
    def rate(game_id: int, body: Rate, t: dict = Depends(team)):
        rateable(game_id, t)
        reaction = body.reaction if body.reaction in REACTIONS else ""
        db.execute("INSERT INTO ratings(game_id, team_id, stars, reaction, created_at) VALUES(?,?,?,?,?) "
                   "ON CONFLICT(game_id, team_id) DO UPDATE SET stars=excluded.stars, reaction=excluded.reaction",
                   (game_id, t["id"], body.stars, reaction, now()))
        return {"ok": True}

    @app.post("/api/arcade/{game_id}/vote")
    def vote(game_id: int, body: Vote, t: dict = Depends(team)):
        if body.category not in AWARD_CATEGORIES:
            raise HTTPException(400, "Unknown award")
        rateable(game_id, t)
        db.execute("INSERT INTO votes(category, team_id, game_id) VALUES(?,?,?) "
                   "ON CONFLICT(category, team_id) DO UPDATE SET game_id=excluded.game_id",
                   (body.category, t["id"], game_id))
        return {"ok": True}

    def compute_awards() -> list[dict]:
        games = {g["id"]: g for g in arcade_games(None)}
        awards = []
        rated = [g for g in games.values() if g["ratings"]]
        if rated:
            best = max(rated, key=lambda g: (g["avg_stars"], g["ratings"]))
            awards.append({"category": "stars", "label": "⭐ Top Rated", "game": best,
                           "detail": f"{best['avg_stars']} stars from {best['ratings']} team{'s' if best['ratings'] != 1 else ''}"})
        for cat, label in AWARD_CATEGORIES.items():
            counts = db.all("SELECT game_id, COUNT(*) AS n FROM votes WHERE category=? GROUP BY game_id "
                            "ORDER BY n DESC, game_id", (cat,))
            counts = [c for c in counts if c["game_id"] in games]
            if counts:
                top = counts[0]
                awards.append({"category": cat, "label": label, "game": games[top["game_id"]],
                               "detail": f"{top['n']} vote{'s' if top['n'] != 1 else ''}"})
        return awards

    @app.get("/api/awards")
    def awards(lead: bool = Depends(is_leader)):
        revealed = db.flag("awards_revealed")
        if not (revealed or lead):
            return {"revealed": False, "awards": [], "event_name": event_name()}
        leaderboard = sorted(
            (g for g in arcade_games(None) if g["ratings"]),
            key=lambda g: (-(g["avg_stars"] or 0), -g["ratings"]),
        )
        return {"revealed": revealed, "awards": compute_awards(), "leaderboard": leaderboard[:10],
                "event_name": event_name()}

    # ---- leader ----
    @app.post("/api/leader/login")
    def leader_login(body: LeaderLogin, response: Response):
        if not secrets.compare_digest(body.pin.strip(), settings.leader_pin):
            raise HTTPException(400, "Wrong leader PIN")
        token = secrets.token_urlsafe(24)
        db.set_setting("leader_token", token)
        set_cookie(response, "scout_leader", token)
        return {"ok": True}

    @app.get("/api/leader/status")
    def leader_status(_: bool = Depends(leader)):
        teams = db.all(
            "SELECT t.id, t.name, t.emoji, t.pin, t.last_worker, "
            "(SELECT COUNT(*) FROM games g WHERE g.team_id=t.id) AS games, "
            "(SELECT COUNT(*) FROM jobs j WHERE j.team_id=t.id AND j.kind='edit') AS requests, "
            "(SELECT COUNT(*) FROM jobs j WHERE j.team_id=t.id AND j.kind='edit' AND j.status='done') AS successes "
            "FROM teams t ORDER BY t.name"
        )
        recent = db.all(
            "SELECT j.id, j.kind, j.status, j.request, j.plan, j.message, j.worker, j.tokens, j.created_at, "
            "substr(j.reply, 1, 4000) AS reply, j.error_in, "
            "j.started_at, j.finished_at, t.name AS team_name, t.emoji AS team_emoji "
            "FROM jobs j JOIN teams t ON t.id=j.team_id ORDER BY j.id DESC LIMIT 30"
        )
        return {
            "event_name": event_name(),
            "join_code": db.get_setting("join_code"),
            "ai_paused": db.flag("ai_paused"),
            "voting_frozen": db.flag("voting_frozen"),
            "awards_revealed": db.flag("awards_revealed"),
            "mock": settings.mock,
            "average_job_seconds": round(jobs.average_seconds(), 1),
            "workers": [{"name": w.name, "healthy": w.healthy, "busy_job": w.busy_job,
                         "tokens_per_sec": w.tokens_per_sec, "jobs_done": w.jobs_done, "stats": w.stats,
                         "warm_done": w.warm_done, "warm_total": w.warm_total, "warm_left": len(w.warm_todo)}
                        for w in jobs.workers],
            "queue": jobs.queue_snapshot(),
            "recent_jobs": recent,
            "teams": teams,
            "games": arcade_games(None, include_hidden=True),
            "all_games": db.all("SELECT g.id, g.title, g.current_version_id, g.published_version_id, g.hidden, "
                                "t.name AS team_name, t.emoji AS team_emoji FROM games g "
                                "JOIN teams t ON t.id=g.team_id ORDER BY g.id DESC"),
        }

    @app.post("/api/leader/settings")
    def leader_settings(body: LeaderSettings, _: bool = Depends(leader)):
        for key in ("ai_paused", "voting_frozen", "awards_revealed"):
            val = getattr(body, key)
            if val is not None:
                db.set_setting(key, "1" if val else "0")
        if body.event_name:
            db.set_setting("event_name", body.event_name.strip()[:80])
        if body.ai_paused is False:
            jobs.notify()
        return {"ok": True}

    @app.post("/api/leader/new-event")
    def new_event(body: NewEvent, _: bool = Depends(leader)):
        """Archive this group's event, then wipe teams, games and votes for the next group."""
        stopped = jobs.cancel_all()
        summary = archive_event(db, settings.data_dir, event_name())
        reset_event(db, body.event_name.strip(), _new_join_code())
        hub.disconnect_all()
        log.info("New event %r started; previous event archived as %s (%d jobs stopped)",
                 body.event_name, summary["name"], stopped)
        return {"archive": summary, "join_code": db.get_setting("join_code")}

    @app.get("/api/leader/archives")
    def archives(_: bool = Depends(leader)):
        return list_archives(settings.data_dir)

    @app.get("/api/leader/archives/{name}/{filename}")
    def archive_download(name: str, filename: str, _: bool = Depends(leader)):
        path = archive_file(settings.data_dir, name, filename)
        if not path:
            raise HTTPException(404, "Not found")
        return FileResponse(path, filename=f"{name}-{filename}")

    @app.post("/api/leader/shutdown")
    async def shutdown_pis(_: bool = Depends(leader)):
        """Power off every Pi cleanly: the other Pis first, then this one (which runs this website)."""
        targets = [w for w in jobs.workers if w.stats_url]
        if not targets:
            raise HTTPException(409, "There are no Pis to shut down (this is the development mode).")

        def is_this_pi(w: Worker) -> bool:
            return urlparse(w.stats_url).hostname in ("127.0.0.1", "localhost", "::1")

        db.set_setting("ai_paused", "1")  # don't start anything new on the way down
        results = []
        async with httpx.AsyncClient(timeout=5) as client:
            for w in sorted(targets, key=is_this_pi):
                # This Pi waits a little longer, so this page gets its answer first.
                delay = 5 if is_this_pi(w) else 1
                try:
                    r = await client.post(w.stats_url.rstrip("/") + "/shutdown", json={"delay": delay},
                                          headers={"Authorization": f"Bearer {w.api_key or ''}"})
                    ok = r.status_code == 202
                    error = "" if ok else r.json().get("error", f"error {r.status_code}")
                except (httpx.HTTPError, ValueError) as e:
                    ok, error = False, f"couldn't reach it ({e.__class__.__name__})"
                results.append({"name": w.name, "ok": ok, "error": error})
        log.info("Shutdown requested: %s", results)
        return {"results": results}

    @app.post("/api/leader/warmup")
    def warmup(_: bool = Depends(leader)):
        jobs.start_warmup()
        return {"ok": True}

    @app.post("/api/leader/join-code")
    def new_join_code(_: bool = Depends(leader)):
        code = _new_join_code()
        db.set_setting("join_code", code)
        return {"join_code": code}

    @app.post("/api/leader/games/{game_id}/hide")
    def hide_game(game_id: int, body: Hide, _: bool = Depends(leader)):
        db.execute("UPDATE games SET hidden=? WHERE id=?", (1 if body.hidden else 0, game_id))
        return {"ok": True}

    @app.post("/api/leader/teams/{team_id}/reset-pin")
    def reset_pin(team_id: int, _: bool = Depends(leader)):
        pin = f"{secrets.randbelow(10000):04d}"
        db.execute("UPDATE teams SET pin=?, token=? WHERE id=?", (pin, secrets.token_urlsafe(24), team_id))
        return {"pin": pin}

    @app.post("/api/leader/jobs/{job_id}/cancel")
    def cancel_job(job_id: int, _: bool = Depends(leader)):
        return {"ok": jobs.cancel(job_id)}

    @app.get("/api/leader/export.zip")
    def export(_: bool = Depends(leader)):
        return Response(build_export(db, event_name()), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="scout-code-games.zip"'})
