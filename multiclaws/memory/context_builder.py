"""
v3.5 Token-budget-aware context builder — 3계층 메모리 통합.

컨텍스트 조립 우선순위 (높음 → 낮음):
  1. system_prompt   (항상 포함)
  2. durable_memory  (L3: MEMORY.md 영구 사실 + 사용자 선호)
  3. daily_log       (L2: 오늘+어제 핵심 사실)
  4. retrieved_chunks (하이브리드 검색 결과)
  5. latest summaries (SQLite Agentic Compaction 캐시)
  6. recent turns    (L1: 최신 대화, 토큰 남은 만큼)

v3.4 대비 변경:
  - L2/L3/retrieved 슬롯 추가 (선택적, 하위 호환)
  - 토큰 예산 4096 → 32k+ (config에서 결정)
  - 각 슬롯 별 최대 비율 할당으로 turn 공간 보호
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiclaws.config import AgentBudgetConfig


def estimate_tokens(text: str) -> int:
    """4자 ≈ 1 토큰 (보수적 추정)."""
    return max(1, len(text) // 4)


def build_context(
    system_prompt: str,
    summaries: list[str],
    short_term: list[dict],
    budget: "AgentBudgetConfig",
    # v3.5 신규 파라미터 (선택적 — 하위 호환 유지)
    daily_log: str = "",
    durable_memory: str = "",
    retrieved_chunks: list[str] | None = None,
) -> tuple[list[dict], int]:
    """
    토큰 예산 내에서 LLM 메시지 리스트 조립.

    Args:
        system_prompt:    CEO/Researcher/Coder 시스템 프롬프트
        summaries:        SQLite Agentic Compaction 캐시 (최신 N개)
        short_term:       L1 단기 대화 (deque → list)
        budget:           AgentBudgetConfig (max_input_tokens, context_turns)
        daily_log:        L2 일일 로그 텍스트 (선택)
        durable_memory:   L3 MEMORY.md 전체 텍스트 (선택)
        retrieved_chunks: 하이브리드 검색 결과 (선택)

    Returns:
        (messages, estimated_token_count)
    """
    remaining = budget.max_input_tokens
    messages: list[dict] = []

    # ── 1. System Prompt (항상) ───────────────────────────────────────────
    sys_tokens = estimate_tokens(system_prompt)
    messages.append({"role": "system", "content": system_prompt})
    remaining -= sys_tokens

    # ── 2. L3 Durable Memory (MEMORY.md) ────────────────────────────────
    # 전체 예산의 최대 25% 할당
    if durable_memory and remaining > 200:
        l3_budget = min(remaining // 4, estimate_tokens(durable_memory))
        if l3_budget > 50:
            l3_text = _trim_to_tokens(
                f"[PERSISTENT MEMORY]\n{durable_memory}", l3_budget
            )
            messages.append({"role": "system", "content": l3_text})
            remaining -= estimate_tokens(l3_text)

    # ── 3. L2 Daily Log (오늘+어제) ──────────────────────────────────────
    # 전체 예산의 최대 20% 할당
    if daily_log and remaining > 200:
        l2_budget = min(remaining // 5, estimate_tokens(daily_log))
        if l2_budget > 50:
            l2_text = _trim_to_tokens(
                f"[DAILY LOG]\n{daily_log}", l2_budget
            )
            messages.append({"role": "system", "content": l2_text})
            remaining -= estimate_tokens(l2_text)

    # ── 4. Retrieved Chunks (하이브리드 검색) ───────────────────────────
    # 전체 예산의 최대 15% 할당
    if retrieved_chunks and remaining > 200:
        retrieval_budget = remaining // 6
        retrieval_parts: list[str] = []
        used = 0
        for chunk in retrieved_chunks:
            chunk_tokens = estimate_tokens(chunk)
            if used + chunk_tokens > retrieval_budget:
                break
            retrieval_parts.append(chunk)
            used += chunk_tokens
        if retrieval_parts:
            retrieved_text = "[RETRIEVED CONTEXT]\n" + "\n---\n".join(retrieval_parts)
            messages.append({"role": "system", "content": retrieved_text})
            remaining -= used

    # ── 5. Latest Summary (SQLite Agentic Compaction 캐시) ───────────────
    if summaries and remaining > 150:
        summary_text = "[MEMORY SUMMARY]\n" + summaries[-1]
        s_tokens = estimate_tokens(summary_text)
        if s_tokens <= remaining - 150:
            messages.append({"role": "system", "content": summary_text})
            remaining -= s_tokens

    # ── 6. Recent Turns (L1 단기 대화) ──────────────────────────────────
    capped = short_term[-budget.context_turns:]
    turn_messages: list[dict] = []
    for turn in reversed(capped):
        t_tokens = estimate_tokens(turn.get("content", ""))
        if t_tokens > remaining:
            break
        turn_messages.insert(0, {"role": turn["role"], "content": turn["content"]})
        remaining -= t_tokens

    messages.extend(turn_messages)

    used_total = budget.max_input_tokens - remaining
    return messages, used_total


def _trim_to_tokens(text: str, max_tokens: int) -> str:
    """
    텍스트를 max_tokens 이하로 잘라냄.
    4자 ≈ 1 토큰 근사. 끝에 "[truncated]" 표시.
    """
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 15] + "\n[...truncated]"
