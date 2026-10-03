"""The "Shut down both Pis" button, with a harmless stand-in for the real poweroff."""

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from server import stats_agent
from server.app import create_app
from server.config import Settings, WorkerConfig

KEY = "secret-key"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def poweroff_log(tmp_path, monkeypatch):
    log = tmp_path / "poweroffs.txt"
    monkeypatch.setattr(stats_agent, "POWEROFF_CMD", ["sh", "-c", f"echo off >> {log}"])
    return log


def start_agent(key_file):
    port = free_port()
    server = stats_agent.make_server("0.0.0.0", port, str(key_file) if key_file else None)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def call(url, key=None, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_agent_needs_the_key(tmp_path, poweroff_log):
    key_file = tmp_path / "llm-key"
    key_file.write_text(KEY + "\n")
    server, port = start_agent(key_file)
    try:
        base = f"http://127.0.0.1:{port}"
        assert call(base + "/stats")[1]["can_shutdown"] is True
        assert call(base + "/shutdown", body={})[0] == 403
        assert call(base + "/shutdown", key="wrong", body={})[0] == 403
        assert call(base + "/shutdown", key=KEY, body={"delay": 0})[0] == 202
        for _ in range(50):
            if poweroff_log.exists():
                break
            time.sleep(0.05)
        assert poweroff_log.read_text().count("off") == 1
    finally:
        server.shutdown()


def test_agent_without_key_never_shuts_down(poweroff_log):
    server, port = start_agent(None)
    try:
        base = f"http://127.0.0.1:{port}"
        assert call(base + "/stats")[1]["can_shutdown"] is False
        assert call(base + "/shutdown", key="anything", body={"delay": 0})[0] == 403
        time.sleep(0.2)
        assert not poweroff_log.exists()
    finally:
        server.shutdown()


def test_dashboard_shuts_down_worker_first_then_basecamp(tmp_path, poweroff_log):
    key_file = tmp_path / "llm-key"
    key_file.write_text(KEY)
    basecamp, p1 = start_agent(key_file)
    worker, p2 = start_agent(key_file)
    settings = Settings(data_dir=tmp_path, leader_pin="123456", warmup=False, workers=[
        WorkerConfig(name="basecamp", llm=f"http://127.0.0.1:{free_port()}", stats=f"http://127.0.0.1:{p1}",
                     api_key=KEY),
        # 127.0.0.2 is still this machine, but doesn't look like "this Pi" to the portal.
        WorkerConfig(name="worker", llm=f"http://127.0.0.2:{free_port()}", stats=f"http://127.0.0.2:{p2}",
                     api_key=KEY),
    ])
    app = create_app(settings)
    try:
        with TestClient(app) as c:
            assert c.post("/api/leader/shutdown").status_code == 401
            c.post("/api/leader/login", json={"pin": "123456"})
            r = c.post("/api/leader/shutdown")
            assert r.status_code == 200, r.text
            results = r.json()["results"]
            assert [x["name"] for x in results] == ["worker", "basecamp"]  # this Pi goes last
            assert all(x["ok"] for x in results)
            assert app.state.db.flag("ai_paused")
        time.sleep(1.5)
        assert poweroff_log.read_text().count("off") == 1  # the worker, after 1 s
        time.sleep(4.5)
        assert poweroff_log.read_text().count("off") == 2  # then basecamp, after 5 s
    finally:
        basecamp.shutdown()
        worker.shutdown()


def test_unreachable_pi_is_reported(tmp_path):
    settings = Settings(data_dir=tmp_path, leader_pin="123456", warmup=False, workers=[
        WorkerConfig(name="worker", llm="http://127.0.0.2:1", stats=f"http://127.0.0.2:{free_port()}", api_key=KEY),
    ])
    with TestClient(create_app(settings)) as c:
        c.post("/api/leader/login", json={"pin": "123456"})
        res = c.post("/api/leader/shutdown").json()["results"]
        assert res[0]["ok"] is False and "couldn't reach" in res[0]["error"]


def test_no_pis_in_development_mode(tmp_path):
    settings = Settings(data_dir=tmp_path, leader_pin="123456", mock=True, warmup=False)
    with TestClient(create_app(settings)) as c:
        c.post("/api/leader/login", json={"pin": "123456"})
        assert c.post("/api/leader/shutdown").status_code == 409
