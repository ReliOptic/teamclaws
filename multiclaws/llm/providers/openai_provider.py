"""OpenAI provider: gpt-4o, gpt-4o-mini"""
from __future__ import annotations

import time
from typing import Any

import httpx

from multiclaws.llm.provider import BaseProvider, LLMResponse

# USD per 1K tokens (input, output)
_PRICING = {
    "gpt-4o":           (0.0025, 0.010),
    "gpt-4o-mini":      (0.00015, 0.0006),
    "gpt-4-turbo":      (0.010,  0.030),
}
_DEFAULT_MODEL = "gpt-4o-mini"
_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(BaseProvider):
    name = "openai"
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

        choice = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        inp = usage.get("prompt_tokens", 0)
        out = usage.get("completion_tokens", 0)

        return LLMResponse(
            content=choice,
            input_tokens=inp,
            output_tokens=out,
            cost_usd=self.calc_cost(model, inp, out),
            latency_ms=latency,
            model=model,
            provider=self.name,
        )

    def calc_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        p = _PRICING.get(model, (0.002, 0.002))
        return (input_tokens * p[0] + output_tokens * p[1]) / 1000
