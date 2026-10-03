"""End-to-end tests in a real (headless) browser, using the mock AI.

Skipped automatically when Playwright isn't installed. On a dev machine:
    pip install playwright && python -m playwright install chromium
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
STARTERS = sorted(p.stem for p in (ROOT / "server" / "starters").glob("*.html"))
CHROMIUM = os.environ.get("SCOUT_CHROMIUM") or next(
    (str(p) for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")), None)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    port = free_port()
    env = {**os.environ, "SCOUT_MOCK": "1", "SCOUT_MOCK_DELAY": "0.003", "SCOUT_DATA_DIR": str(data),
           "SCOUT_LEADER_PIN": "999999"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:create_app", "--factory", "--port", str(port),
         "--timeout-graceful-shutdown", "1"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM) if CHROMIUM else p.chromium.launch()
        yield b
        b.close()


@pytest.mark.parametrize("starter", STARTERS)
def test_starter_runs_without_errors(browser, starter):
    """Load each starter, start it, mash the keys for a few seconds: no JS errors allowed."""
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto((ROOT / "server" / "starters" / f"{starter}.html").as_uri())
    page.wait_for_timeout(300)
    page.keyboard.press("Space")
    for key in ["ArrowRight", "ArrowUp", "ArrowLeft", "Space", "ArrowDown", "ArrowRight"] * 3:
        page.keyboard.down(key)
        page.wait_for_timeout(120)
        page.keyboard.up(key)
    page.wait_for_timeout(1500)
    # Something was drawn on the canvas
    lit = page.evaluate("""() => {
        const c = document.querySelector('canvas');
        const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        const seen = new Set();
        for (let i = 0; i < d.length; i += 4 * 97) seen.add(d[i] + ',' + d[i+1] + ',' + d[i+2]);
        return seen.size;
    }""")
    page.close()
    assert not errors, errors
    assert lit > 2


def test_full_event_flow(browser, server, tmp_path):
    shots = Path(os.environ.get("SCOUT_SCREENSHOTS", tmp_path))
    ctx_leader = browser.new_context(viewport={"width": 1366, "height": 768})
    leader = ctx_leader.new_page()
    leader.goto(server + "/leader")
    leader.fill("#pin", "999999")
    leader.click("#login button")
    leader.wait_for_selector("#dash:not(.hidden)")
    join = leader.inner_text("#join-code").strip()

    # --- Team 1 builds a game ---
    ctx1 = browser.new_context(viewport={"width": 1366, "height": 768})
    p1 = ctx1.new_page()
    errors = []
    p1.on("pageerror", lambda e: errors.append(str(e)))
    p1.goto(server + "/")
    p1.fill("#team-name", "Pixel Wolves")
    p1.click("#emoji-pick button:nth-child(2)")
    p1.fill("#join-code", join)
    p1.click("#new-form button[type=submit]")
    p1.wait_for_selector("#pin-card:not(.hidden)")
    assert len(p1.inner_text("#pin-show").strip()) == 4
    p1.screenshot(path=str(shots / "1-pin.png"))
    p1.click("#pin-card a")
    p1.wait_for_selector("[data-starter=space-shooter]")
    p1.screenshot(path=str(shots / "2-picker.png"))
    p1.click("[data-starter=space-shooter]")
    p1.wait_for_selector("#code .ln")

    p1.fill("#ask-input", "make the player a 🐉")
    p1.click("#ask-btn")
    p1.wait_for_selector("text=Done!", timeout=20000)
    p1.wait_for_timeout(300)
    p1.screenshot(path=str(shots / "3-studio-done.png"))
    assert p1.locator(".ln.added").count() >= 1
    assert "🐉" in p1.inner_text(".ln.added")

    # The auto-fix loop, end to end in the browser
    p1.fill("#ask-input", "BREAK the game")
    p1.click("#ask-btn")
    p1.wait_for_selector("#agent-msg:has-text('Oops, I broke it')", timeout=30000)
    p1.screenshot(path=str(shots / "4-fixed.png"))
    assert "Fixing a bug" in p1.inner_text("#steps")  # the agent noticed its bug and fixed it
    assert "mockExplodes" not in p1.inner_text("#code")

    # Highlight some code with the "mouse" and ask the AI to explain it
    p1.evaluate("""() => {
        const lines = document.querySelectorAll('#code .ln .src');
        const range = document.createRange();
        range.setStart(lines[20], 0);
        range.setEndAfter(lines[24]);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
    }""")
    p1.click("#btn-explain")
    p1.wait_for_selector("#explain-text:has-text('recipe')", timeout=10000)
    p1.screenshot(path=str(shots / "5-explain.png"))

    # History shows the broken version and lets us go back
    p1.click("#btn-history")
    p1.wait_for_selector("#history-modal:not(.hidden)")
    assert p1.locator("#history-list li").count() == 4
    assert p1.locator("#history-list li:has-text('🐛')").count() == 1
    p1.click("#history-modal [data-close]")

    # Publish
    p1.click("#btn-publish")
    p1.fill("#pub-title", "Dragon Blaster")
    p1.fill("#pub-desc", "Arrows + space")
    p1.click("#publish-form button[type=submit]")
    p1.wait_for_selector("text=Your game is in the Arcade")
    # The only error allowed is the deliberate crash inside the test-play window.
    assert [e for e in errors if "mockExplodes" not in e] == [], errors

    # --- Team 2 rates it ---
    ctx2 = browser.new_context(viewport={"width": 1366, "height": 768})
    p2 = ctx2.new_page()
    p2.goto(server + "/login")
    p2.fill("#team-name", "Owl Squad")
    p2.fill("#join-code", join)
    p2.click("#new-form button[type=submit]")
    p2.wait_for_selector("#pin-card:not(.hidden)")
    p2.goto(server + "/arcade")
    p2.click("text=Dragon Blaster")
    p2.wait_for_selector("#player iframe")
    p2.wait_for_timeout(500)
    p2.click("[data-stars='5']")
    p2.wait_for_selector(".star-btn.on >> nth=4")
    p2.click("[data-react='🔥']")
    p2.wait_for_selector(".react-btn.on")
    p2.click("[data-vote='fun']")
    p2.wait_for_selector(".vote-btn.on")
    p2.screenshot(path=str(shots / "6-arcade-play.png"))

    # --- Leader reveals awards ---
    leader.reload()
    leader.wait_for_selector("#dash:not(.hidden)")
    leader.wait_for_timeout(500)
    leader.screenshot(path=str(shots / "7-leader.png"), full_page=True)
    leader.click("#t-vote")
    leader.click("#t-awards")
    awards = ctx_leader.new_page()
    awards.goto(server + "/awards")
    awards.wait_for_selector(".award")
    for card in awards.locator(".award").all():
        card.click()
    awards.wait_for_selector("#board:not(.hidden)")
    awards.screenshot(path=str(shots / "8-awards.png"))
    assert "Dragon Blaster" in awards.inner_text("#awards")

    # Export zip
    resp = leader.request.get(server + "/api/leader/export.zip")
    assert resp.status == 200 and resp.body()[:2] == b"PK"

    # --- Next group: leader starts a new event; the old team's studio is sent back to the join page ---
    leader.reload()
    leader.wait_for_selector("#dash:not(.hidden)")
    leader.fill("#next-event-name", "Cubs Game Jam")
    leader.once("dialog", lambda d: d.accept())
    leader.click("#btn-new-event")
    leader.wait_for_selector("#new-event-done:not(.hidden)")
    assert "Scout Code Game Jam" in leader.inner_text("#archives")
    leader.screenshot(path=str(shots / "9-new-event.png"), full_page=True)
    p1.wait_for_url("**/login", timeout=10000)
    assert leader.inner_text("#join-code").strip() != join
