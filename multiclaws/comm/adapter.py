"""Unified messaging interface (abstract). (§6 Phase 6)"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MessageAdapter(ABC):
    """All comm adapters implement this interface."""

    @abstractmethod
    async def start(self, handler) -> None:
        """Start listening. handler(platform, user_id, text) -> str"""

    @abstractmethod
    async def send(self, user_id: str, text: str, **kwargs: Any) -> None:
        """Send a message to user."""

    @abstractmethod
    async def stop(self) -> None:
        """Graceful shutdown."""
