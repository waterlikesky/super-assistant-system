"""外部记忆镜像（ADR 0001）：OpenViking 用假 server 走官方 SDK 的真实 HTTP；TDAM 用 httpx.MockTransport。

设置 OPENVIKING_URL / TDAM_URL（+ TDAM_API_KEY）时额外跑真实集成测试，否则 skip。
"""

import json
import os
import socket
import threading
import time

import httpx
import pytest

from sas.assistant import Assistant
from sas.config import Config
from sas.ingest import ingest_path
from sas.memory import get_backend
from sas.memory.mirror import BackendUnavailable
from sas.privacy import PrivacyError
from sas.store import Store

from .conftest import EXPORTS, NOW
from .test_store_ingest import SECRETS

fastapi = pytest.importorskip("fastapi")
uvicorn = pytest.importorskip("uvicorn")


# ---------- 假 OpenViking server：只实现适配器用到的 4 个接口 ----------

def fake_openviking():
    from fastapi import FastAPI, Request

    app = FastAPI()
    app.state.files = {}
    app.state.requests = []

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/v1/content/batch-write")
    async def batch_write(request: Request):
        body = await request.json()
        app.state.requests.append(("batch-write", body, dict(request.headers)))
        for op in body["operations"]:
            assert op["mode"] == "upsert"
            app.state.files[op["uri"]] = op["content"]
        return {"status": "ok", "result": {"written": len(body["operations"])}}

    @app.post("/api/v1/search/find")
    async def find(request: Request):
        body = await request.json()
        app.state.requests.append(("find", body, dict(request.headers)))
        hits = [
            {"uri": uri, "abstract": text.strip().splitlines()[-1], "score": 0.9, "context_type": "resource"}
            for uri, text in app.state.files.items()
            if uri.startswith(body["target_uri"]) and body["query"] in text
        ]
        return {"status": "ok", "result": {"memories": [], "resources": hits[: body["limit"]], "skills": []}}

    return app


@pytest.fixture
def ov_server():
    app = fake_openviking()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield app, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def ov_config(tmp_path, url, **kw):
    pytest.importorskip("openviking_sdk")
    values = dict(db_path=tmp_path / "sas.db", memory_backend="openviking", openviking_url=url, openviking_models="local")
    values.update(kw)
    return Config.load(env={}, **values)


