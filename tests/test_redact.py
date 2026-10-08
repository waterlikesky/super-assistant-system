import json

import pytest

from sas.redact import CONFIDENTIAL_PLACEHOLDER, classify_sensitivity, mask_handle, redact_event, redact_text

from .conftest import ROOT


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("电话 13812345678", "电话 [PHONE]"),
        ("电话 +86 138-1234-5678 ok", "电话 [PHONE] ok"),
        ("电话 138 1234 5678", "电话 [PHONE]"),
        ("身份证 11010119900307123X 请收好", "身份证 [ID_CARD] 请收好"),
        ("卡号 6225 8812 3456 7898", "卡号 [BANK_CARD]"),
        ("卡号 6225881234567898", "卡号 [BANK_CARD]"),
        ("单号 SF1234567890CN", "单号 [TRACKING]"),
        ("邮箱 carol@example.com", "邮箱 ca***@example.com"),
        ("验证码是 482913 哦", "验证码是 [OTP] 哦"),
        ("Your code is 123456", "Your code is [OTP]"),
    ],
)
def test_redact_patterns(raw, expected):
    assert redact_text(raw) == expected


def test_non_luhn_long_number_is_kept():
    # 订单号之类的 16 位数字不该被当成银行卡
    assert redact_text("订单 1234567812345678") == "订单 1234567812345678"


def test_amounts_and_dates_untouched():
    text = "账单 3,210.00 元，2026-10-06 到期，房间 1203"
    assert redact_text(text) == text


def test_otp_messages_become_confidential_and_fully_replaced():
    text = "【银行】验证码 482913，5分钟内有效"
    assert classify_sensitivity(text) == "confidential"
    assert redact_text(text, "confidential") == CONFIDENTIAL_PLACEHOLDER
    assert classify_sensitivity("周六见") == "personal"


def test_mask_handle_hashes_phone_consistently():
    a = mask_handle("+86 137 0000 1111")
    b = mask_handle("13700001111")
    assert a == b and a.startswith("tel:") and "1111" not in a
    assert mask_handle("alice@example.com") == "al***@example.com"


def test_redact_event_covers_fields():
    raw = json.loads((ROOT / "fixtures/events/01_email.json").read_text())
    red = redact_event(raw)
    assert "13812345678" not in red["content_text"] and "[PHONE]" in red["content_text"]
    assert "[TRACKING]" in red["content_text"]
    assert red["participants"][0]["handle"] == "al***@example.com"
    assert raw["participants"][0]["handle"] == "alice@example.com"  # 不改原对象
