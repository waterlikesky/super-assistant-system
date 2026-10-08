"""入库前脱敏。规则只做确定性替换，不依赖模型。

覆盖：验证码（含验证码的 confidential 消息整条替换）、身份证、银行卡（Luhn 校验）、
手机号、快递单号、邮箱本地部分。
"""

from __future__ import annotations

import copy
import hashlib
import re

CONFIDENTIAL_PLACEHOLDER = "[REDACTED_CONFIDENTIAL_OTP_MESSAGE]"

OTP_WORDS = r"(?:验证码|校验码|动态码|动态密码|短信码|确认码|取件码)"
OTP_RE = re.compile(rf"({OTP_WORDS}[^\d\n]{{0,8}}?)(\d{{4,8}})(?!\d)")
OTP_EN_RE = re.compile(r"(?i)(\b(?:code|otp|passcode)\b\s*(?:is|:|：)?\s*)(\d{4,8})\b")
ID_CARD_RE = re.compile(
    r"(?<![\dA-Za-z])[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![\dA-Za-z])"
)
CARD_CANDIDATE_RE = re.compile(r"(?<![\d-])(?:\d[ -]?){14,18}\d(?![\d-])")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d(?:[- ]?\d{4}){2}(?!\d)")
TRACKING_RE = re.compile(r"\b[A-Z]{2}\d{9,}[A-Z]{0,3}\b")
EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _mask_card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if 15 <= len(digits) <= 19 and _luhn_ok(digits):
        return "[BANK_CARD]"
    return match.group(0)


def _mask_email(match: re.Match[str]) -> str:
    return f"{match.group(1)[:2]}***@{match.group(2)}"


def has_otp(text: str) -> bool:
    return bool(OTP_RE.search(text) or OTP_EN_RE.search(text) or re.search(OTP_WORDS, text))


def classify_sensitivity(text: str, default: str = "personal") -> str:
    """含验证码类内容的一律升为 confidential。"""
    if OTP_RE.search(text) or OTP_EN_RE.search(text):
        return "confidential"
    return default


def redact_text(text: str, sensitivity: str = "personal") -> str:
    if not text:
        return text
    if sensitivity == "confidential" and has_otp(text):
        return CONFIDENTIAL_PLACEHOLDER
    out = OTP_RE.sub(r"\1[OTP]", text)
    out = OTP_EN_RE.sub(r"\1[OTP]", out)
    out = ID_CARD_RE.sub("[ID_CARD]", out)
    out = CARD_CANDIDATE_RE.sub(_mask_card, out)
    out = PHONE_RE.sub("[PHONE]", out)
    out = TRACKING_RE.sub("[TRACKING]", out)
    out = EMAIL_RE.sub(_mask_email, out)
    return out


def mask_handle(handle: str) -> str:
    """参与方标识：邮箱打码本地部分；电话号码换成不可逆短哈希，保证同一号码仍可聚合。"""
    if "@" in handle:
        name, _, domain = handle.partition("@")
        return f"{name[:2]}***@{domain}" if name else handle
    digits = re.sub(r"\D", "", handle)
    if len(digits) >= 7 and len(digits) >= len(handle.replace(" ", "")) - 2:
        if digits.startswith("86") and len(digits) == 13:
            digits = digits[2:]
        return f"tel:{hashlib.sha256(digits.encode()).hexdigest()[:12]}"
    return redact_text(handle)


def redact_event(event: dict) -> dict:
    e = copy.deepcopy(event)
    sensitivity = e.get("sensitivity", "personal")
    e["content_text"] = redact_text(e.get("content_text", ""), sensitivity)
    if isinstance(e.get("conversation"), str):
        e["conversation"] = redact_text(e["conversation"])
    for participant in e.get("participants") or []:
        handle = participant.get("handle") or ""
        if handle and not handle.startswith("tel:"):
            participant["handle"] = mask_handle(handle)
        display_name = participant.get("display_name")
        if isinstance(display_name, str):
            participant["display_name"] = redact_text(display_name, sensitivity)
    metadata = e.get("metadata")
    if isinstance(metadata, dict):
        subject = metadata.get("subject")
        if isinstance(subject, str):
            metadata["subject"] = redact_text(subject, sensitivity)
        for attachment in metadata.get("attachments") or []:
            filename = attachment.get("filename")
            if isinstance(filename, str):
                attachment["filename"] = redact_text(filename, sensitivity)
    return e
