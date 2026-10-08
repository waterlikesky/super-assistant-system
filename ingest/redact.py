from __future__ import annotations

import copy
import re

PHONE_RE = re.compile(r"(?<!\d)(?:\+?86)?1[3-9]\d{9}(?!\d)")
OTP_RE = re.compile(r"(验证码\s*)(\d{4,8})")
TRACKING_RE = re.compile(r"\b[A-Z]{2}\d{9,}[A-Z]{0,3}\b")
EMAIL_RE = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)


def _mask_email(match: re.Match[str]) -> str:
    local = match.group(1)
    domain = match.group(2)
    return f"{local[:2]}***@{domain}"


def redact_text(text: str, sensitivity: str) -> str:
    out = PHONE_RE.sub("[PHONE]", text)
    out = OTP_RE.sub(r"\1[OTP]", out)
    out = TRACKING_RE.sub("[TRACKING]", out)
    out = EMAIL_RE.sub(_mask_email, out)
    if sensitivity == "confidential":
        # Keep structure but avoid shipping secrets to any LLM path.
        if "验证码" in text or "[OTP]" in out:
            return "[REDACTED_CONFIDENTIAL_OTP_MESSAGE]"
    return out


def redact_event(event: dict) -> dict:
    e = copy.deepcopy(event)
    sensitivity = e.get("sensitivity", "personal")
    e["content_text"] = redact_text(e.get("content_text", ""), sensitivity)
    for participant in e.get("participants") or []:
        handle = participant.get("handle") or ""
        if "@" in handle:
            name, _, domain = handle.partition("@")
            participant["handle"] = f"{name[:2]}***@{domain}" if name else handle
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
