"""OpenViking 镜像后端（ADR 0001 主推），走官方 openviking-sdk（HTTP）。

sas 不包含 OpenViking（AGPL-3.0）的任何代码，只调用用户自己运行的 server。
布局（默认 root = viking://resources/sas）：
    memories/<kind>/<id>.md   每条记忆一份 Markdown（frontmatter 带 sas_id、置信度、出处 event id）
    people/<名字>.md          人物画像
    digests/<日期>.md         每日摘要（sas digest --sync 时）
OpenViking 会为这些文件生成 L0/L1 摘要并建向量；sas ask 通过 find() 做语义召回。
"""

from __future__ import annotations

import os
from datetime import datetime

from sas.config import Config

from .base import MemoryBackend, MemoryItem
from .mirror import BackendUnavailable, guard_remote, item_markdown, item_path, safe

KIND_FROM_DIR = {"commitment", "request", "preference", "fact", "plan"}


class OpenVikingMemory(MemoryBackend):
    name = "openviking"

    def __init__(self, config: Config, client=None) -> None:
        url = config.openviking_url
        if not url:
            raise BackendUnavailable("openviking：未配置 openviking_url（或环境变量 OPENVIKING_URL）")
        self.cloud = guard_remote("openviking", url, config.openviking_models, config)
        self.config = config
        self.root = config.openviking_root.rstrip("/")
        if client is None:
            try:
                from openviking_sdk import SyncHTTPClient
            except ImportError as exc:
                raise BackendUnavailable("openviking：未安装 openviking-sdk（pip install 'super-assistant-system[openviking]'）") from exc
            client = SyncHTTPClient(url=url, api_key=os.environ.get("OPENVIKING_API_KEY") or None, timeout=10.0)
            client.initialize()
        self.client = client
        if not self.client.health():
            raise BackendUnavailable(f"openviking：{url} 不可达或不健康")

    def _uri(self, rel: str) -> str:
        return f"{self.root}/{rel}"

    def _batch(self, docs: dict[str, str]) -> int:
        if not docs:
            return 0
        paths = list(docs)
        contents = safe([docs[p] for p in paths], self.cloud, self.config)
        ops = [{"uri": self._uri(p), "content": c, "mode": "upsert"} for p, c in zip(paths, contents)]
        for i in range(0, len(ops), 50):
            self.client.batch_write(self.root, ops[i : i + 50], wait=False)
        return len(ops)

    def write(self, items: list[MemoryItem]) -> int:
        return self._batch({item_path(i): item_markdown(i) for i in items})

    def write_documents(self, docs: dict[str, str]) -> int:
        return self._batch(docs)

    def search(self, query: str, *, limit: int = 10, now: datetime | None = None) -> list[MemoryItem]:
        (q,) = safe([query], self.cloud, self.config)
        result = self.client.find(query=q, target_uri=self.root, limit=limit) or {}
        out = []
        for bucket in ("memories", "resources", "skills"):
            for hit in result.get(bucket) or []:
                uri = hit.get("uri", "")
                rel = uri[len(self.root) + 1 :] if uri.startswith(self.root) else uri
                parts = rel.split("/")
                kind = parts[1] if len(parts) > 2 and parts[0] == "memories" and parts[1] in KIND_FROM_DIR else (
                    "profile" if parts[0] == "people" else "document"
                )
                text = (hit.get("abstract") or hit.get("overview") or "").strip() or rel
                out.append(
                    MemoryItem(kind=kind, subject=parts[-1].removesuffix(".md") if kind == "profile" else "",
                               text=text, id=uri, confidence=float(hit.get("score") or 0.0), source=self.name)
                )
        out.sort(key=lambda i: i.confidence, reverse=True)
        return out[:limit]

    def list(self, **_kwargs) -> list[MemoryItem]:
        return []  # 结构化列表以本地为准
