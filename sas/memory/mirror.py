"""镜像到外部记忆后端时共用的工具：隐私闸门、记忆 / 画像的 Markdown 渲染。

外部后端拿到的永远是**本地已脱敏**的数据再过一遍 redact；本地 SQLite 是真源。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sas.config import Config
from sas.privacy import PrivacyError, is_local_url, prepare_for_model
from sas.store import Store

from .base import TODO_KINDS, MemoryItem


class BackendUnavailable(RuntimeError):
    """缺包、未配置、server 不可达：调用方降级为纯本地。"""


def guard_remote(name: str, url: str, models: str, config: Config) -> bool:
    """返回 cloud 标记；需要云端而未授权时抛 PrivacyError。"""
    cloud = models == "cloud" or not is_local_url(url)
    if cloud and not config.allow_cloud_llm:
        where = "server 不在本机" if not is_local_url(url) else f"{name}_models=cloud"
        raise PrivacyError(
            f"{name}：{where}，内容可能被云端模型处理。确认后设置 SAS_ALLOW_CLOUD_LLM=true，"
            f"或在 server 用本地模型时设置 SAS_{name.upper()}_MODELS=local"
        )
    return cloud


def safe(texts: list[str], cloud: bool, config: Config) -> list[str]:
    return prepare_for_model(texts, cloud=cloud, allow_cloud=config.allow_cloud_llm)


def slug(text: str) -> str:
    return re.sub(r"[\\/:*?\"<>|\s]+", "_", text).strip("_") or "unnamed"


def item_path(item: MemoryItem) -> str:
    return f"memories/{item.kind}/{slug(item.id or item.text[:20])}.md"


def item_line(item: MemoryItem) -> str:
    who = f"{item.subject} → {item.counterpart}" if item.counterpart else item.subject
    due = f"（截止 {item.due}）" if item.due else ""
    return f"[{item.label}] {who}：{item.text}{due}"


def item_markdown(item: MemoryItem) -> str:
    meta = {
        "sas_id": item.id, "kind": item.kind, "subject": item.subject, "counterpart": item.counterpart,
        "confidence": round(item.confidence, 3), "due": item.due, "status": item.status,
        "observed_at": item.observed_at or item.last_seen, "sources": item.source_event_ids,
    }
    front = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items() if v not in (None, "", []))
    return f"---\n{front}\n---\n\n{item_line(item)}\n"


def profile_markdown(person: dict, items: list[MemoryItem]) -> str:
    channels = json.loads(person["channels"]) if isinstance(person["channels"], str) else person["channels"]
    lines = [
        f"# {person['name']}", "",
        f"- 渠道：{'、'.join(channels)}",
        f"- 往来：收 {person['msg_in']} / 发 {person['msg_out']}",
        f"- 首次联系：{person['first_seen'][:10]}，最近联系：{person['last_seen'][:16].replace('T', ' ')}",
        "",
    ]
    groups = (
        ("偏好", [i for i in items if i.kind == "preference"]),
        ("事实", [i for i in items if i.kind == "fact"]),
        ("约定", [i for i in items if i.kind == "plan"]),
        ("未完成", [i for i in items if i.kind in TODO_KINDS and i.status == "open"]),
    )
    for title, group in groups:
        if group:
            lines += [f"## {title}", *[f"- {item_line(i)}" for i in group], ""]
    lines.append(f"<!-- 由 sas 从本地脱敏数据生成于 {datetime.now(timezone.utc).isoformat(timespec='seconds')} -->")
    return "\n".join(lines) + "\n"


def profile_documents(store: Store, items: list[MemoryItem], names: set[str] | None = None) -> dict[str, str]:
    docs = {}
    for person in store.query("select * from people"):
        if names is not None and person["name"] not in names:
            continue
        mine = [i for i in items if person["name"] in (i.subject, i.counterpart)]
        docs[f"people/{slug(person['name'])}.md"] = profile_markdown(person, mine)
    return docs
