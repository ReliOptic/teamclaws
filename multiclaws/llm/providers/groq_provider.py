"""Groq provider: llama-3.3-70b, mixtral-8x7b — ultra-fast, cheapest"""
from __future__ import annotations

import time
from typing import Any

import httpx

from multiclaws.llm.provider import BaseProvider, LLMResponse

_PRICING = {
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
    "llama-3.1-8b-instant":    (0.00005, 0.00008),
    "mixtral-8x7b-32768":      (0.00024, 0.00024),
}
_DEFAULT_MODEL = "llama-3.1-8b-instant"
_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider(BaseProvider):
    name = "groq"
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
        async with httpx.AsyncClient(timeout=15) as client:
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
        p = _PRICING.get(model, (0.0005, 0.0005))
        return (input_tokens * p[0] + output_tokens * p[1]) / 1000
