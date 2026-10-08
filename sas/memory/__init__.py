"""记忆层：MemoryBackend 接口 + 默认本地实现（真源）+ 可选镜像（OpenViking / TDAM / mem0，见 ADR 0001）。"""

from __future__ import annotations

import sys
from datetime import datetime

from sas.config import Config
from sas.privacy import PrivacyError
from sas.store import Store

from .base import HALF_LIFE_DAYS, KIND_LABEL, ME, TODO_KINDS, MemoryBackend, MemoryItem
from .local import LocalMemory, decayed, update_people
from .mem0_adapter import Mem0Memory
from .mirror import BackendUnavailable, profile_documents
from .openviking_adapter import OpenVikingMemory
from .tdam_adapter import TDAMMemory
from .rules import EventView, extract


class CompositeMemory(MemoryBackend):
    """本地为主（真源）；镜像后端出错只告警，不影响主流程。"""

    def __init__(self, primary: LocalMemory, mirrors: list[MemoryBackend], notes: dict[str, str] | None = None) -> None:
        self.primary = primary
        self.mirrors = mirrors
        self.notes = notes or {}  # 后端名 → 未启用原因
        self.name = "+".join([primary.name] + [m.name for m in mirrors])

    def write(self, items):
        # 只写真源；镜像在一批摄入结束后由 sync() 按本地合并后的结果推送（带稳定 id 与最新置信度）
        return self.primary.write(items)

    def search(self, query, *, limit=10, now: datetime | None = None):
        hits = self.primary.search(query, limit=limit, now=now)
        for m in self.mirrors:
            try:
                hits += m.search(query, limit=3, now=now)[:3]  # 每个镜像最多补 3 条语义命中
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] {m.name} 检索失败：{exc}", file=sys.stderr)
        return hits

    def list(self, **kwargs):
        return self.primary.list(**kwargs)

    def write_documents(self, docs):
        n = 0
        for m in self.mirrors:
            try:
                n += m.write_documents(docs)
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] {m.name} 同步文档失败：{exc}", file=sys.stderr)
        return n

    def sync(self, store: Store, *, names: set[str] | None = None, items=None) -> dict[str, int]:
        """把本地记忆与人物画像推到所有镜像。items=None 表示全量。"""
        if not self.mirrors:
            return {}
        everything = self.primary.list()
        pushed = {}
        for m in self.mirrors:
            try:
                n = m.write(everything if items is None else items)
                n += m.write_documents(profile_documents(store, everything, names))
                pushed[m.name] = n
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] {m.name} 同步失败：{exc}", file=sys.stderr)
        return pushed

    def close(self, item_id):
        return self.primary.close(item_id)

    def observe_closure(self, ev):
        return self.primary.observe_closure(ev)


MIRRORS = {"openviking": OpenVikingMemory, "tdam": TDAMMemory, "mem0": Mem0Memory}


def get_backend(config: Config, store: Store, *, quiet: bool = False) -> CompositeMemory:
    local = LocalMemory(store)
    mirrors: list[MemoryBackend] = []
    notes: dict[str, str] = {}
    for name in config.memory_backends():
        if name == "local":
            continue
        try:
            mirrors.append(MIRRORS[name](config))
            notes[name] = "已连接"
        except (BackendUnavailable, PrivacyError) as exc:
            notes[name] = str(exc)
            if not quiet:
                print(f"[info] {exc}；继续使用本地记忆", file=sys.stderr)
    return CompositeMemory(local, mirrors, notes)


__all__ = [
    "BackendUnavailable",
    "CompositeMemory",
    "EventView",
    "HALF_LIFE_DAYS",
    "KIND_LABEL",
    "LocalMemory",
    "ME",
    "Mem0Memory",
    "OpenVikingMemory",
    "TDAMMemory",
    "MemoryBackend",
    "MemoryItem",
    "TODO_KINDS",
    "decayed",
    "extract",
    "get_backend",
    "update_people",
]
