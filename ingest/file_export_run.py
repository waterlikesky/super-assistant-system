"""Read one directory of .eml files, redact, and write local JSONL.

No mailbox login and no network. Each run overwrites --out.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import ValidationError

from connectors.file_export import FileExportConnector
from ingest.pipeline import validate_event
from ingest.redact import redact_event


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把一层 .eml 目录收成脱敏 ChannelEvent JSONL")
    parser.add_argument("--input", required=True, help="只含 .eml 的一层目录")
    parser.add_argument("--out", required=True, help="输出 JSONL；每次覆盖")
    parser.add_argument("--consent-tag", required=True, help="这批导出的同意标记")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    consent = args.consent_tag.strip()
    if not consent:
        print("缺少 consent_tag", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    connector = FileExportConnector(args.input, consent)
    try:
        events = list(connector.iter_events())
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(exc, file=sys.stderr)
        return 1

    for name, reason in connector.skipped:
        print(f"skipped {name}: {reason}")

    if not events and not connector.skipped:
        print(f"目录里没有 .eml: {args.input}", file=sys.stderr)
        return 1

    written: list[dict] = []
    for event in events:
        source_name = event.get("metadata", {}).get("source_name", event.get("id", "unknown"))
        try:
            validate_event(event)
            redacted = redact_event(event)
            validate_event(redacted)
        except ValidationError as exc:
            print(f"skipped {source_name}: 不符合 schema ({exc.message})")
            continue
        written.append(redacted)

    if not written:
        print("没有可写入的事件", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event, ensure_ascii=False) for event in written]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(written)} events to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
