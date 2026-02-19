"""
Multi-provider LLM Router with cost/quota/latency scoring. (§4-2)
Routing formula: score = priority×0.3 + (1-norm_cost)×0.3 + (1-norm_latency)×0.2 + quota×0.2
Fallback chain: top-3 by score → try #1 → #2 → #3 → raise ProviderExhaustedError
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiclaws.llm.provider import BaseProvider, LLMResponse
from multiclaws.utils.logger import get_logger

if TYPE_CHECKING:
    from multiclaws.config import PicoConfig
    from multiclaws.memory.store import MemoryStore

log = get_logger("llm.router")

# Task type → preferred model quality mapping  (v3.5: openrouter 추가)
TASK_MODEL_MAP = {
    "complex":  {"openai": "gpt-4o",            "anthropic": "claude-sonnet-4-5-20250929",
                 "google": "gemini-1.5-pro",     "groq": "llama-3.3-70b-versatile",
                 "mistral": "mistral-large-latest",
                 "openrouter": "qwen/qwen-2.5-72b-instruct:free"},
    "simple":   {"openai": "gpt-4o-mini",        "anthropic": "claude-haiku-4-5-20251001",
                 "google": "gemini-2.0-flash",   "groq": "llama-3.1-8b-instant",
                 "mistral": "mistral-small-latest",
                 "openrouter": "google/gemma-3-27b-it:free"},
    "fast":     {"openai": "gpt-4o-mini",        "anthropic": "claude-haiku-4-5-20251001",
                 "google": "gemini-2.0-flash",   "groq": "llama-3.1-8b-instant",
                 "mistral": "open-mistral-nemo",
                 "openrouter": "mistralai/mistral-7b-instruct:free"},
}


class ProviderExhaustedError(Exception):
    pass


class LLMRouter:
    def __init__(self, config: "PicoConfig", store: "MemoryStore | None" = None) -> None:
        self.config = config
        self.store = store
        self._providers: dict[str, BaseProvider] = {}
        self._quota_remaining: dict[str, float] = {}
        self._load_providers()

    def _load_providers(self) -> None:
        from multiclaws.llm.providers.claude_provider import ClaudeProvider
        from multiclaws.llm.providers.gemini_provider import GeminiProvider
        from multiclaws.llm.providers.groq_provider import GroqProvider
        from multiclaws.llm.providers.mistral_provider import MistralProvider
        from multiclaws.llm.providers.openai_provider import OpenAIProvider
        from multiclaws.llm.providers.openrouter_provider import OpenRouterProvider  # v3.5

        classes = {
            "openai":      OpenAIProvider,
            "anthropic":   ClaudeProvider,
            "google":      GeminiProvider,
            "groq":        GroqProvider,
            "mistral":     MistralProvider,
            "openrouter":  OpenRouterProvider,  # v3.5
        }
        for name, cls in classes.items():
            pcfg = self.config.provider(name)
            if pcfg.enabled and pcfg.api_key:
                self._providers[name] = cls(api_key=pcfg.api_key)
                self._quota_remaining[name] = 1.0
                log.info("Provider loaded: %s", name)

        if not self._providers:
            log.warning("No LLM providers configured. Set API keys in .env or config.yaml")

    # ── Routing ────────────────────────────────────────────────────────────
    def _score(self, provider_name: str) -> float:
        pcfg = self.config.provider(provider_name)
        prov = self._providers[provider_name]

        # Normalize cost (lower = better)
        all_costs = [self.config.provider(n).cost_per_1k_input
                     for n in self._providers if self.config.provider(n).cost_per_1k_input > 0]
        max_cost = max(all_costs) if all_costs else 0.01
        norm_cost = pcfg.cost_per_1k_input / max_cost if max_cost else 0

        # Normalize latency (lower = better)
        all_lat = [p.avg_latency_ms for p in self._providers.values()]
        max_lat = max(all_lat) if all_lat else 1000
        norm_lat = prov.avg_latency_ms / max_lat if max_lat else 0

        quota = self._quota_remaining.get(provider_name, 1.0)
        priority = pcfg.priority

        return priority * 0.3 + (1 - norm_cost) * 0.3 + (1 - norm_lat) * 0.2 + quota * 0.2

    def _ranked_providers(self) -> list[str]:
        return sorted(self._providers.keys(), key=self._score, reverse=True)

    # ── Main API ──────────────────────────────────────────────────────────
    async def complete(
        self,
        messages: list[dict],
        agent_role: str = "system",
        task_type: str = "simple",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        provider_override: str | None = None,
        model_override: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Route to best provider, fallback on failure. Returns content string."""
        resp = await self.complete_full(
            messages=messages,
            agent_role=agent_role,
            task_type=task_type,
            max_tokens=max_tokens,
            temperature=temperature,
            provider_override=provider_override,
            model_override=model_override,
            **kwargs,
        )
        return resp.content

    async def complete_full(
        self,
        messages: list[dict],
        agent_role: str = "system",
        task_type: str = "simple",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        provider_override: str | None = None,
        model_override: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Route and return full LLMResponse including cost/latency."""
        if not self._providers:
            raise ProviderExhaustedError("No LLM providers available. Configure API keys.")

        if provider_override and provider_override in self._providers:
            ordered = [provider_override]
        else:
            ordered = self._ranked_providers()[:3]

        model_map = TASK_MODEL_MAP.get(task_type, TASK_MODEL_MAP["simple"])
        last_exc: Exception = ProviderExhaustedError("All providers failed")

        for pname in ordered:
            prov = self._providers[pname]
            model = model_override or model_map.get(pname, prov.models[0])
            try:
                resp = await prov.complete(
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )
                # Log cost
                if self.store:
                    self.store.log_cost(
                        agent_role=agent_role,
                        provider=pname,
                        model=model,
                        input_tokens=resp.input_tokens,
                        output_tokens=resp.output_tokens,
                        cost_usd=resp.cost_usd,
                        latency_ms=resp.latency_ms,
                    )
                    # Budget check
                    daily = self.store.get_daily_cost()
                    limit = self.config.budget.daily_usd
                    pct = daily / limit * 100 if limit else 0
                    if daily >= limit:
                        raise ProviderExhaustedError(
                            f"Daily budget exhausted: ${daily:.4f} / ${limit:.2f}"
                        )
                    if pct >= self.config.budget.alert_threshold_percent:
                        log.warning("Daily budget %.1f%% used ($%.4f / $%.2f)",
                                    pct, daily, limit)
                return resp

            except Exception as exc:
                log.warning("Provider %s failed: %s. Trying next.", pname, exc)
                self._quota_remaining[pname] = max(0, self._quota_remaining.get(pname, 1) - 0.3)
                last_exc = exc

        raise ProviderExhaustedError(f"All providers exhausted: {last_exc}") from last_exc

    def available_providers(self) -> list[str]:
        return list(self._providers.keys())
