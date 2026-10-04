"""The arcade list, awards and leaderboard, shared by the live site and the online games site.

Games by the leaders' demo team are shown in the arcade (so the demo works) but
never win awards or appear on the leaderboard, in exports or online.
"""

from __future__ import annotations

from .db import DB

AWARD_CATEGORIES = {
    "fun": "🎉 Most Fun",
    "looks": "🎨 Best Looking",
    "creative": "💡 Most Creative",
}


def published_games(db: DB, viewer_team: int | None = None, include_hidden: bool = False,
                    include_demo: bool = True) -> list[dict]:
    rows = db.all(
        "SELECT g.id, g.title, g.description, g.published_version_id AS version_id, g.hidden, g.starter, "
        "g.published_at, t.id AS team_id, t.name AS team_name, t.emoji AS team_emoji, t.demo AS demo, "
        "AVG(r.stars) AS avg_stars, COUNT(r.stars) AS ratings "
        "FROM games g JOIN teams t ON t.id=g.team_id LEFT JOIN ratings r ON r.game_id=g.id "
        "WHERE g.published_version_id IS NOT NULL " + ("" if include_hidden else "AND g.hidden=0 ") +
        ("" if include_demo else "AND t.demo=0 ") +
        "GROUP BY g.id ORDER BY g.published_at DESC"
    )
    reactions = db.all("SELECT game_id, reaction, COUNT(*) AS n FROM ratings WHERE reaction != '' "
                       "GROUP BY game_id, reaction")
    mine, my_votes = {}, {}
    if viewer_team:
        mine = {r["game_id"]: r for r in db.all("SELECT * FROM ratings WHERE team_id=?", (viewer_team,))}
        my_votes = {r["category"]: r["game_id"] for r in
                    db.all("SELECT category, game_id FROM votes WHERE team_id=?", (viewer_team,))}
    for g in rows:
        g["avg_stars"] = round(g["avg_stars"], 2) if g["avg_stars"] else None
        g["reactions"] = {r["reaction"]: r["n"] for r in reactions if r["game_id"] == g["id"]}
        g["my_rating"] = mine.get(g["id"], {}).get("stars")
        g["my_reaction"] = mine.get(g["id"], {}).get("reaction") or ""
        g["my_votes"] = [c for c, gid in my_votes.items() if gid == g["id"]]
        g["is_mine"] = viewer_team == g["team_id"]
        g["demo"] = bool(g["demo"])
    return rows


def compute_awards(db: DB) -> list[dict]:
    games = {g["id"]: g for g in published_games(db, include_demo=False)}
    awards = []
    rated = [g for g in games.values() if g["ratings"]]
    if rated:
        best = max(rated, key=lambda g: (g["avg_stars"], g["ratings"]))
        teams = f"team{'s' if best['ratings'] != 1 else ''}"
        awards.append({"category": "stars", "label": "⭐ Top Rated", "game": best,
                       "detail": f"{best['avg_stars']} stars from {best['ratings']} {teams}"})
    for cat, label in AWARD_CATEGORIES.items():
        counts = db.all("SELECT game_id, COUNT(*) AS n FROM votes WHERE category=? GROUP BY game_id "
                        "ORDER BY n DESC, game_id", (cat,))
        counts = [c for c in counts if c["game_id"] in games]
        if counts:
            top = counts[0]
            awards.append({"category": cat, "label": label, "game": games[top["game_id"]],
                           "detail": f"{top['n']} vote{'s' if top['n'] != 1 else ''}"})
    return awards


def leaderboard(db: DB, limit: int = 10) -> list[dict]:
    rated = [g for g in published_games(db, include_demo=False) if g["ratings"]]
    return sorted(rated, key=lambda g: (-(g["avg_stars"] or 0), -g["ratings"]))[:limit]
