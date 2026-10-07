from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ingest.redact import redact_event
from memory.store import Fact, InMemoryStore

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "channel_event.schema.json"


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_event(event: dict, schema: dict | None = None) -> None:
    schema = schema or load_schema()
    Draft202012Validator(schema).validate(event)


def naive_extract_facts(event: dict) -> list[Fact]:
    """Rule-based demo extractor (not an LLM). Replace in M2/M3."""
    facts: list[Fact] = []
    text = event.get("content_text", "")
    eid = event["id"]
    if "meet" in text.lower() or "见面" in text or "约" in text:
        facts.append(
            Fact(
                subject="user",
                predicate="has_pending_meetup_mention",
                object=text[:120],
                source_event_ids=[eid],
                confidence=0.4,
            )
        )
    if event.get("channel") == "wechat" and "项目" in text:
        facts.append(
            Fact(
                subject="project",
                predicate="mentioned_in_wechat",
                object="schedule_or_contract_hint",
                source_event_ids=[eid],
                confidence=0.35,
            )
        )
    if event.get("sensitivity") == "confidential":
        facts.append(
            Fact(
                subject="security",
                predicate="received_sensitive_message",
                object="otp_or_confidential",
                source_event_ids=[eid],
                confidence=0.9,
            )
        )
    return facts


def process_events(events: list[dict], store: InMemoryStore | None = None) -> InMemoryStore:
    store = store or InMemoryStore()
    schema = load_schema()
    for raw in events:
        validate_event(raw, schema)
        redacted = redact_event(raw)
        store.upsert_chunk(
            {
                "id": redacted["id"],
                "channel": redacted["channel"],
                "text": redacted["content_text"],
                "timestamp": redacted["timestamp"],
            }
        )
        for fact in naive_extract_facts(redacted):
            store.upsert_fact(fact)
    return store
