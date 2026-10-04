"""Putting the scouts' games online (GitHub Pages) for parents to play at home.

Each group publishes to its *own* GitHub repository with its own limited
token, entered on the leader dashboard and stored only on this Pi.

Every sync rebuilds the whole site from the saved events and force-pushes a
single fresh commit, so sessions that are taken offline or have expired leave
no trace in the repository. A small daily GitHub Action (tools/expire.py in the
published site) removes expired sessions even when the Pi is switched off.

Site layout:
    index.html  sessions.json  robots.txt  .nojekyll
    s/<date>-<random>/index.html            a session's arcade
    s/<date>-<random>/games/<id>.html       its games
    tools/expire.py  .github/workflows/expire.yml
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from .archive import archive_dir, list_archives
from .awards import compute_awards, published_games
from .db import DB

log = logging.getLogger("scout.publish")

TEMPLATES = Path(__file__).resolve().parent / "site_template"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SLUG_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-f0-9]{8}$")
DAY = 24 * 3600

# Same rules as on the Pi: the game can run its own code but can't reach the internet.
GAME_HEAD = ('<meta name="robots" content="noindex, nofollow">'
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
             'script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data: blob:; '
             'media-src data: blob:; font-src data:">')


# --------------------------------------------------------------------------- settings

@dataclass
class PublishSettings:
    repo: str = ""                 # "owner/name"
    token: str = ""                # fine-grained token for that repo only; never sent to the browser
    site_title: str = "Our Scout Code games"
    expiry_days: int = 30
    hide_team_names: bool = False
    checklist_done: bool = False   # leader confirmed consent / no real names / games reviewed
    auto_expire: bool = True       # include the daily GitHub clean-up job
    site_url: str = ""             # learnt from GitHub after the first sync
    api_url: str = "https://api.github.com"
    git_url: str = ""              # override for tests (e.g. a local bare repo)

    def public(self) -> dict:
        """What the dashboard may see: everything except the token."""
        data = asdict(self)
        data.pop("token")
        data.pop("git_url")
        data.pop("api_url")
        data["token_hint"] = ("••••" + self.token[-4:]) if self.token else ""
        data["configured"] = bool(self.repo and self.token)
        return data

    def remote(self) -> str:
        return self.git_url or f"https://github.com/{self.repo}.git"

    def default_site_url(self) -> str:
        owner, name = self.repo.split("/", 1)
        if name.lower() == f"{owner.lower()}.github.io":
            return f"https://{owner.lower()}.github.io/"
        return f"https://{owner.lower()}.github.io/{name}/"


def settings_file(data_dir: Path) -> Path:
    return data_dir / "publish.json"


def load_settings(data_dir: Path) -> PublishSettings:
    path = settings_file(data_dir)
    s = PublishSettings()
    if path.exists():
        try:
            raw = json.loads(path.read_text())
            for key, value in raw.items():
                if hasattr(s, key):
                    setattr(s, key, value)
        except (OSError, json.JSONDecodeError):
            log.warning("publish.json is unreadable; using defaults")
    return s


def save_settings(data_dir: Path, s: PublishSettings) -> None:
    path = settings_file(data_dir)
    path.write_text(json.dumps(asdict(s), indent=2))
    os.chmod(path, 0o600)  # the token lives here


# --------------------------------------------------------------------------- per-session state

def session_state(data_dir: Path, name: str) -> dict:
    """Whether a saved event is online, its secret link and when it expires."""
    path = archive_dir(data_dir) / name / "publish.json"
    state = {"online": False, "slug": "", "expires": 0, "excluded": []}
    if path.exists():
        try:
            state.update(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    if not SLUG_RE.match(state["slug"]):
        state["slug"] = f"{name[:10]}-{secrets.token_hex(4)}"
        save_session_state(data_dir, name, state)
    return state


def save_session_state(data_dir: Path, name: str, state: dict) -> None:
    (archive_dir(data_dir) / name / "publish.json").write_text(json.dumps(state, indent=2))


def session_url(s: PublishSettings, state: dict) -> str:
    base = s.site_url or (s.default_site_url() if s.repo else "")
    return f"{base}s/{state['slug']}/" if base else ""


def sessions_overview(data_dir: Path, s: PublishSettings, now: float | None = None) -> list[dict]:
    now = now or time.time()
    out = []
    for summary in list_archives(data_dir):
        state = session_state(data_dir, summary["name"])
        live = state["online"] and state["expires"] > now
        out.append({**summary, **state, "live": live, "expired": state["online"] and not live,
                    "url": session_url(s, state)})
    return out


# --------------------------------------------------------------------------- building the site

def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _json_for_html(data) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _game_file(code: str) -> str:
    """The game, plus the network block, "don't index", and phone/tablet buttons."""
    head = GAME_HEAD + "<script>" + _template("touch.js") + "</script>"
    m = re.search(r"<head[^>]*>", code, re.IGNORECASE)
    return code[:m.end()] + head + code[m.end():] if m else head + code


def build_session(folder: Path, out: Path, title: str, state: dict, hide_team_names: bool) -> int:
    """Write one session's arcade into `out`. Returns how many games it has."""
    db = DB(folder / "scout.db")
    try:
        games = [g for g in published_games(db, include_demo=False) if g["id"] not in state.get("excluded", [])]
        awards = [a for a in compute_awards(db) if a["game"]["id"] in {g["id"] for g in games}]
        team_numbers: dict[int, int] = {}
        (out / "games").mkdir(parents=True, exist_ok=True)
        items = []
        for g in sorted(games, key=lambda g: (g["team_name"].lower(), g["id"])):
            team = g["team_name"]
            if hide_team_names:
                team = f"Team {team_numbers.setdefault(g['team_id'], len(team_numbers) + 1)}"
            code = db.value("SELECT code FROM versions WHERE id=?", (g["version_id"],)) or ""
            (out / "games" / f"{g['id']}.html").write_text(_game_file(code), encoding="utf-8")
            items.append({"id": g["id"], "title": g["title"], "description": g["description"],
                          "team": team, "emoji": g["team_emoji"], "stars": g["avg_stars"]})
        data = {
            "title": title,
            "date": json.loads((folder / "summary.json").read_text()).get("archived_at", time.time()),
            "expires": state["expires"],
            "games": items,
            "awards": [{"label": a["label"], "detail": a["detail"], "game_id": a["game"]["id"]} for a in awards],
        }
        page = (_template("session.html").replace("{{CSS}}", _template("site.css"))
                .replace("{{TITLE}}", _esc(title)).replace("{{DATA_JSON}}", _json_for_html(data)))
        (out / "index.html").write_text(page, encoding="utf-8")
        return len(items)
    finally:
        db.close()