def test_openviking_mirror_receives_redacted_memories_and_profiles(tmp_path, ov_server):
    app, url = ov_server
    cfg = ov_config(tmp_path, url)
    store = Store(cfg.db_path)
    memory = get_backend(cfg, store)
    assert memory.name == "local+openviking"
    report = ingest_path(EXPORTS, store=store, memory=memory, config=cfg, recursive=True)
    assert report.mirrored > 0

    files = app.state.files
    assert any(u.startswith("viking://resources/sas/memories/commitment/") for u in files)
    profile = files["viking://resources/sas/people/老王.md"]
    assert "不吃香菜" in profile and "合同我发你邮箱" in profile
    blob = json.dumps(files, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in blob, secret
    # 本地仍是真源：本地记忆条数不受镜像影响
    assert store.count("memories") == 27


def test_openviking_search_merges_into_ask(tmp_path, ov_server):
    app, url = ov_server
    cfg = ov_config(tmp_path, url)
    store = Store(cfg.db_path)
    memory = get_backend(cfg, store)
    ingest_path(EXPORTS, store=store, memory=memory, config=cfg, recursive=True)
    hits = memory.mirrors[0].search("香菜")
    assert hits and hits[0].source == "openviking"
    ans = Assistant(store, memory, now=NOW).ask("香菜")
    assert "来自 openviking" in ans.render()
    find = [r for r in app.state.requests if r[0] == "find"][-1]
    assert find[1]["target_uri"] == "viking://resources/sas"


def test_full_sync_command(tmp_path, ov_server, capsys):
    from sas.cli import main

    app, url = ov_server
    db = tmp_path / "sas.db"
    assert main(["--db", str(db), "ingest", str(EXPORTS), "-r"]) == 0
    assert not app.state.files  # 没配置镜像时不外发
    os.environ["SAS_MEMORY_BACKEND"], os.environ["SAS_OPENVIKING_URL"], os.environ["SAS_OPENVIKING_MODELS"] = "openviking", url, "local"
    try:
        assert main(["--db", str(db), "sync"]) == 0
    finally:
        for k in ("SAS_MEMORY_BACKEND", "SAS_OPENVIKING_URL", "SAS_OPENVIKING_MODELS"):
            os.environ.pop(k)
    assert "openviking：推送" in capsys.readouterr().out
    assert len(app.state.files) > 20


def test_openviking_cloud_models_need_explicit_opt_in(tmp_path, ov_server):
    _, url = ov_server
    cfg = ov_config(tmp_path, url, openviking_models="cloud")
    memory = get_backend(cfg, Store(cfg.db_path), quiet=True)
    assert memory.mirrors == [] and "SAS_ALLOW_CLOUD_LLM" in memory.notes["openviking"]
    cfg.allow_cloud_llm = True
    assert get_backend(cfg, Store(cfg.db_path), quiet=True).mirrors


def test_openviking_remote_host_counts_as_cloud(tmp_path):
    cfg = Config.load(env={}, db_path=tmp_path / "x.db", openviking_url="https://ov.example.com", openviking_models="local")
    from sas.memory import OpenVikingMemory

    with pytest.raises(PrivacyError):
        OpenVikingMemory(cfg)


def test_openviking_unreachable_degrades(tmp_path):
    pytest.importorskip("openviking_sdk")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # 端口此刻无人监听
    cfg = ov_config(tmp_path, f"http://127.0.0.1:{port}")
    store = Store(cfg.db_path)
    memory = get_backend(cfg, store, quiet=True)
    assert memory.mirrors == [] and "不可达" in memory.notes["openviking"]
    report = ingest_path(EXPORTS, store=store, memory=memory, config=cfg, recursive=True)
    assert report.new == 28  # 降级后照常摄入


def test_unconfigured_backend_note(tmp_path):
    cfg = Config.load(env={}, db_path=tmp_path / "x.db", memory_backend="openviking,tdam")
    memory = get_backend(cfg, Store(cfg.db_path), quiet=True)
    assert memory.name == "local"
    assert "openviking_url" in memory.notes["openviking"] and "tdam_url" in memory.notes["tdam"]


# ---------- TDAM：httpx.MockTransport 模拟 MemoryCore v3 ----------

def tdam_transport(log):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        body = json.loads(request.content)
        log.append((request.url.path, body, dict(request.headers)))
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.headers["x-tdai-service-id"] == "default"
        assert (body["team_id"], body["agent_id"], body["user_id"]) == ("personal", "sas", "me")
        if request.url.path == "/v3/conversation/add":
            n = len(body["messages"])
            return httpx.Response(200, json={"code": 0, "message": "ok", "request_id": "r", "data": {
                "accepted_ids": [f"m{i}" for i in range(n)], "accepted_versions": ["v1"] * n, "total_count": n}})
        if request.url.path == "/v3/atomic/search":
            return httpx.Response(200, json={"code": 0, "message": "ok", "request_id": "r", "data": {"items": [
                {"id": "a1", "version": 1, "type": "persona", "content": "老王不吃香菜", "score": 0.8}]}})
        if request.url.path == "/v3/core/read":
            return httpx.Response(200, json={"code": 0, "message": "ok", "request_id": "r", "data": {"content": "# 我"}})
        return httpx.Response(404, json={"code": 404, "message": "not found"})

    return httpx.MockTransport(handler)


def tdam_backend(tmp_path, monkeypatch, log, **kw):
    pytest.importorskip("tencentdb_agent_memory.v3")
    from sas.memory import TDAMMemory

    monkeypatch.setenv("TDAM_API_KEY", "test-key")
    values = dict(db_path=tmp_path / "x.db", tdam_url="http://127.0.0.1:8420", tdam_models="local")
    values.update(kw)
    cfg = Config.load(env={}, **values)
    return cfg, TDAMMemory(cfg, http_client=httpx.Client(transport=tdam_transport(log)))


def test_tdam_v3_write_and_search(tmp_path, monkeypatch, store, memory, ingested):
    log = []
    _, tdam = tdam_backend(tmp_path, monkeypatch, log)
    items = memory.list()
    assert tdam.write(items) == len(items)
    adds = [b for p, b, _ in log if p == "/v3/conversation/add"]
    assert {b["session_id"] for b in adds} >= {"sas-commitment", "sas-preference"}
    sent = json.dumps(adds, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in sent
    hits = tdam.search("香菜")
    assert hits[0].source == "tdam" and hits[0].text == "老王不吃香菜"
    assert tdam.persona() == "# 我"


def test_tdam_requires_key_and_cloud_opt_in(tmp_path, monkeypatch):
    from sas.memory import TDAMMemory

    monkeypatch.delenv("TDAM_API_KEY", raising=False)
    cfg = Config.load(env={}, db_path=tmp_path / "x.db", tdam_url="http://127.0.0.1:8420", tdam_models="local")
    with pytest.raises(BackendUnavailable, match="TDAM_API_KEY"):
        TDAMMemory(cfg)
    monkeypatch.setenv("TDAM_API_KEY", "k")
    cfg.tdam_models = "cloud"
    with pytest.raises(PrivacyError):
        TDAMMemory(cfg)


# ---------- 真实集成（可选）----------

@pytest.mark.skipif(not os.environ.get("OPENVIKING_URL"), reason="未设置 OPENVIKING_URL")
def test_real_openviking_roundtrip(tmp_path):
    cfg = ov_config(tmp_path, os.environ["OPENVIKING_URL"], openviking_root="viking://resources/sas-it")
    cfg.allow_cloud_llm = os.environ.get("SAS_ALLOW_CLOUD_LLM", "false") == "true"
    memory = get_backend(cfg, Store(cfg.db_path))
    if not memory.mirrors:
        pytest.skip(memory.notes["openviking"])
    assert memory.mirrors[0].write_documents({"it/hello.md": "# 集成测试\n老王不吃香菜\n"}) == 1


@pytest.mark.skipif(not (os.environ.get("TDAM_URL") and os.environ.get("TDAM_API_KEY")), reason="未设置 TDAM_URL / TDAM_API_KEY")
def test_real_tdam_roundtrip(tmp_path):
    cfg = Config.load(env={}, db_path=tmp_path / "x.db", tdam_url=os.environ["TDAM_URL"], memory_backend="tdam")
    cfg.allow_cloud_llm = os.environ.get("SAS_ALLOW_CLOUD_LLM", "false") == "true"
    memory = get_backend(cfg, Store(cfg.db_path))
    if not memory.mirrors:
        pytest.skip(memory.notes["tdam"])
    from sas.memory import MemoryItem

    assert memory.mirrors[0].write([MemoryItem(kind="preference", subject="老王", text="不吃香菜")]) == 1
