from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class ConnectorCapability:
    name: str
    read_only: bool = True
    outbound: bool = False
    enabled_by_default: bool = False
    risk_notes: str = ""


class BaseConnector(ABC):
    """Pull channel data into ChannelEvent dicts. No send methods in v0."""

    capability: ConnectorCapability

    @abstractmethod
    def iter_events(self) -> Iterator[dict]:
        raise NotImplementedError

    def collect(self) -> list[dict]:
        return list(self.iter_events())