def build_site(data_dir: Path, out: Path, s: PublishSettings, now: float | None = None) -> list[dict]:
    """Build the whole site into `out` (emptied first). Returns the sessions included."""
    now = now or time.time()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    sessions = []
    for summary in list_archives(data_dir):
        state = session_state(data_dir, summary["name"])
        if not (state["online"] and state["expires"] > now):
            continue
        folder = archive_dir(data_dir) / summary["name"]
        title = summary.get("event_name") or "Scout Code session"
        n = build_session(folder, out / "s" / state["slug"], title, state, s.hide_team_names)
        sessions.append({"slug": state["slug"], "title": title, "games": n, "expires": state["expires"],
                         "date": time.strftime("%Y-%m-%d", time.localtime(summary.get("archived_at", now)))})

    (out / "sessions.json").write_text(json.dumps(sessions, indent=2, ensure_ascii=False), encoding="utf-8")
    home = (_template("home.html").replace("{{CSS}}", _template("site.css"))
            .replace("{{SITE_TITLE}}", _esc(s.site_title or "Our Scout Code games")))
    (out / "index.html").write_text(home, encoding="utf-8")
    (out / "404.html").write_text(home, encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (out / ".nojekyll").write_text("")
    if s.auto_expire:
        (out / "tools").mkdir()
        shutil.copy(TEMPLATES / "expire.py", out / "tools" / "expire.py")
        (out / ".github" / "workflows").mkdir(parents=True)
        shutil.copy(TEMPLATES / "expire.yml", out / ".github" / "workflows" / "expire.yml")
    return sessions


def site_zip(data_dir: Path, s: PublishSettings) -> bytes:
    """The same site as a zip, for any other web host."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "site"
        build_site(data_dir, out, s)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(out.rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(out).as_posix())
        return buf.getvalue()


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# --------------------------------------------------------------------------- GitHub

class PublishError(Exception):
    pass


def _api(s: PublishSettings, method: str, path: str, **kwargs) -> httpx.Response:
    headers = {"Authorization": f"Bearer {s.token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    try:
        return httpx.request(method, s.api_url.rstrip("/") + path, headers=headers, timeout=20, **kwargs)
    except httpx.HTTPError as e:
        raise PublishError("Can't reach GitHub. Is this Pi connected to the internet?") from e


def test_connection(s: PublishSettings) -> str:
    """Check the repo and token. Returns a friendly success message or raises PublishError."""
    if not REPO_RE.match(s.repo or ""):
        raise PublishError("The repository should look like owner/name, e.g. 1st-anytown-scouts/scout-games.")
    if not s.token:
        raise PublishError("Paste the access token first.")
    r = _api(s, "GET", f"/repos/{s.repo}")
    if r.status_code == 401:
        raise PublishError("GitHub didn't accept the token. Check it was copied fully and hasn't expired.")
    if r.status_code == 404:
        raise PublishError(f"Can't find {s.repo}. Check the name, and that the token was given access to it.")
    if r.status_code >= 400:
        raise PublishError(f"GitHub said {r.status_code}: {r.text[:150]}")
    perms = r.json().get("permissions") or {}
    if perms and not (perms.get("push") or perms.get("admin")):
        raise PublishError("The token can see the repository but can't change it. Give it Contents: Read and write.")
    return f"Connected to {s.repo}."


def enable_pages(s: PublishSettings) -> str:
    """Make sure GitHub Pages serves the main branch. Returns the site's address."""
    r = _api(s, "GET", f"/repos/{s.repo}/pages")
    if r.status_code == 404:
        r = _api(s, "POST", f"/repos/{s.repo}/pages", json={"source": {"branch": "main", "path": "/"}})
    if r.status_code in (200, 201):
        return r.json().get("html_url") or s.default_site_url()
    raise PublishError(
        f"The games were uploaded, but GitHub Pages isn't switched on (GitHub said {r.status_code}). "
        f"On github.com open {s.repo} → Settings → Pages, choose 'Deploy from a branch', branch 'main', "
        f"folder '/ (root)', and Save. Or give the token Pages: Read and write.")


def _git(args: list[str], cwd: Path, token: str = "") -> None:
    cmd = ["git", "-c", "user.name=Scout Code", "-c", "user.email=scout-code@users.noreply.github.com"]
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        cmd += ["-c", f"http.extraHeader=Authorization: Basic {basic}"]
    out = subprocess.run(cmd + args, cwd=cwd, capture_output=True, text=True, timeout=300,
                         env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if out.returncode != 0:
        message = (out.stderr or out.stdout).replace(token, "••••") if token else (out.stderr or out.stdout)
        if ("workflow" in message and "scope" in message) or "refusing to allow" in message:
            raise PublishError("GitHub refused the daily clean-up job: give the token Workflows: Read and write "
                               "(or turn off automatic clean-up).")
        if "403" in message or "Authentication failed" in message or "denied" in message.lower():
            raise PublishError("GitHub refused the upload. Give the token Contents: Read and write for this repo.")
        raise PublishError("Uploading failed: " + message.strip().splitlines()[-1][:200] if message.strip()
                           else "Uploading failed.")


def push_site(data_dir: Path, s: PublishSettings) -> list[dict]:
    """Build the site and replace the repository's main branch with it (one fresh commit, no history)."""
    work = data_dir / "site-repo"
    if work.exists():
        shutil.rmtree(work)
    sessions = build_site(data_dir, work, s)
    _git(["init", "-q", "-b", "main"], work)
    _git(["add", "-A"], work)
    _git(["commit", "-q", "-m", f"Scout Code games: {len(sessions)} session(s)"], work)
    _git(["push", "-q", "--force", s.remote(), "HEAD:main"], work, s.token)
    shutil.rmtree(work / ".git", ignore_errors=True)
    return sessions


# --------------------------------------------------------------------------- background sync for the dashboard

class Publisher:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.lock = threading.Lock()
        self.status = {"state": "idle", "message": "", "at": None}

    def settings(self) -> PublishSettings:
        return load_settings(self.data_dir)

    def sync(self, wait: bool = False) -> None:
        if self.status["state"] == "syncing":
            return
        self.status = {"state": "syncing", "message": "Uploading the games…", "at": time.time()}
        thread = threading.Thread(target=self._sync, daemon=True)
        thread.start()
        if wait:
            thread.join()

    def _sync(self) -> None:
        with self.lock:
            s = self.settings()
            try:
                if not (s.repo and s.token):
                    raise PublishError("Set up the repository and token first.")
                if not s.checklist_done:
                    raise PublishError("Tick the safeguarding checklist first.")
                sessions = push_site(self.data_dir, s)
                if not s.git_url:  # real GitHub: make sure Pages is on and learn the address
                    s.site_url = enable_pages(s)
                    save_settings(self.data_dir, s)
                n = len(sessions)
                self.status = {"state": "ok", "at": time.time(),
                               "message": f"Online: {n} session{'s' if n != 1 else ''}. "
                                          "It can take a minute or two for GitHub to show the changes."}
            except PublishError as e:
                self.status = {"state": "error", "message": str(e), "at": time.time()}
            except Exception as e:  # never let a sync crash the website
                log.exception("sync failed")
                self.status = {"state": "error", "message": f"Something went wrong: {e}", "at": time.time()}
