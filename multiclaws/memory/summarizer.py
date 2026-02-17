"""
Auto-summarization: every 15 turns, fire-and-forget cheapest LLM.
Compresses to ~33% token count. (§5-2)
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from multiclaws.utils.logger import get_logger

if TYPE_CHECKING:
    from multiclaws.memory.store import MemoryStore
    from multiclaws.llm.router import LLMRouter

log = get_logger("summarizer")

SUMMARIZE_PROMPT = (
    "You are a memory compressor. Extract key facts, decisions, and action items "
    "from the following conversation turns. Be concise — target {target_tokens} tokens. "
    "Output only the summary, no preamble.\n\n---\n{turns_text}\n---"
)


async def maybe_summarize(
    store: "MemoryStore",
    router: "LLMRouter",
    session_id: str,
    agent_role: str,
    every_n: int = 15,
) -> bool:
    """Check if summarization needed; if so, run fire-and-forget. Returns True if triggered."""
    count = store.count_unsummarized_turns(session_id)
    if count < every_n:
        return False

    turns = store.get_unsummarized_turns(session_id, limit=every_n)
    if not turns:
        return False

    asyncio.create_task(_run_summarize(store, router, session_id, agent_role, turns))
    return True


async def _run_summarize(
    store: "MemoryStore",
    router: "LLMRouter",
    session_id: str,
    agent_role: str,
    turns: list[dict],
) -> None:
    try:
        turns_text = "\n".join(
            f"[{t['role']}]: {t['content'][:500]}" for t in turns
        )
        total_tokens = sum(t.get("tokens", 50) for t in turns)
        target_tokens = max(50, int(total_tokens * 0.33))

        prompt = SUMMARIZE_PROMPT.format(
            target_tokens=target_tokens,
            turns_text=turns_text,
        )

        summary_text = await router.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_role=agent_role,
            task_type="fast",  # use cheapest available model
        )

        if not summary_text:
            return

        turn_ids = [t["id"] for t in turns]
        turn_range = f"{min(turn_ids)}-{max(turn_ids)}"

        store.save_summary(session_id, summary_text, turn_range)
        store.mark_summarized(session_id, turn_ids)
        log.info("Summarized %d turns for session %s (range %s)", len(turns), session_id, turn_range)

    except Exception as exc:
        log.error("Summarization failed: %s", exc)
