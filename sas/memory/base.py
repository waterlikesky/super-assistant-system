"""记忆层接口。默认实现是本地规则 + SQLite（local.py）；mem0 为可选适配器。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

ME = "我"

# kind → 半衰期（天）。偏好最稳定，约定 / 待办过期最快
HALF_LIFE_DAYS = {
    "preference": 180.0,
    "fact": 120.0,
    "commitment": 30.0,
    "request": 30.0,
    "plan": 14.0,
}
KIND_LABEL = {
    "preference": "偏好",
    "fact": "事实",
    "commitment": "承诺",
    "request": "请求",
    "plan": "约定",
    "profile": "画像",
    "document": "文档",
    "episodic": "事件",
    "persona": "画像",
    "instruction": "指令",
}
TODO_KINDS = ("commitment", "request")


@dataclass
class MemoryItem:
    kind: str  # preference | fact | commitment | request | plan
    subject: str  # 谁的（偏好/事实），谁答应的（commitment），谁提的（request）
    text: str
    counterpart: str = ""  # 对谁（commitment / request）
    confidence: float = 0.5
    due: str | None = None  # YYYY-MM-DD
    status: str | None = None  # open | done（仅 commitment / request）
    source_event_ids: list[str] = field(default_factory=list)
    observed_at: str = ""  # ISO 时间：被观察到的消息时间
    conversation: str = ""
    channel: str = ""
    id: str = ""
    evidence: int = 1
    first_seen: str = ""
    last_seen: str = ""
    effective_confidence: float | None = None
    source: str = "local"  # 来自哪个后端：local | openviking | tdam | mem0

    @property
    def label(self) -> str:
        return KIND_LABEL.get(self.kind, self.kind)


class MemoryBackend(ABC):
    """所有后端共享的最小接口：写入、检索、列出、关闭待办。"""

    name: str = "base"

    @abstractmethod
    def write(self, items: list[MemoryItem]) -> int:
        """写入（与已有记忆去重合并），返回新增条数。"""

    @abstractmethod
    def search(self, query: str, *, limit: int = 10, now: datetime | None = None) -> list[MemoryItem]:
        """按文本检索，结果带衰减后的 effective_confidence。"""

    @abstractmethod
    def list(
        self,
        *,
        kind: str | tuple[str, ...] | None = None,
        subject: str | None = None,
        counterpart: str | None = None,
        status: str | None = None,
        now: datetime | None = None,
        min_confidence: float = 0.0,
    ) -> list[MemoryItem]:
        ...

    def close(self, item_id: str) -> bool:
        return False

    # 镜像后端可选实现：同步人物画像 / 每日摘要等 Markdown 文档
    def write_documents(self, docs: dict[str, str]) -> int:
        """docs: 相对路径（如 people/老王.md）→ Markdown。返回写入数。"""
        return 0
