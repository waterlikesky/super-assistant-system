"""Read a single directory of .eml files into ChannelEvent dicts.

One directory level only. No recursion, no hidden files, no network.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator

from .base import BaseConnector, ConnectorCapability

MAX_EML_BYTES = 25 * 1024 * 1024


class EmlSkip(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


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
    """Drop a RFC 3676 signature: a line that is exactly '-- ' and everything after it."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line == "-- ":
            return "\n".join(lines[:index]).rstrip()
    return text.strip()


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


def _event_id(msg, data: bytes) -> str:
    raw_id = msg.get("message-id")
    if raw_id:
        token = _message_id(str(raw_id))
        if token:
            return f"email:{token}"
    # No Message-ID: key on the message bytes, so the same file keeps its id after a
    # rename and different messages that share a file name do not collide.
    digest = hashlib.sha256(data).hexdigest()[:16]
    return f"file:{digest}"


def _participants(msg) -> list[dict]:
    found: list[dict] = []
    for role, key in (("from", "from"), ("to", "to"), ("cc", "cc")):
        values = msg.get_all(key, [])
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
    if plain is not None:
        text = plain.get_content()
    elif html_part is not None:
        text = html_to_text(html_part.get_content())
    else:
        text = ""
    return strip_signature(text or "")


def _attachments(msg) -> list[dict]:
    if not msg.is_multipart():
        return []
    items: list[dict] = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        items.append(
            {
                "filename": part.get_filename() or "unnamed",
                "size": len(payload),
            }
        )
    return items


def _timestamp(msg) -> str:
    raw_date = msg.get("date")
    if raw_date is None or not str(raw_date).strip():
        raise EmlSkip("缺少 Date")
    try:
        parsed = parsedate_to_datetime(str(raw_date))
    except (TypeError, ValueError, IndexError, OverflowError) as exc:
        raise EmlSkip("无法解析 Date") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def parse_eml(path: Path, root: Path, consent_tag: str) -> dict:
    if path.is_symlink():
        raise EmlSkip("符号链接，未读取")
    try:
        if path.stat().st_size > MAX_EML_BYTES:
            raise EmlSkip("文件过大")
        data = path.read_bytes()
    except OSError as exc:
        raise EmlSkip("无法读取") from exc
    try:
        msg = BytesParser(policy=policy.default).parsebytes(data)
    except Exception as exc:
        raise EmlSkip("无法解析邮件") from exc

    text = _body_text(msg).strip()
    if not text:
        raise EmlSkip("正文为空")
    sensitivity = "confidential" if "验证码" in text else "personal"
    subject = str(msg.get("subject") or "")
    return {
        "id": _event_id(msg, data),
        "channel": "email",
        "direction": "inbound",
        "timestamp": _timestamp(msg),
        "participants": _participants(msg),
        "thread_id": _thread_id(msg),
        "content_text": text,
        "sensitivity": sensitivity,
        "consent_tag": consent_tag,
        "raw_ref": str(path.resolve()),
        "metadata": {
            "ingest_via": "file_export",
            "subject": subject,
            "source_name": path.name,
            "attachments": _attachments(msg),
        },
    }


def list_eml_files(root: Path) -> list[Path]:
    files = [
        path
        for path in root.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() == ".eml"
    ]
    return sorted(files, key=lambda path: path.name)


@dataclass
class ScanResult:
    events: list[dict]
    skipped: list[tuple[str, str]]


def scan_eml_dir(root: Path, consent_tag: str) -> ScanResult:
    events: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for path in list_eml_files(root):
        try:
            events.append(parse_eml(path, root, consent_tag))
        except EmlSkip as exc:
            skipped.append((path.name, exc.reason))
    return ScanResult(events=events, skipped=skipped)


class FileExportConnector(BaseConnector):
    capability = ConnectorCapability(
        name="file_export",
        read_only=True,
        outbound=False,
        enabled_by_default=True,
        risk_notes="Only reads one directory of .eml files the user points at. Redact before any model call.",
    )

    def __init__(self, path: str | Path | None = None, consent_tag: str | None = None) -> None:
        self.path = Path(path) if path else None
        self.consent_tag = consent_tag.strip() if consent_tag else None
        self.skipped: list[tuple[str, str]] = []

    def iter_events(self) -> Iterator[dict]:
        if self.path is None:
            return iter(())
        if not self.consent_tag:
            raise ValueError("缺少 consent_tag")
        if not self.path.exists():
            raise FileNotFoundError(f"目录不存在: {self.path}")
        if not self.path.is_dir():
            raise NotADirectoryError(f"需要目录: {self.path}")
        result = scan_eml_dir(self.path, self.consent_tag)
        self.skipped = result.skipped
        return iter(result.events)
