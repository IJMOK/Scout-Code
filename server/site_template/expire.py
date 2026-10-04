"""Remove sessions whose time is up. Runs daily on GitHub Actions (see .github/workflows/expire.yml).

Made by Scout Code. Standard library only, so it needs nothing installed.
"""

import json
import re
import shutil
import time
from pathlib import Path

SLUG = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-f0-9]{8}$")

root = Path(__file__).resolve().parent.parent
index = root / "sessions.json"
sessions = json.loads(index.read_text(encoding="utf-8")) if index.exists() else []
now = time.time()
keep = []
for session in sessions:
    slug = session.get("slug", "")
    if session.get("expires", 0) > now:
        keep.append(session)
    elif SLUG.match(slug):
        shutil.rmtree(root / "s" / slug, ignore_errors=True)
        print(f"Removed expired session {slug}")
index.write_text(json.dumps(keep, indent=2), encoding="utf-8")
print(f"{len(keep)} session(s) still online")
