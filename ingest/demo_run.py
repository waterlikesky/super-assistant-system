"""M0 demo: load fixtures → validate → redact → naive facts. No cloud calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ingest.pipeline import process_events
from ingest.redact import redact_event

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "sample_events"


def load_fixtures() -> list[dict]:
    events: list[dict] = []
    for path in sorted(FIXTURES.glob("*.json")):
        events.append(json.loads(path.read_text(encoding="utf-8")))
    return events


def main() -> int:
    events = load_fixtures()
    print(f"loaded {len(events)} fixture events from {FIXTURES}")
    for e in events:
        r = redact_event(e)
        print("---")
        print(f"id={r['id']} channel={r['channel']} sensitivity={r['sensitivity']}")
        print(f"redacted_text={r['content_text']!r}")

    store = process_events(events)
    print("===")
    print(f"chunks={len(store.chunks)} facts={len(store.facts)}")
    for fact in store.facts:
        print(
            f"fact: ({fact.subject}) -[{fact.predicate}]-> ({fact.object}) "
            f"sources={fact.source_event_ids} conf={fact.confidence}"
        )

    hits = store.search("meetup")
    print("=== search('meetup') ===")
    print(hits or "(no hits)")
    print("M0 demo OK — no real channels connected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
