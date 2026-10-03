"""setup/benchmark.py helpers: the "still working?" check, model names, and scoring a run."""

import argparse
import re
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "setup"))
import benchmark  # noqa: E402

from tests.test_edits import BOSS_RETRY_REPLY, SHOOTER_REPLY, STAR_REPLY  # noqa: E402

STARTERS = ROOT / "server" / "starters"


@pytest.mark.parametrize("path", sorted(STARTERS.glob("*.html")), ids=lambda p: p.stem)
def test_starters_look_fine(path):
    html = path.read_text(encoding="utf-8")
    assert benchmark.bracket_problem("\n".join(benchmark.SCRIPT_RE.findall(html))) is None
    assert benchmark.looks_broken(html) is None


def test_bracket_check_catches_slips_and_ignores_strings_and_comments():
    assert benchmark.bracket_problem("function a() { if (x) { y(); }") == "missing a closing bracket for '{'"
    assert benchmark.bracket_problem("a(); }") == "unexpected '}'"
    assert benchmark.bracket_problem("const s = '}{'; // ) [ \n /* { */ let t = `(${s}`;") is None


def test_broken_game_is_flagged_with_and_without_node(monkeypatch):
    html = (STARTERS / "space-shooter.html").read_text(encoding="utf-8")
    broken = html.replace("function update() {\n", "function update() \n", 1)  # lose a brace
    if benchmark.shutil.which("node"):
        assert benchmark.looks_broken(broken)
    monkeypatch.setattr(benchmark.shutil, "which", lambda _: None)
    assert benchmark.looks_broken(broken)
    assert benchmark.looks_broken(html) is None


def test_model_names_match_the_download_script():
    script = (ROOT / "setup" / "download-models.sh").read_text()
    files_block = script[script.index("declare -A FILES"):]
    files = dict(re.findall(r'\[([\w.]+)\]="([^"]+)"', files_block))
    assert files == benchmark.MODEL_FILES
    assert benchmark.model_path("3B").name == files["3b"]
    assert benchmark.model_path("/some/where/model.gguf") == Path("/some/where/model.gguf")


# A broken "success": applies cleanly (deletes a unique line) but leaves an unmatched '}'.
BREAKS_IT = """PLAN: Tidy up.
<<<<<<< SEARCH
function drawEmoji(emoji, x, y, size) {
=======
>>>>>>> REPLACE
"""


@pytest.fixture
def fake_ai():
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        user = body["messages"][-1]["content"]
        retry = "could not be used" in user
        if "player a dragon" in user:
            text = SHOOTER_REPLY
        elif "golden star" in user:
            text = BREAKS_IT if retry else STAR_REPLY
        else:  # the boss request: the retry partly fits but leaves an unclosed "if (...) {"
            text = BOSS_RETRY_REPLY.replace("enemies.push", "nothing.here") if retry else BOSS_RETRY_REPLY
        return {"choices": [{"message": {"content": text}}],
                "timings": {"prompt_n": 20, "prompt_ms": 1500, "predicted_n": 80, "predicted_per_second": 4.5}}

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def test_run_cases_scores_like_the_studio(fake_ai, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(benchmark, "CASES", [
        ("space-shooter", "make the player a dragon 🐉 and the enemies ghosts 👻"),
        ("catch", "add a golden star that gives an extra life"),
        ("space-shooter", "add a boss that appears every 100 points"),
    ])
    args = argparse.Namespace(url=fake_ai, key_file="/nonexistent", cases=3, max_tokens=100, show=True,
                              show_all=False, no_grammar=False)
    results = benchmark.run_cases(benchmark.make_client(args), args, save_to=tmp_path)
    # Both "successes" after the retry are really broken games, and the benchmark now says so.
    assert [r["outcome"] for r in results] == ["first", "broken", "broken"]
    summary = benchmark.summarise(results)
    assert (summary["first"], summary["applied"], summary["working"]) == (1, 3, 1)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["01-space-shooter.html", "02-catch.html",
                                                           "03-space-shooter.html"]
    out = capsys.readouterr().out
    assert "💥 applied but broken" in out and "Still working code: 1/3" in out


def test_compare_switches_models_and_always_restores(fake_ai, monkeypatch, tmp_path, capsys):
    models = tmp_path / "models"
    models.mkdir()
    for f in ("qwen2.5-coder-3b-instruct-q4_k_m.gguf", "qwen3-4b-instruct-2507-q4_k_m.gguf"):
        (models / f).write_text("GGUF")
    original = models / "qwen2.5-coder-3b-instruct-q4_k_m.gguf"
    (models / "current.gguf").symlink_to(original)

    calls, links_seen = [], []

    def fake_systemctl(*args, check=True):
        calls.append(args)
        if args[0] == "restart":
            links_seen.append(Path(benchmark.os.readlink(models / "current.gguf")).name)
        return benchmark.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(benchmark, "MODELS_DIR", models)
    monkeypatch.setattr(benchmark, "systemctl", fake_systemctl)
    monkeypatch.setattr(benchmark.os, "geteuid", lambda: 0)
    monkeypatch.setattr(benchmark, "SAVE_DIR", tmp_path / "saved")
    monkeypatch.setattr(benchmark, "CASES", [("space-shooter", "make the player a dragon 🐉 and the enemies ghosts 👻")])
    args = argparse.Namespace(url=fake_ai, key_file="/nonexistent", cases=1, max_tokens=100, show=False,
                              show_all=False, no_grammar=False, compare=["3b", "4b"])
    benchmark.compare_models(benchmark.make_client(args), args)

    assert links_seen == ["qwen2.5-coder-3b-instruct-q4_k_m.gguf", "qwen3-4b-instruct-2507-q4_k_m.gguf",
                          "qwen2.5-coder-3b-instruct-q4_k_m.gguf"]  # ...and back again
    assert Path(benchmark.os.readlink(models / "current.gguf")) == original
    assert ("stop", "scout-portal") in calls and calls[-1] == ("start", "scout-portal")
    out = capsys.readouterr().out
    assert "Most working games:" in out and "restart scout-llm" in out
    assert (tmp_path / "saved" / "4b" / "01-space-shooter.html").exists()


def test_compare_needs_downloaded_models(monkeypatch, tmp_path):
    monkeypatch.setattr(benchmark, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(benchmark.os, "geteuid", lambda: 0)
    args = argparse.Namespace(url="http://127.0.0.1:1", key_file="/nonexistent", compare=["4b"])
    with pytest.raises(SystemExit, match="download-models.sh 4b"):
        benchmark.compare_models(benchmark.make_client(args), args)
