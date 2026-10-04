"""Saving one group's event and starting fresh for the next group.

Each archive is a folder in data/archive/ holding:
    scout.db      a complete copy of the database (teams, games, every version, ratings)
    games.zip     every team's latest game as stand-alone HTML files
    summary.json  name, date and counts, shown on the leader dashboard

To bring an old event back: stop the portal, copy its scout.db over
data/scout.db (and delete data/scout.db-wal and -shm), then start the portal.
"""

from __future__ import annotations

import io
import json
import re
import secrets
import sqlite3
import time
import zipfile
from pathlib import Path

from .db import DB

ARCHIVE_NAME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}(?:-[a-z0-9-]+)?$")

# Tables cleared for a new event, children first.
EVENT_TABLES = ("votes", "ratings", "jobs", "versions", "games", "teams")
# Settings that belong to the leader or the Pis, not to one event.
KEEP_SETTINGS = ("leader_tokens",)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "game"


def build_export(db: DB, event_name: str) -> bytes:
    """Every team's latest working game as stand-alone HTML files, plus an index page."""
    games = db.all(
        "SELECT g.id, g.title, g.description, g.published_version_id, t.name AS team_name, t.emoji AS team_emoji, "
        "v.code FROM games g JOIN teams t ON t.id=g.team_id JOIN versions v ON v.id=g.current_version_id "
        "WHERE g.hidden=0 AND t.demo=0 ORDER BY t.name, g.id"
    )
    buf = io.BytesIO()
    links = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for g in games:
            path = f"{_slug(g['team_name'])}/{g['id']}-{_slug(g['title'])}.html"
            z.writestr(path, g["code"])
            star = " ⭐ published" if g["published_version_id"] else ""
            links.append(f'<li>{_esc(g["team_emoji"])} <b>{_esc(g["team_name"])}</b>: '
                         f'<a href="{path}">{_esc(g["title"])}</a>{star}</li>')
        z.writestr("index.html", f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{_esc(event_name)}</title>
<style>body{{font-family:sans-serif;max-width:700px;margin:2em auto;padding:0 1em;line-height:1.6}}</style>
</head><body><h1>🎮 {_esc(event_name)}</h1>
<p>Every game made at the event. They work offline: just open one in a web browser.</p>
<ul>{''.join(links)}</ul></body></html>""")
    return buf.getvalue()


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def archive_dir(data_dir: Path) -> Path:
    return data_dir / "archive"


def current_event_id(db: DB) -> str:
    """A random id for the event in progress; "Start a new event" gives the next one a new id."""
    event_id = db.get_setting("event_id")
    if not event_id:
        event_id = secrets.token_hex(8)
        db.set_setting("event_id", event_id)
    return event_id


def find_archive(data_dir: Path, event_id: str) -> Path | None:
    for summary in list_archives(data_dir):
        if summary.get("event_id") == event_id:
            return archive_dir(data_dir) / summary["name"]
    return None


def archive_event(db: DB, data_dir: Path, event_name: str) -> dict:
    """Snapshot the current event into data/archive/<date>-<name>/ and return its summary.

    Saving the same event again (e.g. "Put tonight's games online", then later
    "Start a new event") refreshes its existing snapshot instead of making a second one.
    """
    event_id = current_event_id(db)
    folder = find_archive(data_dir, event_id)
    if folder is None:
        stamp = time.strftime("%Y-%m-%d-%H%M")
        name = f"{stamp}-{_slug(event_name)}"[:80].rstrip("-")
        folder = archive_dir(data_dir) / name
        n = 2
        while folder.exists():
            folder = archive_dir(data_dir) / f"{name}-{n}"
            n += 1
        folder.mkdir(parents=True)
    for old in ("scout.db", "scout.db-wal", "scout.db-shm"):
        (folder / old).unlink(missing_ok=True)

    # SQLite's backup API copies a consistent snapshot even while the portal is running.
    with db.lock:
        dest = sqlite3.connect(str(folder / "scout.db"))
        try:
            db.conn.backup(dest)
        finally:
            dest.close()
    (folder / "games.zip").write_bytes(build_export(db, event_name))

    summary = {
        "name": folder.name,
        "event_id": event_id,
        "event_name": event_name,
        "archived_at": time.time(),
        "teams": db.value("SELECT COUNT(*) FROM teams WHERE demo=0"),
        "games": db.value("SELECT COUNT(*) FROM games g JOIN teams t ON t.id=g.team_id WHERE t.demo=0"),
        "published": db.value("SELECT COUNT(*) FROM games g JOIN teams t ON t.id=g.team_id "
                              "WHERE t.demo=0 AND g.published_version_id IS NOT NULL"),
        "ai_requests": db.value("SELECT COUNT(*) FROM jobs WHERE kind='edit'"),
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def reset_event(db: DB, event_name: str, join_code: str) -> None:
    """Remove every team, game, rating and vote, ready for a new group."""
    keep = ",".join("?" * len(KEEP_SETTINGS))
    with db.lock:
        db.conn.execute("BEGIN")
        try:
            for table in EVENT_TABLES:
                db.conn.execute(f"DELETE FROM {table}")
            db.conn.execute(f"DELETE FROM settings WHERE key NOT IN ({keep})", KEEP_SETTINGS)
            db.conn.execute("INSERT INTO settings(key, value) VALUES('event_name', ?)", (event_name,))
            db.conn.execute("INSERT INTO settings(key, value) VALUES('join_code', ?)", (join_code,))
            db.conn.execute("COMMIT")
        except Exception:
            db.conn.execute("ROLLBACK")
            raise


def list_archives(data_dir: Path) -> list[dict]:
    out = []
    root = archive_dir(data_dir)
    if root.exists():
        for folder in root.iterdir():
            summary_file = folder / "summary.json"
            if folder.is_dir() and summary_file.exists():
                try:
                    out.append(json.loads(summary_file.read_text()))
                except (OSError, json.JSONDecodeError):
                    continue
    return sorted(out, key=lambda a: a.get("archived_at", 0), reverse=True)


def archive_file(data_dir: Path, name: str, filename: str) -> Path | None:
    """A file inside one archive, or None. Guards against ../ tricks."""
    if not ARCHIVE_NAME_RE.match(name) or filename not in ("games.zip", "scout.db"):
        return None
    path = archive_dir(data_dir) / name / filename
    return path if path.is_file() else None
