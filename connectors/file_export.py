"""M1 target: parse user-exported files into ChannelEvent dicts.

M0: placeholder that yields nothing until implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .base import BaseConnector, ConnectorCapability


class FileExportConnector(BaseConnector):
    capability = ConnectorCapability(
        name="file_export",
        read_only=True,
        outbound=False,
        enabled_by_default=True,
        risk_notes="Only reads paths the user points at; still redact before LLM.",
    )

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None

    def iter_events(self) -> Iterator[dict]:
        # M1: implement mbox/eml/csv parsers.
        if self.path is None:
            return iter(())
        raise NotImplementedError(
            "FileExportConnector parsing lands in M1. Use fixtures + ingest.demo_run for M0."
        )
