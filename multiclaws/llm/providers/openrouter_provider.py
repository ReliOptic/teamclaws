"""
OpenRouter provider: OpenAI-compatible API with free model tier. (v3.5)

특징:
  - 단일 API 키로 100+ 모델 접근
  - :free 접미사 모델: 무료 (rate limit 있음)
  - Groq 할당량 초과 시 자동 폴백 대상
  - 우선순위: 0.85 (Groq 0.9 바로 아래)

무료 모델 목록 (2025년 기준, 변경 가능):
  - google/gemma-3-27b-it:free
  - meta-llama/llama-3.2-3b-instruct:free
  - qwen/qwen-2.5-72b-instruct:free
  - mistralai/mistral-7b-instruct:free
  - microsoft/phi-3-mini-128k-instruct:free

API 문서: https://openrouter.ai/docs
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from multiclaws.llm.provider import BaseProvider, LLMResponse

_API_URL = "https://openrouter.ai/api/v1/chat/completions"
_SITE_URL = "https://github.com/YOUR_GITHUB/teamclaws"  # setup.sh 설치 시 자동 교체됨
_APP_NAME = "TeamClaws"

# 무료 모델 — cost 0
_FREE_MODELS = [
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "microsoft/phi-3-mini-128k-instruct:free",
]

# task_type 별 기본 모델
_TASK_MODELS = {
    "complex": "qwen/qwen-2.5-72b-instruct:free",
    "simple":  "google/gemma-3-27b-it:free",
    "fast":    "mistralai/mistral-7b-instruct:free",
}

_DEFAULT_MODEL = _TASK_MODELS["fast"]


class OpenRouterProvider(BaseProvider):
    """
    OpenRouter API provider.

    OpenAI 호환 인터페이스 사용.
    요청 시 HTTP-Referer, X-Title 헤더 필수 (OpenRouter 정책).
    """
    name = "openrouter"
    models = _FREE_MODELS

    async def complete(
        self,
        messages: list[dict],
        model: str = _DEFAULT_MODEL,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        start = time.perf_counter()

        # Claude 형식 system 메시지는 그대로 통과 (OpenRouter가 처리)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": _SITE_URL,
            "X-Title": _APP_NAME,
        }
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=90) as client:  # 무료 모델은 느릴 수 있음
            resp = await client.post(_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        latency = self._elapsed_ms(start)
        self._record_latency(latency)

        # OpenRouter는 OpenAI 형식 응답
        choices = data.get("choices", [])
        if not choices:
            raise ValueError(f"OpenRouter returned no choices: {data}")

        content = choices[0]["message"]["content"] or ""
        usage = data.get("usage", {})
        inp = usage.get("prompt_tokens", 0)
        out = usage.get("completion_tokens", 0)

        # 무료 모델은 cost 0
        cost = self.calc_cost(model, inp, out)

        return LLMResponse(
            content=content,
            input_tokens=inp,
            output_tokens=out,
            cost_usd=cost,
            latency_ms=latency,
            model=model,
            provider=self.name,
        )

    def calc_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """무료 모델은 0, 유료 모델은 OpenRouter 공시 가격 적용."""
        if model.endswith(":free"):
            return 0.0
        # 유료 모델 fallback (OpenRouter 평균 가격)
        return (input_tokens * 0.001 + output_tokens * 0.001) / 1000

    @classmethod
    def get_model_for_task(cls, task_type: str) -> str:
        """CFO task_type → 최적 무료 모델 반환."""
        return _TASK_MODELS.get(task_type, _DEFAULT_MODEL)
