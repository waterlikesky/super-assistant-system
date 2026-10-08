"""短信：SMS Backup & Restore（Android）导出的 xml，以及通用 csv。

xml: <smses><sms address= date=(毫秒) type=(1 收 / 2 发) body= contact_name= />…
     <mms date= msg_box=(1 收 / 2 发) address= contact_name=><parts><part ct="text/plain" text=…/></parts></mms>
csv: 号码/address、内容/body、时间/date、类型/type（1/2、收/发、inbox/sent）、联系人/contact_name
号码在入库前换成不可逆哈希；显示名用通讯录名或「尾号1234」。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator

from sas.redact import mask_handle

from .base import (
    Connector,
    ParseContext,
    SkipRecord,
    has_any,
    is_service_address,
    make_chat_event,
    parse_time,
    phone_tail,
    pick,
    read_csv_header,
    read_csv_rows,
)

ADDRESS = ["address", "phone", "number", "号码", "手机号", "电话", "联系人号码"]
BODY = ["body", "content", "text", "message", "内容", "短信内容"]
TIME = ["date", "time", "datetime", "时间", "日期"]
KIND = ["type", "direction", "msg_box", "类型", "方向"]
NAME = ["contact_name", "name", "contact", "联系人", "姓名"]
OUT_VALUES = {"2", "sent", "outbox", "outgoing", "发送", "已发送", "发", "out"}


def _sms_event(ctx: ParseContext, path: Path, *, address: str, name: str, when, text: str, outbound: bool, via: str) -> dict:
    display = name if name and name not in {"(Unknown)", "null", "未知"} else phone_tail(address)
    service = is_service_address(address)
    return make_chat_event(
        ctx=ctx,
        channel="sms",
        via=via,
        path=path,
        conversation=display,
        sender=display,
        is_me=outbound,
        when=when,
        text=text,
        peer=display,
        sender_handle=None if outbound else mask_handle(address),
        extra={"is_service": service and not outbound},
    )


class SmsXmlConnector(Connector):
    name = "sms_xml"
    channel = "sms"
    description = "SMS Backup & Restore 导出的 xml"
    suffixes = (".xml",)

    def sniff(self, path: Path) -> bool:
        if path.suffix.lower() != ".xml":
            return False
        try:
            head = path.read_bytes()[:2048].decode("utf-8", errors="ignore")
        except OSError:
            return False
        return "<smses" in head

    def parse(self, path: Path, ctx: ParseContext) -> Iterator[dict]:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            raise SkipRecord(f"xml 无法解析: {exc}") from exc
        for index, node in enumerate(root, start=1):
            where = f"{path.name}#{index}"
            if node.tag == "sms":
                text = (node.get("body") or "").strip()
                outbound = node.get("type") == "2"
            elif node.tag == "mms":
                parts = [p.get("text") or "" for p in node.iter("part") if p.get("ct") == "text/plain"]
                text = "\n".join(t for t in parts if t).strip()
                outbound = node.get("msg_box") == "2"
            else:
                continue
            if not text:
                ctx.skip(where, "正文为空")
                continue
            try:
                when = parse_time(node.get("date"), ctx.tz)
            except SkipRecord as exc:
                ctx.skip(where, exc.reason)
                continue
            address = (node.get("address") or "").split("~")[0]
            yield _sms_event(
                ctx, path, address=address, name=node.get("contact_name") or "", when=when,
                text=text, outbound=outbound, via="sms_xml",
            )


class SmsCsvConnector(Connector):
    name = "sms_csv"
    channel = "sms"
    description = "通用短信 csv（号码 / 内容 / 时间 / 类型 / 联系人）"
    suffixes = (".csv",)

    def sniff(self, path: Path) -> bool:
        if path.suffix.lower() != ".csv":
            return False
        header = read_csv_header(path)
        return has_any(header, ADDRESS) and has_any(header, BODY)

    def parse(self, path: Path, ctx: ParseContext) -> Iterator[dict]:
        _, rows = read_csv_rows(path)
        for index, row in enumerate(rows, start=2):
            where = f"{path.name}:{index}"
            text = pick(row, BODY)
            if not text:
                ctx.skip(where, "正文为空")
                continue
            try:
                when = parse_time(pick(row, TIME), ctx.tz)
            except SkipRecord as exc:
                ctx.skip(where, exc.reason)
                continue
            yield _sms_event(
                ctx, path, address=pick(row, ADDRESS), name=pick(row, NAME), when=when, text=text,
                outbound=pick(row, KIND).lower() in OUT_VALUES, via="sms_csv",
            )
