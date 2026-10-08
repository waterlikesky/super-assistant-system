"""只读 connector 注册表。

新增渠道：写一个 Connector 子类（sniff + parse），在下面 register 一行即可。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .base import Connector, ParseContext, SkipRecord
from .dingtalk import DingTalkConnector
from .email import EmlConnector, MboxConnector
from .events import ChannelEventConnector
from .sms import SmsCsvConnector, SmsXmlConnector
from .wechat import WeChatCsvConnector, WeChatTxtConnector

REGISTRY: dict[str, Connector] = {}

# 用户在 --source 里可以写渠道名（或 borrow-list 里的叫法），展开成具体 connector
ALIASES: dict[str, tuple[str, ...]] = {
    "wechat": ("wechat_txt", "wechat_csv"),
    "wechat_export": ("wechat_txt", "wechat_csv"),
    "email": ("email_eml", "email_mbox"),
    "mail": ("email_eml", "email_mbox"),
    "eml": ("email_eml",),
    "mbox": ("email_mbox",),
    "sms": ("sms_xml", "sms_csv"),
    "dingtalk": ("dingtalk",),
}


def register(connector: Connector) -> Connector:
    if not connector.read_only:
        raise ValueError(f"{connector.name}: 只允许只读 connector")
    REGISTRY[connector.name] = connector
    return connector


# 注册顺序 = 自动识别优先级：特征强的在前，通用 csv 在后
for _c in (
    EmlConnector(),
    MboxConnector(),
    WeChatTxtConnector(),
    WeChatCsvConnector(),
    SmsXmlConnector(),
    SmsCsvConnector(),
    DingTalkConnector(),
    ChannelEventConnector(),
):
    register(_c)


def resolve_source(source: str | None) -> list[Connector]:
    if not source or source == "auto":
        return list(REGISTRY.values())
    names = ALIASES.get(source, (source,))
    missing = [n for n in names if n not in REGISTRY]
    if missing:
        known = ", ".join(sorted(set(REGISTRY) | set(ALIASES)))
        raise KeyError(f"未知 source: {source}（可选：{known}）")
    return [REGISTRY[n] for n in names]


def detect(path: Path, candidates: list[Connector]) -> Connector | None:
    for connector in candidates:
        try:
            if connector.sniff(path):
                return connector
        except (OSError, UnicodeDecodeError):
            continue
    return None


def iter_files(path: Path, recursive: bool = False) -> Iterator[Path]:
    """单个文件直接返回；目录默认只看这一层，-r 才递归。点开头的文件 / 目录一律跳过。"""
    if path.is_file():
        yield path
        return
    entries = sorted(path.rglob("*") if recursive else path.iterdir())
    for item in entries:
        rel = item.relative_to(path).parts
        if any(part.startswith(".") for part in rel):
            continue
        if item.is_file():
            yield item


__all__ = [
    "ALIASES",
    "REGISTRY",
    "Connector",
    "ParseContext",
    "SkipRecord",
    "detect",
    "iter_files",
    "register",
    "resolve_source",
]
