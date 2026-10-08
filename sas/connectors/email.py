"""邮件：单封 .eml 与 .mbox（Gmail Takeout、Thunderbird、Apple Mail 导出）。

全部用标准库 email / mailbox 解析，不自己写 MIME 解析。
- 优先 text/plain，没有时从 HTML 去标签
- 单独一行 `-- `（或 `--`）之后的签名丢弃
- 附件只记文件名与字节数，内容不入库
- 缺 Date / 日期无法解析 / 正文为空：跳过并记录原因
"""

from __future__ import annotations

import mailbox
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from datetime import timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator

from .base import Connector, ParseContext, SkipRecord, is_service_address, short_hash


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        if tag in {"p", "br", "div", "tr", "li", "h1", "h2", "h3"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._chunks.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html)
    parser.close()
    return "".join(parser._chunks)


def strip_signature(text: str) -> str:
    """丢弃 RFC 3676 签名：恰好为 '-- ' 的一行及其之后（很多客户端会吃掉行尾空格，'--' 也算）。"""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line in ("-- ", "--"):
            return "\n".join(lines[:index]).rstrip()
    return text.strip()


SUBJECT_PREFIX_RE = re.compile(r"^\s*((re|fw|fwd|答复|回复|转发)\s*[:：]\s*)+", re.IGNORECASE)


def normalize_subject(subject: str) -> str:
    return SUBJECT_PREFIX_RE.sub("", subject).strip() or "(无主题)"


def _message_id(value: str) -> str:
    return value.strip().strip("<>").strip()


def _thread_id(msg) -> str | None:
    replied = msg.get("in-reply-to")
    if replied:
        token = _message_id(str(replied))
        if token:
            return token
    references = msg.get("references")
    if references:
        for part in str(references).split():
            token = _message_id(part)
            if token:
                return token
    return None


def _participants(msg) -> list[dict]:
    found: list[dict] = []
    for role in ("from", "to", "cc"):
        values = msg.get_all(role, [])
        if not values:
            continue
        for name, addr in getaddresses([str(item) for item in values]):
            handle = addr.strip()
            if "@" not in handle:
                continue
            item: dict = {"role": role, "handle": handle}
            if name:
                item["display_name"] = str(name)
            found.append(item)
    return found


def _body_text(msg) -> str:
    plain = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    try:
        if plain is not None:
            text = plain.get_content()
        elif html_part is not None:
            text = html_to_text(html_part.get_content())
        else:
            text = ""
    except (LookupError, ValueError):
        text = ""
    return strip_signature(text or "")


def _attachments(msg) -> list[dict]:
    if not msg.is_multipart():
        return []
    items: list[dict] = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        items.append({"filename": part.get_filename() or "unnamed", "size": len(payload)})
    return items


def _timestamp(msg) -> str:
    raw_date = msg.get("date")
    if raw_date is None or not str(raw_date).strip():
        raise SkipRecord("缺少 Date")
    try:
        parsed = parsedate_to_datetime(str(raw_date))
    except (TypeError, ValueError, IndexError, OverflowError) as exc:
        raise SkipRecord("无法解析 Date") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _is_outbound(msg, participants: list[dict], ctx: ParseContext) -> bool:
    labels = str(msg.get("x-gmail-labels") or "")
    if re.search(r"(^|,)\s*(Sent|已发送|已发邮件)\s*(,|$)", labels):
        return True
    senders = [p["handle"].lower() for p in participants if p["role"] == "from"]
    mine = {e.lower() for e in ctx.config.me_emails}
    return bool(mine and any(s in mine for s in senders))


def message_to_event(msg, *, ctx: ParseContext, path: Path, via: str, fallback_key: str) -> dict:
    text = _body_text(msg).strip()
    if not text:
        raise SkipRecord("正文为空")
    timestamp = _timestamp(msg)
    raw_id = msg.get("message-id")
    token = _message_id(str(raw_id)) if raw_id else ""
    event_id = f"email:{token}" if token else f"file:{short_hash(fallback_key)}"
    participants = _participants(msg)
    subject = str(msg.get("subject") or "")
    sender = next((p["handle"] for p in participants if p["role"] == "from"), "")
    outbound = _is_outbound(msg, participants, ctx)
    return {
        "id": event_id,
        "channel": "email",
        "direction": "outbound" if outbound else "inbound",
        "timestamp": timestamp,
        "participants": participants,
        "thread_id": _thread_id(msg),
        "conversation": normalize_subject(subject),
        "content_text": text,
        "sensitivity": "confidential" if "验证码" in text else "personal",
        "consent_tag": ctx.consent_tag,
        "raw_ref": str(path.resolve()),
        "metadata": {
            "ingest_via": via,
            "subject": subject,
            "source_name": path.name,
            "attachments": _attachments(msg),
            "is_service": bool(sender) and not outbound and is_service_address(sender),
        },
    }


class EmlConnector(Connector):
    name = "email_eml"
    channel = "email"
    description = "单封 .eml 文件（邮件客户端「另存为」）"
    suffixes = (".eml",)

    def parse(self, path: Path, ctx: ParseContext) -> Iterator[dict]:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise SkipRecord("无法读取") from exc
        try:
            msg = BytesParser(policy=policy.default).parsebytes(data)
        except Exception as exc:
            raise SkipRecord("无法解析邮件") from exc
        root = ctx.root or path.parent
        relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name
        yield message_to_event(msg, ctx=ctx, path=path, via="file_export", fallback_key=relative)


class MboxConnector(Connector):
    name = "email_mbox"
    channel = "email"
    description = ".mbox 邮箱归档（Gmail Takeout / Thunderbird）"
    suffixes = (".mbox",)

    def sniff(self, path: Path) -> bool:
        if path.suffix.lower() == ".mbox":
            return True
        if path.suffix:
            return False
        try:
            with path.open("rb") as fh:
                return fh.read(5) == b"From "
        except OSError:
            return False

    def parse(self, path: Path, ctx: ParseContext) -> Iterator[dict]:
        box = mailbox.mbox(str(path), factory=lambda f: BytesParser(policy=policy.default).parse(f), create=False)
        try:
            for index, msg in enumerate(box):
                if not isinstance(msg, EmailMessage):
                    continue
                key = "|".join(str(msg.get(h) or "") for h in ("from", "date", "subject"))
                try:
                    yield message_to_event(msg, ctx=ctx, path=path, via="mbox", fallback_key=key)
                except SkipRecord as exc:
                    ctx.skip(f"{path.name}#{index}", exc.reason)
        finally:
            box.close()
