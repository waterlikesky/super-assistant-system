from __future__ import annotations

import copy
import re

PHONE_RE = re.compile(r"(?<!\d)(?:\+?86)?1[3-9]\d{9}(?!\d)")
OTP_RE = re.compile(r"(验证码\s*)(\d{4,8})")
TRACKING_RE = re.compile(r"\b[A-Z]{2}\d{9,}[A-Z]{0,3}\b")


def redact_text(text: str, sensitivity: str) -> str:
    out = PHONE_RE.sub("[PHONE]", text)
    out = OTP_RE.sub(r"\1[OTP]", out)
    out = TRACKING_RE.sub("[TRACKING]", out)
    if sensitivity == "confidential":
        # Keep structure but avoid shipping secrets to any LLM path.
        if "验证码" in text or "[OTP]" in out:
            return "[REDACTED_CONFIDENTIAL_OTP_MESSAGE]"
    return out


def redact_event(event: dict) -> dict:
    e = copy.deepcopy(event)
    e["content_text"] = redact_text(e.get("content_text", ""), e.get("sensitivity", "personal"))
    for p in e.get("participants") or []:
        handle = p.get("handle") or ""
        if "@" in handle:
            name, _, domain = handle.partition("@")
            p["handle"] = f"{name[:2]}***@{domain}" if name else handle
    return e
