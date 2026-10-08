"""TencentDB-Agent-Memory 镜像后端（可选），走官方 Python SDK 的 v3 客户端。

SDK 不在 PyPI：从官方仓库 sdk/memory-core/python 安装（包名 tencentdb-agent-memory-sdk-python-v2，
同时带 v2 与 v3 客户端；MemoryCore 文档以 v3 为准，这里只用 v3）。
映射：每条记忆 → L0 conversation/add 一条消息（session = sas-<kind>，由服务端异步抽 L1）；
检索 → L1 atomic/search；画像 → L3 core/read。隔离三元组固定 team=personal / agent=sas / user=me。
"""

from __future__ import annotations

import os
from datetime import datetime

from sas.config import Config

from .base import MemoryBackend, MemoryItem
from .mirror import BackendUnavailable, guard_remote, item_line, safe

TEAM, AGENT, USER = "personal", "sas", "me"


class TDAMMemory(MemoryBackend):
    name = "tdam"

    def __init__(self, config: Config, http_client=None) -> None:
        url = config.tdam_url
        if not url:
            raise BackendUnavailable("tdam：未配置 tdam_url（或环境变量 TDAM_URL）")
        api_key = os.environ.get("TDAM_API_KEY", "")
        if not api_key:
            raise BackendUnavailable("tdam：缺少环境变量 TDAM_API_KEY（不会从配置文件读取密钥）")
        self.cloud = guard_remote("tdam", url, config.tdam_models, config)
        self.config = config
        try:
            from tencentdb_agent_memory._v3_http import HttpStub
            from tencentdb_agent_memory.v3 import MemoryClient
        except ImportError as exc:
            raise BackendUnavailable("tdam：未安装官方 SDK（见 README「记忆后端」安装说明）") from exc
        import httpx

        self.http = http_client or httpx.Client(timeout=10.0)
        try:
            health = self.http.get(f"{url.rstrip('/')}/health")
            ok = health.status_code == 200
        except httpx.HTTPError:
            ok = False
        if not ok:
            raise BackendUnavailable(f"tdam：{url} 不可达或不健康")
        stub = HttpStub(url, api_key, config.tdam_service_id, client=self.http)
        self.client = MemoryClient(stub=stub, team_id=TEAM, agent_id=AGENT, user_id=USER)

    def write(self, items: list[MemoryItem]) -> int:
        by_kind: dict[str, list[MemoryItem]] = {}
        for item in items:
            by_kind.setdefault(item.kind, []).append(item)
        n = 0
        for kind, group in by_kind.items():
            texts = safe([item_line(i)[:8000] for i in group], self.cloud, self.config)
            for start in range(0, len(texts), 100):
                messages = [
                    {"role": "user", "content": t, **({"timestamp": i.observed_at} if i.observed_at else {})}
                    for t, i in zip(texts[start : start + 100], group[start : start + 100])
                ]
                result = self.client.add_conversation(messages, session_id=f"sas-{kind}")
                n += int(result.get("total_count", len(messages)))
        return n

    def search(self, query: str, *, limit: int = 10, now: datetime | None = None) -> list[MemoryItem]:
        (q,) = safe([query], self.cloud, self.config)
        result = self.client.search_atomic(query=q[:2048], limit=min(limit, 100))
        return [
            MemoryItem(kind=h.get("type") or "fact", subject="", text=h.get("content", ""),
                       id=str(h.get("id", "")), confidence=float(h.get("score") or 0.0), source=self.name)
            for h in result.get("items") or []
        ]

    def persona(self) -> str:
        return (self.client.read_core() or {}).get("content", "")

    def list(self, **_kwargs) -> list[MemoryItem]:
        return []
