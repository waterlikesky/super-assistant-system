"""Connector 接口与共用工具。

connector 只做一件事：把一个**本地导出文件**读成 ChannelEvent 字典（尚未脱敏）。
没有任何网络、发送或写回原文件的能力。
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Iterable, Iterator

from sas.config import Config
from sas.redact import redact_text


class SkipRecord(Exception):
    """单条记录 / 单个文件无法解析：记录原因后跳过，不写半条事件。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class ParseContext:
    config: Config
    consent_tag: str
    root: Path | None = None
    skipped: list[tuple[str, str]] = field(default_factory=list)
    _seen: Counter = field(default_factory=Counter)

    @property
    def tz(self) -> tzinfo:
        return self.config.tzinfo()

    def skip(self, where: str, reason: str) -> None:
        self.skipped.append((where, reason))

    def unique(self, base_id: str) -> str:
        """同一文件里完全相同的两条消息（同秒同人同文）用序号区分，重跑结果不变。"""
        n = self._seen[base_id]
        self._seen[base_id] += 1
        return base_id if n == 0 else f"{base_id}-{n}"


class Connector(ABC):
    name: str = ""
    channel: str = "other"
    description: str = ""
    suffixes: tuple[str, ...] = ()
    read_only: bool = True  # 所有 connector 只读；没有 send 方法

    def sniff(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    @abstractmethod
    def parse(self, path: Path, ctx: ParseContext) -> Iterator[dict]:
        raise NotImplementedError


# ---------- 共用工具 ----------

TIME_RE = re.compile(
    r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)


def parse_time(value, tz: tzinfo) -> datetime:
    """接受 unix 秒/毫秒、ISO、'2026-10-05 21:40:12'、'2026/10/5 9:05'、'2026年10月5日 09:05'。"""
    if value is None:
        raise SkipRecord("缺少时间")
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            raise SkipRecord("缺少时间")
        if re.fullmatch(r"\d{12,13}", text):
            return datetime.fromtimestamp(int(text) / 1000, tz)
        if re.fullmatch(r"\d{9,10}(\.\d+)?", text):
            return datetime.fromtimestamp(float(text), tz)
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            m = TIME_RE.search(text)
            if not m:
                raise SkipRecord(f"无法解析时间: {text[:30]}")
            y, mo, d, h, mi, s = m.groups()
            try:
                dt = datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))
            except ValueError as exc:
                raise SkipRecord(f"无法解析时间: {text[:30]}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def short_hash(*parts: str, n: int = 16) -> str:
    joined = "\x1f".join(p or "" for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:n]


def stable_id(channel: str, *parts: str) -> str:
    """基于脱敏后的内容算 id：同一条消息重复摄入 id 不变，且 id 不泄露原文里的号码。"""
    return f"{channel}:{short_hash(*(redact_text(p or '') for p in parts))}"


def name_handle(channel: str, name: str) -> str:
    return f"{channel}:{short_hash(name.strip(), n=12)}"


def phone_tail(address: str) -> str:
    digits = re.sub(r"\D", "", address)
    return f"尾号{digits[-4:]}" if len(digits) >= 7 else address


def is_service_address(address: str) -> bool:
    """短信服务号 / 邮件通知地址：不算「人」，也不进待回复。"""
    a = address.strip().lower()
    if "@" in a:
        local = a.split("@", 1)[0]
        return bool(re.search(r"no-?reply|notice|notification|newsletter|news|service|alert|mailer|bank", local))
    digits = re.sub(r"\D", "", a)
    if not digits:
        return False
    return len(digits) <= 8 or digits.startswith(("106", "95", "96", "100", "12"))


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_csv_rows(path: Path) -> tuple[list[str], list[dict]]:
    text = read_text(path)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = [{(k or "").strip(): (v or "").strip() if isinstance(v, str) else v for k, v in row.items()} for row in reader]
    return [h.strip() for h in (reader.fieldnames or [])], rows


def read_csv_header(path: Path) -> list[str]:
    try:
        first = read_text(path).splitlines()[0]
    except (IndexError, OSError):
        return []
    delim = "\t" if first.count("\t") > first.count(",") else ","
    return [h.strip().strip('"') for h in next(csv.reader([first], delimiter=delim))]


def pick(row: dict, aliases: Iterable[str]) -> str:
    lowered = {k.lower(): v for k, v in row.items() if k}
    for alias in aliases:
        value = lowered.get(alias.lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def has_any(header: Iterable[str], aliases: Iterable[str]) -> bool:
    cols = {h.lower() for h in header}
    return any(a.lower() in cols for a in aliases)


def make_chat_event(
    *,
    ctx: ParseContext,
    channel: str,
    via: str,
    path: Path,
    conversation: str,
    sender: str,
    is_me: bool,
    when: datetime,
    text: str,
    peer: str | None = None,
    is_group: bool = False,
    sender_handle: str | None = None,
    extra: dict | None = None,
) -> dict:
    """IM 类（微信 / 钉钉 / 短信）消息的统一构造。"""
    me_name = "我"
    sender_name = me_name if is_me else sender
    participants = [
        {
            "role": "self" if is_me else "from",
            "handle": sender_handle or name_handle(channel, sender_name),
            "display_name": sender_name,
        }
    ]
    if not is_group:
        to_name = peer if is_me else me_name
        if to_name:
            participants.append(
                {"role": "to" if is_me else "self", "handle": name_handle(channel, to_name), "display_name": to_name}
            )
    base = stable_id(channel, conversation, when.isoformat(), sender_name, text)
    metadata = {"ingest_via": via, "is_group": is_group, "source_name": path.name}
    if extra:
        metadata.update(extra)
    return {
        "id": ctx.unique(base),
        "channel": channel,
        "direction": "outbound" if is_me else "inbound",
        "timestamp": when.isoformat(),
        "participants": participants,
        "thread_id": f"{channel}:{short_hash(conversation, n=12)}",
        "conversation": conversation,
        "content_text": text,
        "sensitivity": "personal",
        "consent_tag": ctx.consent_tag,
        "raw_ref": str(path.resolve()),
        "metadata": metadata,
    }
