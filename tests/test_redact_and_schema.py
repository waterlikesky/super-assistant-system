import json
from pathlib import Path

from ingest.pipeline import process_events, validate_event
from ingest.redact import redact_event

ROOT = Path(__file__).resolve().parents[1]


def test_fixtures_validate_and_redact_phone():
    raw = json.loads((ROOT / "fixtures/sample_events/01_email.json").read_text())
    validate_event(raw)
    redacted = redact_event(raw)
    assert "13812345678" not in redacted["content_text"]
    assert "[PHONE]" in redacted["content_text"]
    assert "[TRACKING]" in redacted["content_text"]


def test_otp_confidential_fully_redacted():
    raw = json.loads((ROOT / "fixtures/sample_events/02_sms.json").read_text())
    redacted = redact_event(raw)
    assert "948211" not in redacted["content_text"]
    assert "REDACTED_CONFIDENTIAL" in redacted["content_text"]


def test_process_events_builds_facts():
    events = [
        json.loads(p.read_text())
        for p in sorted((ROOT / "fixtures/sample_events").glob("*.json"))
    ]
    store = process_events(events)
    assert store.chunks
    assert store.facts
