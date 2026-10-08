"""已是 ChannelEvent 形状的 .json / .jsonl（例如其他工具或旧版 sas 的产出）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from .base import Connector, ParseContext, SkipRecord, read_text


class ChannelEventConnector(Connector):
    name = "events"
    channel = "other"
    description = "ChannelEvent 格式的 .json / .jsonl"
    suffixes = (".json", ".jsonl")

    def sniff(self, path: Path) -> bool:
        if path.suffix.lower() not in self.suffixes:
            return False
        head = read_text(path)[:2000]
        return '"channel"' in head and '"content_text"' in head

    def parse(self, path: Path, ctx: ParseContext) -> Iterator[dict]:
        text = read_text(path)
        if path.suffix.lower() == ".jsonl":
            items = []
            for lineno, line in enumerate(text.splitlines(), start=1):
                if line.strip():
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        ctx.skip(f"{path.name}:{lineno}", "不是合法 JSON")
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SkipRecord("不是合法 JSON") from exc
            items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                item.setdefault("consent_tag", ctx.consent_tag)
                yield item
