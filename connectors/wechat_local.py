"""Optional wechat local-vault reader. DISABLED by default.

See docs/problems/channel-ingestion-pitfalls.md and SCYS posts
82255448142454542 / 45544211552415428. Version-fragile; ToS risk.
"""

from __future__ import annotations

import os
from typing import Iterator

from .base import BaseConnector, ConnectorCapability


class WechatLocalConnector(BaseConnector):
    capability = ConnectorCapability(
        name="wechat_local",
        read_only=True,
        outbound=False,
        enabled_by_default=False,
        risk_notes=(
            "Requires pinned WeChat version / local decrypt skill; "
            "DMCA and account risk; never enable outbound here."
        ),
    )

    def __init__(self) -> None:
        flag = os.getenv("WECHAT_CONNECTOR_ENABLED", "false").lower()
        self._enabled = flag in {"1", "true", "yes"}

    def iter_events(self) -> Iterator[dict]:
        if not self._enabled:
            raise RuntimeError(
                "WechatLocalConnector is disabled. Set WECHAT_CONNECTOR_ENABLED=true "
                "only after reading docs/problems/channel-ingestion-pitfalls.md"
            )
        raise NotImplementedError(
            "Wrap a local decrypt skill in M2W; do not vendor risky binaries into this repo."
        )
