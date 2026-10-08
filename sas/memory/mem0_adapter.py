"""可选：把抽出的记忆同步一份到 mem0（mem0ai）。

本地 SQLite 仍是主存储（待办、人物画像依赖结构化字段）；mem0 作为镜像，提供语义检索。
未安装 mem0ai 时抛 BackendUnavailable，由 get_backend() 降级为纯本地。
mem0 默认配置会调用 OpenAI：除非在 sas.toml 的 [sas.mem0] 里配成本地 Ollama，
否则必须显式 SAS_ALLOW_CLOUD_LLM=true；送出的文本一律先脱敏。
"""

from __future__ import annotations

from datetime import datetime

from sas.config import Config
from sas.privacy import is_local_url, prepare_for_model

from .base import MemoryBackend, MemoryItem
from .mirror import BackendUnavailable


def _is_local_config(cfg: dict) -> bool:
    llm = (cfg.get("llm") or {}).get("provider")
    emb = (cfg.get("embedder") or {}).get("provider")
    urls = [
        (cfg.get("llm") or {}).get("config", {}).get("ollama_base_url", "http://localhost:11434"),
        (cfg.get("embedder") or {}).get("config", {}).get("ollama_base_url", "http://localhost:11434"),
    ]
    return llm == "ollama" and emb == "ollama" and all(is_local_url(u) for u in urls)


class Mem0Memory(MemoryBackend):
    name = "mem0"

    def __init__(self, config: Config, user_id: str = "me") -> None:
        try:
            from mem0 import Memory  # type: ignore
        except ImportError as exc:
            raise BackendUnavailable("未安装 mem0ai：pip install 'super-assistant-system[mem0]'") from exc
        mem0_cfg = config.extra.get("mem0") or {}
        self.cloud = not _is_local_config(mem0_cfg)
        prepare_for_model([], cloud=self.cloud, allow_cloud=config.allow_cloud_llm)  # 未授权直接拒绝
        self.allow_cloud = config.allow_cloud_llm
        self.user_id = user_id
        self.client = Memory.from_config(mem0_cfg) if mem0_cfg else Memory()

    def write(self, items: list[MemoryItem]) -> int:
        n = 0
        for item in items:
            (text,) = prepare_for_model([f"{item.subject}（{item.label}）：{item.text}"], cloud=self.cloud, allow_cloud=self.allow_cloud)
            self.client.add(text, user_id=self.user_id, metadata={"kind": item.kind, "subject": item.subject})
            n += 1
        return n

    def search(self, query: str, *, limit: int = 10, now: datetime | None = None) -> list[MemoryItem]:
        (q,) = prepare_for_model([query], cloud=self.cloud, allow_cloud=self.allow_cloud)
        result = self.client.search(q, user_id=self.user_id, limit=limit)
        hits = result.get("results", result) if isinstance(result, dict) else result
        out = []
        for h in hits or []:
            meta = h.get("metadata") or {}
            out.append(
                MemoryItem(kind=meta.get("kind", "fact"), subject=meta.get("subject", ""), text=h.get("memory", ""),
                           confidence=float(h.get("score") or 0.5), id=str(h.get("id", "")), source=self.name)
            )
        return out

    def list(self, **_kwargs) -> list[MemoryItem]:
        return []
