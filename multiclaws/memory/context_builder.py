"""
Token-budget-aware context builder. (Phase E2)
Constructs LLM message list within token limits:
  system_prompt > latest summary > recent turns (newest first)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiclaws.config import AgentBudgetConfig


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 4 chars ≈ 1 token."""
    return max(1, len(text) // 4)


def build_context(
    system_prompt: str,
    summaries: list[str],
    short_term: list[dict],
    budget: "AgentBudgetConfig",
) -> tuple[list[dict], int]:
    """
    Build a message list that fits within budget.max_input_tokens.

    Priority (highest → lowest):
      1. system_prompt  (always included)
      2. Latest summary (if fits)
      3. Recent short_term turns (newest included first, up to context_turns)

    Returns (messages, estimated_token_count).
    """
    remaining = budget.max_input_tokens
    messages: list[dict] = []

    # 1. System prompt — always
    sys_tokens = estimate_tokens(system_prompt)
    messages.append({"role": "system", "content": system_prompt})
    remaining -= sys_tokens

    # 2. Latest summary
    if summaries and remaining > 100:
        summary_text = "MEMORY SUMMARY:\n" + "\n---\n".join(summaries[-1:])
        s_tokens = estimate_tokens(summary_text)
        if s_tokens <= remaining - 100:  # keep 100 token buffer for turns
            messages.append({"role": "system", "content": summary_text})
            remaining -= s_tokens

    # 3. Recent turns (newest last, bounded by context_turns)
    capped = short_term[-budget.context_turns:]
    turn_messages: list[dict] = []
    for turn in reversed(capped):
        t_tokens = estimate_tokens(turn.get("content", ""))
        if t_tokens > remaining:
            break
        turn_messages.insert(0, turn)
        remaining -= t_tokens

    messages.extend(turn_messages)
    used = budget.max_input_tokens - remaining
    return messages, used
