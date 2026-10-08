"""邮件 connector（.eml 目录 + .mbox）。由 M1 的 tests/test_file_export.py 迁移而来，断言保持不变。"""

from email.message import EmailMessage

import pytest

from sas.connectors import ParseContext, SkipRecord, detect, resolve_source
from sas.connectors.email import EmlConnector, MboxConnector
from sas.ingest import ingest_path, prepare
from sas.schema import ValidationError, validate_event

from .conftest import EML_CASES, EXPORTS

PHONE = "13900001111"
OTP = "948211"
BODY_EMAIL = "carol@example.com"
SECRET_EMAIL = "lin.secret@example.com"


def _dump(store) -> str:
    return "\n".join(str(r) for r in store.query("select * from events"))


def test_eml_directory_is_redacted_before_storage(config, store, memory):
    report = ingest_path(EML_CASES, store=store, memory=memory, config=config, source="email", consent_tag="fixture-m1")
    assert report.new == 2
    blob = _dump(store) + config.db_path.read_bytes().decode("utf-8", errors="ignore")
    for secret in (PHONE, OTP, BODY_EMAIL, SECRET_EMAIL, "Sent from my phone", "HTML should not win",
                   "do-not-inline-this-token", "UNIQUE_NESTED_SECRET", "UNIQUE_DOT_SECRET"):
        assert secret not in blob, secret
    assert "ca***@example.com" in blob

    rows = {r["id"]: r for r in store.query("select * from events")}
    thursday = rows["email:meet-thursday@example.com"]
    assert thursday["thread_id"] == "thread-root@example.com"
    assert thursday["ts"].startswith("2026-10-07T00:15:00+08:00")  # 原 2026-10-06 09:15 -07:00，统一到东八区
    assert thursday["consent_tag"] == "fixture-m1"
    assert '"filename": "notes.txt"' in thursday["metadata"]
    assert '"handle": "al***@example.com"' in thursday["participants"]
    otp = rows["email:otp-1@example.com"]
    assert otp["sensitivity"] == "confidential"
    assert otp["content_text"] == "[REDACTED_CONFIDENTIAL_OTP_MESSAGE]"


def test_bad_file_is_skipped_and_named(config, store, memory):
    report = ingest_path(EML_CASES, store=store, memory=memory, config=config)
    assert ("bad-date.eml", "无法解析 Date") in report.skipped


def test_hidden_files_always_skipped_nested_only_with_recursive(config, store, memory):
    ingest_path(EML_CASES, store=store, memory=memory, config=config)
    assert not store.query("select 1 from events where content_text like '%NESTED%'")
    ingest_path(EML_CASES, store=store, memory=memory, config=config, recursive=True)
    assert store.query("select 1 from events where content_text like '%NESTED%'")
    assert not store.query("select 1 from events where content_text like '%DOT_SECRET%'")


def test_parse_events_validate_against_schema(config):
    ctx = ParseContext(config=config, consent_tag="t", root=EML_CASES)
    event = next(EmlConnector().parse(EML_CASES / "thursday.eml", ctx))
    validate_event(event)
    assert event["channel"] == "email" and event["direction"] == "inbound"
    assert event["metadata"]["ingest_via"] == "file_export"
    assert event["raw_ref"]
    validate_event(prepare(event))


def test_html_only_and_empty_body(tmp_path, config):
    ctx = ParseContext(config=config, consent_tag="t", root=tmp_path)
    message = EmailMessage()
    message["From"] = "Ada <ada@example.com>"
    message["Date"] = "Wed, 07 Oct 2026 01:02:03 +0000"
    message["Message-ID"] = "<html-only@example.com>"
    message.set_content("<p>Hello <b>there</b></p><p>Next</p>", subtype="html")
    (tmp_path / "html.eml").write_bytes(message.as_bytes())
    event = next(EmlConnector().parse(tmp_path / "html.eml", ctx))
    assert "Hello" in event["content_text"] and "<b>" not in event["content_text"]

    empty = EmailMessage()
    empty["From"] = "Ada <ada@example.com>"
    empty["Date"] = "Wed, 07 Oct 2026 01:02:03 +0000"
    empty.set_content("   \n")
    (tmp_path / "empty.eml").write_bytes(empty.as_bytes())
    with pytest.raises(SkipRecord, match="正文为空"):
        next(EmlConnector().parse(tmp_path / "empty.eml", ctx))


def test_mbox_direction_and_service_detection(config):
    ctx = ParseContext(config=config, consent_tag="t")
    events = list(MboxConnector().parse(EXPORTS / "email" / "archive.mbox", ctx))
    assert [e["direction"] for e in events] == ["inbound", "outbound", "inbound"]  # X-Gmail-Labels: Sent
    assert events[1]["thread_id"] == "q4-1@example.com"
    assert events[1]["conversation"] == "Q4 预算"  # 去掉 Re:
    assert events[2]["metadata"]["is_service"] is True


def test_me_emails_marks_outbound(tmp_path):
    from sas.config import Config

    cfg = Config.load(env={"SAS_ME_EMAILS": "alice@example.com"}, db_path=tmp_path / "x.db")
    ctx = ParseContext(config=cfg, consent_tag="t", root=EML_CASES)
    event = next(EmlConnector().parse(EML_CASES / "thursday.eml", ctx))
    assert event["direction"] == "outbound"


def test_detect_and_source_alias():
    assert detect(EXPORTS / "email" / "archive.mbox", resolve_source("auto")).name == "email_mbox"
    assert [c.name for c in resolve_source("mail")] == ["email_eml", "email_mbox"]
    with pytest.raises(KeyError):
        resolve_source("telegram")


def test_schema_rejects_illegal_event():
    with pytest.raises(ValidationError):
        validate_event({"id": "x"})
