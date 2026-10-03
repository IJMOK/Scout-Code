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
    assert not (models / ".compare-restore").exists()
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


# ---- Round 5: crash-safe model switching and the memory check ----

import struct  # noqa: E402
import subprocess  # noqa: E402


def write_gguf(path: Path, arch: str, layers: int, heads: int, kv_heads: int, emb: int, key_length: int = 0):
    """A tiny but valid GGUF header with the numbers the memory check reads, plus a vocabulary."""
    def s(text):
        b = text.encode()
        return struct.pack("<Q", len(b)) + b

    kvs = [
        (s("general.architecture"), 8, s(arch)),
        (s(f"{arch}.block_count"), 4, struct.pack("<I", layers)),
        (s(f"{arch}.attention.head_count"), 4, struct.pack("<I", heads)),
        (s(f"{arch}.attention.head_count_kv"), 4, struct.pack("<I", kv_heads)),
        (s(f"{arch}.embedding_length"), 4, struct.pack("<I", emb)),
        *([(s(f"{arch}.attention.key_length"), 4, struct.pack("<I", key_length))] if key_length else []),
        (s("tokenizer.ggml.tokens"), 9, struct.pack("<IQ", 8, 3) + s("a") + s("bb") + s("ccc")),
        (s("tokenizer.ggml.scores"), 9, struct.pack("<IQ", 6, 2000) + b"\0" * 8000),
    ]
    body = b"GGUF" + struct.pack("<IQQ", 3, 0, len(kvs))
    for key, vtype, value in kvs:
        body += key + struct.pack("<I", vtype) + value
    path.write_bytes(body)


def test_gguf_reader_and_memory_estimate(tmp_path, monkeypatch):
    small = tmp_path / "small.gguf"
    write_gguf(small, "qwen2", layers=36, heads=16, kv_heads=2, emb=2048)
    meta = benchmark.gguf_metadata(small)
    assert meta == {"architecture": "qwen2", "block_count": 36, "head_count": 16, "head_count_kv": 2,
                    "embedding_length": 2048}
    # 36 layers x 2 KV heads x (128 + 128) x 2 bytes = 36 KB per token, at 8192 tokens = 288 MB
    kv = 36 * 2 * 256 * 2 * 8192
    assert benchmark.estimated_memory(small) == small.stat().st_size + kv + benchmark.CACHE_RAM + benchmark.HEADROOM


def test_too_big_models_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark, "total_memory", lambda: 8 * 2**30)
    qwen3_4b = tmp_path / "big.gguf"
    write_gguf(qwen3_4b, "qwen3", layers=36, heads=32, kv_heads=8, emb=2560, key_length=128)  # real Qwen3-4B
    # Pretend the file is the real size (2.4 GB) without writing 2.4 GB.
    real_stat = Path.stat
    monkeypatch.setattr(Path, "stat", lambda p, **kw: type("S", (), {"st_size": int(2.4 * 2**30)})()
                        if p == qwen3_4b else real_stat(p, **kw))
    assert "needs about" in benchmark.too_big(qwen3_4b)

    qwen25_3b = tmp_path / "ok.gguf"
    write_gguf(qwen25_3b, "qwen2", layers=36, heads=16, kv_heads=2, emb=2048)
    monkeypatch.setattr(Path, "stat", lambda p, **kw: type("S", (), {"st_size": int(2.0 * 2**30)})()
                        if p in (qwen3_4b, qwen25_3b) else real_stat(p, **kw))
    assert benchmark.too_big(qwen25_3b) is None


def test_unreadable_gguf_uses_a_cautious_estimate(tmp_path):
    junk = tmp_path / "junk.gguf"
    junk.write_bytes(b"not a model" * 100)
    assert benchmark.estimated_memory(junk) == int(junk.stat().st_size * 2.5) + benchmark.CACHE_RAM


def test_leftover_marker_is_restored_on_next_run(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    good = models / "qwen2.5-coder-3b-instruct-q4_k_m.gguf"
    bad = models / "qwen3-4b-instruct-2507-q4_k_m.gguf"
    good.write_text("x")
    bad.write_text("x")
    (models / "current.gguf").symlink_to(bad)  # the Pi died while testing 4b...
    (models / ".compare-restore").write_text(str(good))
    restarted = []
    monkeypatch.setattr(benchmark, "MODELS_DIR", models)
    monkeypatch.setattr(benchmark, "systemctl", lambda *a, check=True: restarted.append(a))
    monkeypatch.setattr(benchmark.os, "geteuid", lambda: 0)
    assert benchmark.restore_after_crash() is True
    assert Path(benchmark.os.readlink(models / "current.gguf")) == good
    assert not (models / ".compare-restore").exists() and restarted == [("restart", "scout-llm")]
    assert benchmark.restore_after_crash() is False  # nothing to do the second time


def test_update_services_restores_too(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    good, bad = models / "good.gguf", models / "bad.gguf"
    good.write_text("x")
    bad.write_text("x")
    (models / "current.gguf").symlink_to(bad)
    (models / ".compare-restore").write_text(str(good))
    out = subprocess.run(["bash", "-c", f'source "{ROOT}/setup/lib.sh"; SCOUT_DIR="{tmp_path}"; restore_model_after_crash'],
                         capture_output=True, text=True, check=True).stdout
    assert "back on good.gguf" in out
    assert Path(benchmark.os.readlink(models / "current.gguf")) == good
    assert not (models / ".compare-restore").exists()


def test_stats_report_the_model(tmp_path, monkeypatch):
    from server import stats_agent

    (tmp_path / "qwen2.5-coder-3b-instruct-q4_k_m.gguf").write_text("x")
    (tmp_path / "current.gguf").symlink_to(tmp_path / "qwen2.5-coder-3b-instruct-q4_k_m.gguf")
    monkeypatch.setattr(stats_agent, "MODELS_DIR", tmp_path)
    assert stats_agent.read_stats()["model"] == "qwen2.5-coder-3b-instruct-q4_k_m.gguf"
