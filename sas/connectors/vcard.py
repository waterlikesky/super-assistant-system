"""通讯录：vCard（.vcf，iPhone / Android / Google Contacts / Outlook 导出，3.0 与 4.0）。

不产出消息，只产出联系人，用于**人物别名合并**：同一个人在微信备注、短信通讯录名、邮件显示名不同，
通过 vCard 的姓名 / 昵称 / 电话 / 邮箱把他们并成一个人。
入库前同样脱敏：电话只存不可逆哈希（与短信 connector 的 handle 相同算法），邮箱只存打码形式。
"""

from __future__ import annotations

import quopri
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from sas.redact import mask_handle

from .base import Connector, SkipRecord, read_text


@dataclass
class Contact:
    name: str
    aliases: set[str] = field(default_factory=set)
    handles: set[str] = field(default_factory=set)  # tel:<hash> / 打码邮箱
    org: str = ""


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif lines and lines[-1].endswith("=") and "QUOTED-PRINTABLE" in lines[-1].upper():
            lines[-1] = lines[-1][:-1] + raw  # QP 软换行
        else:
            lines.append(raw)
    return lines


def _value(params: str, value: str) -> str:
    if "QUOTED-PRINTABLE" in params.upper():
        charset = (re.search(r"CHARSET=([\w-]+)", params, re.I) or [None, "utf-8"])[1]
        value = quopri.decodestring(value.encode()).decode(charset, errors="replace")
    return value.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()


def parse_vcards(text: str) -> Iterator[Contact]:
    card: dict[str, list[tuple[str, str]]] | None = None
    for line in _unfold(text):
        upper = line.upper()
        if upper.startswith("BEGIN:VCARD"):
            card = {}
            continue
        if upper.startswith("END:VCARD"):
            if card is not None:
                contact = _to_contact(card)
                if contact:
                    yield contact
            card = None
            continue
        if card is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        prop, _, params = head.partition(";")
        prop = prop.split(".")[-1].upper()  # item1.TEL → TEL
        card.setdefault(prop, []).append((params, _value(params, value)))


def _to_contact(card: dict[str, list[tuple[str, str]]]) -> Contact | None:
    fn = next((v for _, v in card.get("FN", []) if v), "")
    n_forms = set()
    for _, v in card.get("N", []):
        parts = [p.strip() for p in v.split(";")]
        family, given = (parts + ["", ""])[:2]
        if family or given:
            n_forms |= {family + given, f"{given} {family}".strip()}
    name = fn or next(iter(sorted(n_forms)), "")
    if not name:
        return None
    aliases = {name, *n_forms}
    for _, v in card.get("NICKNAME", []):
        aliases |= {a.strip() for a in v.split(",") if a.strip()}
    handles = {mask_handle(v) for _, v in card.get("TEL", []) if re.sub(r"\D", "", v)}
    handles |= {mask_handle(v.lower()) for _, v in card.get("EMAIL", []) if "@" in v}
    org = next((v.split(";")[0] for _, v in card.get("ORG", []) if v), "")
    return Contact(name=name, aliases={a for a in aliases if a}, handles=handles, org=org)


class VCardConnector(Connector):
    name = "vcard"
    channel = "other"
    kind = "contacts"
    description = "通讯录 vCard（.vcf），用于人物别名合并"
    suffixes = (".vcf", ".vcard")

    def parse(self, path: Path, ctx) -> Iterator[dict]:
        return iter(())

    def parse_contacts(self, path: Path) -> list[Contact]:
        contacts = list(parse_vcards(read_text(path)))
        if not contacts:
            raise SkipRecord("没有可识别的 vCard")
        return contacts
