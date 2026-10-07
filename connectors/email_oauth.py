"""M1 target: OAuth/IMAP read-only email ingest. Not implemented in M0."""

from __future__ import annotations

from typing import Iterator

from .base import BaseConnector, ConnectorCapability


class EmailOAuthConnector(BaseConnector):
    capability = ConnectorCapability(
        name="email_oauth",
        read_only=True,
        outbound=False,
        enabled_by_default=False,
        risk_notes="Request minimum OAuth scopes; store tokens outside git.",
    )

    def iter_events(self) -> Iterator[dict]:
        raise NotImplementedError("Email OAuth connector is planned for M1.")
