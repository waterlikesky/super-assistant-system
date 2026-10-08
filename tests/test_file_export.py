import json
import socket
import subprocess
from email.message import EmailMessage
from pathlib import Path

import pytest
from jsonschema import ValidationError

from connectors.email_oauth import EmailOAuthConnector
from connectors.file_export import parse_eml
from connectors.wechat_local import WechatLocalConnector
from ingest.file_export_run import main
from ingest.pipeline import validate_event

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "sample_exports" / "mail"
PHONE = "13900001111"
OTP = "948211"
BODY_EMAIL = "carol@example.com"
SECRET_EMAIL = "lin.secret@example.com"


def test_fixture_directory_writes_redacted_jsonl(tmp_path):
    out = tmp_path / "events.jsonl"
    code = main(
        [
            "--input",
            str(FIXTURE),
            "--out",
            str(out),
            "--consent-tag",
            "fixture-m1",
        ]
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 2
    blob = "\n".join(lines)
    assert PHONE not in blob
    assert OTP not in blob
    assert BODY_EMAIL not in blob
    assert SECRET_EMAIL not in blob
    assert "Sent from my phone" not in blob
    assert "HTML should not win" not in blob
    assert "do-not-inline-this-token" not in blob
    assert "UNIQUE_NESTED_SECRET" not in blob
    assert "UNIQUE_DOT_SECRET" not in blob
    assert "ca***@example.com" in blob

    events = [json.loads(line) for line in lines]
    for event in events:
        validate_event(event)
        assert event["channel"] == "email"
        assert event["direction"] == "inbound"
        assert event["consent_tag"] == "fixture-m1"
        assert event["metadata"]["ingest_via"] == "file_export"
        assert event["raw_ref"]

    by_id = {event["id"]: event for event in events}
    thursday = by_id["email:meet-thursday@example.com"]
    assert thursday["thread_id"] == "thread-root@example.com"
    assert thursday["timestamp"] == "2026-10-06T09:15:00-07:00"
    assert thursday["metadata"]["attachments"][0]["filename"] == "notes.txt"
    assert thursday["metadata"]["attachments"][0]["size"] > 0
    assert any(item["role"] == "from" and item["handle"] == "al***@example.com" for item in thursday["participants"])

    otp = by_id["email:otp-1@example.com"]
    assert otp["sensitivity"] == "confidential"
    assert otp["content_text"] == "[REDACTED_CONFIDENTIAL_OTP_MESSAGE]"


def test_ids_stay_stable(tmp_path):
    first = tmp_path / "a.jsonl"
    second = tmp_path / "b.jsonl"
    args = ["--input", str(FIXTURE), "--consent-tag", "fixture-m1"]
    assert main([*args, "--out", str(first)]) == 0
    assert main([*args, "--out", str(second)]) == 0
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_bad_file_is_skipped_and_named(tmp_path, capsys):
    out = tmp_path / "events.jsonl"
    assert main(["--input", str(FIXTURE), "--out", str(out), "--consent-tag", "fixture-m1"]) == 0
    captured = capsys.readouterr()
    assert "skipped bad-date.eml: 无法解析 Date" in captured.out
    assert out.exists()


def test_missing_consent_writes_nothing(tmp_path):
    out = tmp_path / "events.jsonl"
    with pytest.raises(SystemExit) as caught:
        main(["--input", str(FIXTURE), "--out", str(out)])
    assert caught.value.code != 0
    assert not out.exists()


def test_blank_consent_writes_nothing(tmp_path, capsys):
    out = tmp_path / "events.jsonl"
    code = main(["--input", str(FIXTURE), "--out", str(out), "--consent-tag", "   "])
    assert code == 2
    assert not out.exists()
    assert "consent_tag" in capsys.readouterr().err


def test_missing_directory_writes_nothing(tmp_path, capsys):
    missing = tmp_path / "nope"
    out = tmp_path / "events.jsonl"
    code = main(["--input", str(missing), "--out", str(out), "--consent-tag", "fixture-m1"])
    assert code == 1
    assert not out.exists()
    assert "目录不存在" in capsys.readouterr().err


def test_empty_directory_writes_nothing(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    out = tmp_path / "events.jsonl"
    code = main(["--input", str(empty), "--out", str(out), "--consent-tag", "fixture-m1"])
    assert code == 1
    assert not out.exists()
    assert "没有 .eml" in capsys.readouterr().err


def test_all_files_invalid_writes_nothing(tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "bad-date.eml").write_bytes((FIXTURE / "bad-date.eml").read_bytes())
    out = tmp_path / "events.jsonl"
    assert main(["--input", str(folder), "--out", str(out), "--consent-tag", "fixture-m1"]) == 1
    assert not out.exists()


def test_html_only_and_empty_body(tmp_path):
    html_path = tmp_path / "html.eml"
    message = EmailMessage()
    message["From"] = "Ada <ada@example.com>"
    message["To"] = "Me <me@example.com>"
    message["Date"] = "Wed, 07 Oct 2026 01:02:03 +0000"
    message["Message-ID"] = "<html-only@example.com>"
    message.set_content("<p>Hello <b>there</b></p><p>Next</p>", subtype="html")
    html_path.write_bytes(message.as_bytes())
    event = parse_eml(html_path, tmp_path, "fixture-m1")
    assert "Hello" in event["content_text"]
    assert "there" in event["content_text"]
    assert "<b>" not in event["content_text"]
    validate_event(event)

    empty_path = tmp_path / "empty.eml"
    empty = EmailMessage()
    empty["From"] = "Ada <ada@example.com>"
    empty["Date"] = "Wed, 07 Oct 2026 01:02:03 +0000"
    empty["Message-ID"] = "<empty@example.com>"
    empty.set_content("   \n")
    empty_path.write_bytes(empty.as_bytes())
    with pytest.raises(Exception, match="正文为空"):
        parse_eml(empty_path, tmp_path, "fixture-m1")


def test_schema_rejects_illegal_event():
    with pytest.raises(ValidationError):
        validate_event({"id": "x"})


def test_other_connectors_stay_closed(monkeypatch):
    monkeypatch.delenv("WECHAT_CONNECTOR_ENABLED", raising=False)
    with pytest.raises(RuntimeError):
        WechatLocalConnector().iter_events()
    with pytest.raises(NotImplementedError):
        EmailOAuthConnector().iter_events()


def test_fixture_run_does_not_open_sockets(tmp_path, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("意外的网络连接")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    out = tmp_path / "events.jsonl"
    assert main(["--input", str(FIXTURE), "--out", str(out), "--consent-tag", "fixture-m1"]) == 0


def test_processed_output_is_gitignored():
    result = subprocess.run(
        ["git", "check-ignore", "-q", "data/processed/events.jsonl"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0
