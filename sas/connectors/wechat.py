"""微信：只吃 WeChatMsg / MemoTrace（留痕）等工具导出的 txt / csv。

不解密、不读数据库、不 Hook。文件名（去扩展名）作为会话名：私聊 = 对方备注，群聊 = 群名。

txt（留痕「导出 txt」）：
    2026-10-05 21:40:12 老王
    项目下周一切一……
    <空行>
也接受「老王 2026-10-05 21:40:12」的抬头顺序。

csv（留痕「导出 csv」）列：localId,TalkerId,Type,SubType,IsSender,CreateTime,Status,
StrContent,StrTime,Remark,NickName,Sender。只保留文本类消息（Type 1 / 49）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from .base import (
    Connector,
    ParseContext,
    SkipRecord,
    has_any,
    make_chat_event,
    parse_time,
    pick,
    read_csv_header,
    read_csv_rows,
    read_text,
)

TS = r"\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?"
HEAD_TS_FIRST = re.compile(rf"^(?P<ts>{TS})\s+(?P<name>\S.{{0,60}}?)\s*$")
HEAD_NAME_FIRST = re.compile(rf"^(?P<name>\S.{{0,60}}?)\s+(?P<ts>{TS})\s*$")

WECHAT_CSV_MARKERS = ("StrContent", "IsSender", "StrTime", "TalkerId")
TEXT_TYPES = {"", "1", "49"}


def _header(line: str) -> tuple[str, str] | None:
    for pattern in (HEAD_TS_FIRST, HEAD_NAME_FIRST):
        m = pattern.match(line.strip())
        if m:
            return m.group("ts"), m.group("name").strip()
    return None


def _emit(records: list[tuple], conversation: str, path: Path, ctx: ParseContext, via: str) -> Iterator[dict]:
    """records: (when, sender, is_me, text, where)。先收齐再判断是否群聊。"""
    others = {sender for _, sender, is_me, _, _ in records if not is_me}
    is_group = len(others) > 1
    for when, sender, is_me, text, _ in records:
        yield make_chat_event(
            ctx=ctx,
            channel="wechat",
            via=via,
            path=path,
            conversation=conversation,
            sender=sender,
            is_me=is_me,
            when=when,
            text=text,
            peer=None if is_group else (next(iter(others)) if others else conversation),
            is_group=is_group,
        )


class WeChatTxtConnector(Connector):
    name = "wechat_txt"
    channel = "wechat"
    description = "WeChatMsg / 留痕 导出的 txt 聊天记录"
    suffixes = (".txt",)

    def sniff(self, path: Path) -> bool:
        if path.suffix.lower() != ".txt":
            return False
        lines = read_text(path).splitlines()[:80]
        return sum(1 for line in lines if _header(line)) >= 1

    def parse(self, path: Path, ctx: ParseContext) -> Iterator[dict]:
        records: list[tuple] = []
        current: dict | None = None

        def flush() -> None:
            if current is None:
                return
            body = "\n".join(current["lines"]).strip()
            where = f"{path.name}:{current['line']}"
            if not body:
                ctx.skip(where, "正文为空")
                return
            try:
                when = parse_time(current["ts"], ctx.tz)
            except SkipRecord as exc:
                ctx.skip(where, exc.reason)
                return
            records.append((when, current["name"], ctx.config.is_me(current["name"]), body, where))

        for lineno, line in enumerate(read_text(path).splitlines(), start=1):
            head = _header(line)
            if head:
                flush()
                current = {"ts": head[0], "name": head[1], "lines": [], "line": lineno}
            elif current is not None:
                current["lines"].append(line.rstrip())
        flush()
        yield from _emit(records, path.stem, path, ctx, "wechat_txt")


class WeChatCsvConnector(Connector):
    name = "wechat_csv"
    channel = "wechat"
    description = "WeChatMsg / 留痕 导出的 csv（含 StrContent / IsSender 列）"
    suffixes = (".csv",)

    def sniff(self, path: Path) -> bool:
        return path.suffix.lower() == ".csv" and has_any(read_csv_header(path), WECHAT_CSV_MARKERS)

    def parse(self, path: Path, ctx: ParseContext) -> Iterator[dict]:
        _, rows = read_csv_rows(path)
        records: list[tuple] = []
        for index, row in enumerate(rows, start=2):
            where = f"{path.name}:{index}"
            if pick(row, ["Type", "类型"]) not in TEXT_TYPES:
                continue
            text = pick(row, ["StrContent", "content", "内容", "消息内容"])
            if not text:
                ctx.skip(where, "正文为空")
                continue
            is_me = pick(row, ["IsSender", "is_sender", "是否发送"]) in {"1", "true", "True", "是"}
            sender = pick(row, ["Sender", "发送人", "发送者"]) or pick(row, ["Remark", "NickName", "昵称"])
            if is_me or ctx.config.is_me(sender):
                is_me, sender = True, "我"
            elif not sender:
                sender = path.stem
            try:
                when = parse_time(pick(row, ["StrTime", "CreateTime", "time", "时间"]), ctx.tz)
            except SkipRecord as exc:
                ctx.skip(where, exc.reason)
                continue
            records.append((when, sender, is_me, text, where))
        yield from _emit(records, path.stem, path, ctx, "wechat_csv")
