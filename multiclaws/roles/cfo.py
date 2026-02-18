"""
CFO Middleware: Resource Allocation & Model Selection.
Pure Python rule engine — no LLM call for routine decisions.

Responsibilities:
  1. Dynamic model selection (task complexity → task_type)
  2. Token budget allocation per task
  3. Cost projection & veto when over-budget
  4. Monthly/daily cost reporting to CEO
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiclaws.config import PicoConfig
    from multiclaws.memory.store import MemoryStore


# ── Complexity scoring keywords ────────────────────────────────────────────────
_COMPLEX_SIGNALS = frozenset([
    "architect", "design", "debug", "refactor", "analyze", "implement",
    "optimize", "explain", "compare", "evaluate", "write code", "build",
    "system", "algorithm", "pipeline", "integration", "security",
])

_FAST_SIGNALS = frozenset([
    "summarize", "translate", "bullet", "list", "quick", "brief",
    "format", "convert", "rename", "fix typo", "spell", "grammar",
])


@dataclass
class CFODecision:
    task_type: str        # "complex" | "simple" | "fast"
    max_tokens: int
    approved: bool
    reason: str
    projected_cost_usd: float


class CFO:
    """
    Chief Financial Officer — lightweight middleware.
    Decides model tier and approves/blocks tasks on budget grounds.
    """

    # Cost estimates per 1K tokens (blended input+output, approximate)
    _COST_PER_1K: dict[str, float] = {
        "complex": 0.003,   # Sonnet / GPT-4o / Llama-70B
        "simple":  0.0003,  # Haiku / GPT-4o-mini / Flash
        "fast":    0.0001,  # Haiku / Flash / Nemo
    }

    def __init__(self, config: "PicoConfig", store: "MemoryStore") -> None:
        self.config = config
        self.store  = store

    # ── Public API ─────────────────────────────────────────────────────────────
    def allocate(self, task_text: str, agent_role: str) -> CFODecision:
        """
        Analyse the task, choose model tier, check budget.
        Called by CEO before dispatching to CTO/CKO.
        """
        task_type  = self._classify(task_text, agent_role)
        max_tokens = self._token_alloc(task_type, agent_role)
        projected  = self._project_cost(task_type, max_tokens)

        daily_used = self.store.get_daily_cost()
        daily_limit = self.config.budget.daily_usd
        remaining   = daily_limit - daily_used

        if projected > remaining:
            # Try downgrade first
            downgraded = self._downgrade(task_type)
            if downgraded != task_type:
                projected_down = self._project_cost(downgraded, max_tokens)
                if projected_down <= remaining:
                    return CFODecision(
                        task_type=downgraded,
                        max_tokens=max_tokens,
                        approved=True,
                        reason=f"Downgraded {task_type}→{downgraded}: "
                               f"${projected_down:.5f} fits remaining ${remaining:.4f}",
                        projected_cost_usd=projected_down,
                    )
            # Both tiers over budget — veto
            return CFODecision(
                task_type=task_type,
                max_tokens=max_tokens,
                approved=False,
                reason=f"Budget veto: projected ${projected:.5f} > "
                       f"remaining ${remaining:.4f} (daily ${daily_limit:.2f})",
                projected_cost_usd=projected,
            )

        return CFODecision(
            task_type=task_type,
            max_tokens=max_tokens,
            approved=True,
            reason=f"Approved {task_type} (${projected:.5f}, "
                   f"${daily_used:.4f}/${daily_limit:.2f} used)",
            projected_cost_usd=projected,
        )

    def cost_report(self) -> dict:
        """Summary report for CEO to relay to Chairman."""
        daily  = self.store.get_daily_cost()
        weekly = self.store.get_weekly_cost()
        limit  = self.config.budget.daily_usd
        pct    = (daily / limit * 100) if limit else 0
        return {
            "daily_used":   daily,
            "daily_limit":  limit,
            "daily_pct":    round(pct, 1),
            "weekly_used":  weekly,
            "status":       "ok" if pct < 80 else ("warning" if pct < 100 else "exhausted"),
        }

    # ── Internal helpers ───────────────────────────────────────────────────────
    def _classify(self, text: str, agent_role: str) -> str:
        """Keyword-based complexity scoring → task_type."""
        lower = text.lower()

        # Researcher always uses "simple" (context retrieval, not heavy reasoning)
        if agent_role in ("researcher", "cko"):
            return "simple"

        # Count signal words
        complex_hits = sum(1 for kw in _COMPLEX_SIGNALS if kw in lower)
        fast_hits    = sum(1 for kw in _FAST_SIGNALS    if kw in lower)

        if complex_hits >= 2 or len(text) > 400:
            return "complex"
        if fast_hits >= 1 and complex_hits == 0:
            return "fast"
        if len(text) < 80:
            return "fast"
        return "simple"

    def _token_alloc(self, task_type: str, agent_role: str) -> int:
        budget = self.config.agent_budget(agent_role)
        # Complex tasks get full allocation; fast tasks get half
        multiplier = {"complex": 1.0, "simple": 0.75, "fast": 0.5}.get(task_type, 0.75)
        return max(256, int(budget.max_output_tokens * multiplier))

    def _project_cost(self, task_type: str, max_tokens: int) -> float:
        rate = self._COST_PER_1K.get(task_type, 0.001)
        return rate * max_tokens / 1000

    @staticmethod
    def _downgrade(task_type: str) -> str:
        return {"complex": "simple", "simple": "fast", "fast": "fast"}[task_type]
