"""Google Gemini provider: gemini-2.0-flash, gemini-pro"""
from __future__ import annotations

import time
from typing import Any

import httpx

from multiclaws.llm.provider import BaseProvider, LLMResponse

_PRICING = {
    "gemini-2.0-flash":         (0.0001, 0.0004),
    "gemini-1.5-pro":           (0.00125, 0.005),
    "gemini-1.5-flash":         (0.000075, 0.0003),
}
_DEFAULT_MODEL = "gemini-2.0-flash"
_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(BaseProvider):
    name = "google"
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

        # Convert to Gemini format
        contents = []
        system_instruction = None
        for m in messages:
            if m["role"] == "system":
                system_instruction = m["content"]
            else:
                role = "user" if m["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        url = f"{_API_BASE}/{model}:generateContent?key={self.api_key}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        latency = self._elapsed_ms(start)
        self._record_latency(latency)

        content = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        inp = usage.get("promptTokenCount", 0)
        out = usage.get("candidatesTokenCount", 0)

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
        p = _PRICING.get(model, (0.0001, 0.0004))
        return (input_tokens * p[0] + output_tokens * p[1]) / 1000
