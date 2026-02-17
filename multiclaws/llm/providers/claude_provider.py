"""Anthropic Claude provider: claude-sonnet-4-5, haiku"""
from __future__ import annotations

import time
from typing import Any

import httpx

from multiclaws.llm.provider import BaseProvider, LLMResponse

_PRICING = {
    "claude-sonnet-4-5-20250929": (0.003, 0.015),
    "claude-haiku-4-5-20251001":  (0.00025, 0.00125),
    "claude-opus-4-6":            (0.015,  0.075),
}
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_API_URL = "https://api.anthropic.com/v1/messages"


class ClaudeProvider(BaseProvider):
    name = "anthropic"
    models = list(_PRICING.keys())

    async def complete(
        self,
        messages: list[dict],
        model: str = _DEFAULT_MODEL,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        start = time.perf_counter()

        # Separate system message if present
        system_msg = ""
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                filtered.append(m)

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": model,
            "messages": filtered,
            "max_tokens": max_tokens,
        }
        if system_msg:
            payload["system"] = system_msg

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        latency = self._elapsed_ms(start)
        self._record_latency(latency)

        content = data["content"][0]["text"]
        usage = data.get("usage", {})
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)

        return LLMResponse(
            content=content,
            input_tokens=inp,
            output_tokens=out,
            cost_usd=self.calc_cost(model, inp, out),
            latency_ms=latency,
            model=model,
            provider=self.name,
        )

    def calc_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        p = _PRICING.get(model, (0.003, 0.015))
        return (input_tokens * p[0] + output_tokens * p[1]) / 1000
