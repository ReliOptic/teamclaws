"""Mistral provider: mistral-large, mistral-small — EU compliance"""
from __future__ import annotations

import time
from typing import Any

import httpx

from multiclaws.llm.provider import BaseProvider, LLMResponse

_PRICING = {
    "mistral-large-latest": (0.002, 0.006),
    "mistral-small-latest": (0.0002, 0.0006),
    "open-mistral-nemo":    (0.00015, 0.00015),
}
_DEFAULT_MODEL = "mistral-small-latest"
_API_URL = "https://api.mistral.ai/v1/chat/completions"


class MistralProvider(BaseProvider):
    name = "mistral"
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
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        latency = self._elapsed_ms(start)
        self._record_latency(latency)

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        inp = usage.get("prompt_tokens", 0)
        out = usage.get("completion_tokens", 0)

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
        p = _PRICING.get(model, (0.002, 0.006))
        return (input_tokens * p[0] + output_tokens * p[1]) / 1000
