"""
Abstract BaseProvider class. All LLM providers inherit this. (§4-1)
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    model: str
    provider: str


class BaseProvider(ABC):
    """Abstract provider. Implement complete() only."""

    name: str = "base"
    models: list[str] = []

    def __init__(self, api_key: str, **kwargs: Any) -> None:
        self.api_key = api_key
        self._latency_samples: list[int] = []

    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Make a completion call. Raises on failure."""

    @property
    def avg_latency_ms(self) -> int:
        if not self._latency_samples:
            return 1000
        return int(sum(self._latency_samples[-10:]) / len(self._latency_samples[-10:]))

    def _record_latency(self, ms: int) -> None:
        self._latency_samples.append(ms)
        if len(self._latency_samples) > 50:
            self._latency_samples.pop(0)

    def _elapsed_ms(self, start: float) -> int:
        return int((time.perf_counter() - start) * 1000)

    def calc_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Override in subclass with actual pricing."""
        return 0.0

    def is_available(self) -> bool:
        return bool(self.api_key)
