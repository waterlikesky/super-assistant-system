"""Read-only channel connectors. Real I/O lands in M1+; wechat stays opt-in."""

from .base import BaseConnector, ConnectorCapability

__all__ = ["BaseConnector", "ConnectorCapability"]
