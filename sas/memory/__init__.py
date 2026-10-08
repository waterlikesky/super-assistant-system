"""记忆层：MemoryBackend 接口 + 默认本地实现 + 可选 mem0 镜像。"""

from __future__ import annotations

import sys
from datetime import datetime

from sas.config import Config
from sas.privacy import PrivacyError
from sas.store import Store

from .base import HALF_LIFE_DAYS, KIND_LABEL, ME, TODO_KINDS, MemoryBackend, MemoryItem
from .local import LocalMemory, decayed, update_people
from .mem0_adapter import BackendUnavailable, Mem0Memory
from .rules import EventView, extract


class CompositeMemory(MemoryBackend):
    """本地为主；镜像后端（mem0）出错只告警，不影响主流程。"""

    def __init__(self, primary: LocalMemory, mirrors: list[MemoryBackend]) -> None:
        self.primary = primary
        self.mirrors = mirrors
        self.name = "+".join([primary.name] + [m.name for m in mirrors])

    def write(self, items):
        n = self.primary.write(items)
        for m in self.mirrors:
            try:
                m.write(items)
            except Exception as exc:  # noqa: BLE001 — 镜像失败不阻断摄入
                print(f"[warn] {m.name} 写入失败：{exc}", file=sys.stderr)
        return n

    def search(self, query, *, limit=10, now: datetime | None = None):
        hits = self.primary.search(query, limit=limit, now=now)
        for m in self.mirrors:
            try:
                hits += m.search(query, limit=limit, now=now)
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] {m.name} 检索失败：{exc}", file=sys.stderr)
        return hits[:limit]

    def list(self, **kwargs):
        return self.primary.list(**kwargs)

    def close(self, item_id):
        return self.primary.close(item_id)

    def observe_closure(self, ev):
        return self.primary.observe_closure(ev)


def get_backend(config: Config, store: Store) -> CompositeMemory:
    local = LocalMemory(store)
    mirrors: list[MemoryBackend] = []
    if config.memory_backend == "mem0":
        try:
            mirrors.append(Mem0Memory(config))
        except (BackendUnavailable, PrivacyError) as exc:
            print(f"[info] {exc}；继续使用本地记忆", file=sys.stderr)
    return CompositeMemory(local, mirrors)


__all__ = [
    "BackendUnavailable",
    "CompositeMemory",
    "EventView",
    "HALF_LIFE_DAYS",
    "KIND_LABEL",
    "LocalMemory",
    "ME",
    "Mem0Memory",
    "MemoryBackend",
    "MemoryItem",
    "TODO_KINDS",
    "decayed",
    "extract",
    "get_backend",
    "update_people",
]
