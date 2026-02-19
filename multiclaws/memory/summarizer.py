"""
Agentic Compaction: 단순 압축이 아닌 핵심 사실 추출 → L2/L3 기록.

v3.4 대비 변경:
  - fire-and-forget → awaited (정확성 보장)
  - 33% 압축 → 4개 섹션 구조적 추출 (KEY FACTS / USER PREFERENCES / OPEN TASKS / CONCLUSIONS)
  - SQLite summary만 → L2 daily log + L3 MEMORY.md 동시 기록
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from multiclaws.utils.logger import get_logger

if TYPE_CHECKING:
    from multiclaws.config import PicoConfig
    from multiclaws.memory.store import MemoryStore
    from multiclaws.llm.router import LLMRouter

log = get_logger("summarizer")

# ── Agentic Compaction 프롬프트 ─────────────────────────────────────────────
COMPACTION_PROMPT = """\
You are a memory extraction agent. Analyze the conversation below and extract structured information.

Output EXACTLY in this markdown format (include all 4 sections):

## KEY FACTS
- [specific names, numbers, dates, technical decisions, file paths, versions]
- [each bullet = one concrete fact]

## USER PREFERENCES
- [things the user explicitly likes, dislikes, wants, or wants to avoid]
- [coding style, communication style, tool preferences, etc.]

## OPEN TASKS
- [anything mentioned but not yet completed]
- [write "None" if nothing pending]

## CONCLUSIONS
- [what was resolved, decisions made, problems solved]
- [write "None" if nothing concluded]

Be extremely concise. Each bullet should be one line. Omit filler words.

---
{turns_text}
---"""


async def maybe_summarize(
    store: "MemoryStore",
    router: "LLMRouter",
    session_id: str,
    agent_role: str,
    every_n: int = 15,
    config: "PicoConfig | None" = None,
) -> bool:
    """
    임계값 체크 후 Agentic Compaction 실행 여부 결정.

    Args:
        store:      MemoryStore
        router:     LLMRouter (fast 모델 사용)
        session_id: 세션 ID
        agent_role: 호출 에이전트 역할
        every_n:    요약 트리거 턴 수 (기본 15)
        config:     PicoConfig (L2/L3 기록에 필요, None이면 SQLite만)

    Returns:
        True if compaction was triggered
    """
    count = store.count_unsummarized_turns(session_id)
    if count < every_n:
        return False

    turns = store.get_unsummarized_turns(session_id, limit=every_n)
    if not turns:
        return False

    # v3.5: awaited — fire-and-forget 제거 (정확성 보장)
    await _run_agentic_compact(store, router, session_id, agent_role, turns, config)
    return True


async def _run_agentic_compact(
    store: "MemoryStore",
    router: "LLMRouter",
    session_id: str,
    agent_role: str,
    turns: list[dict],
    config: "PicoConfig | None",
) -> None:
    """
    Agentic Compaction 핵심 로직:
    1. LLM으로 4섹션 구조적 추출
    2. SQLite summary 저장 (호환성)
    3. L2 daily log 기록
    4. L3 MEMORY.md 병합
    """
    try:
        turns_text = "\n".join(
            f"[{t['role'].upper()}]: {t['content'][:600]}" for t in turns
        )

        prompt = COMPACTION_PROMPT.format(turns_text=turns_text)

        extracted = await router.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_role=agent_role,
            task_type="fast",  # 최저 비용 모델
        )

        if not extracted or not extracted.strip():
            log.warning("Agentic compaction returned empty result for session %s", session_id)
            return

        # ── 1. SQLite summary (기존 호환성 유지) ──────────────────────────
        turn_ids = [t["id"] for t in turns]
        turn_range = f"{min(turn_ids)}-{max(turn_ids)}"
        store.save_summary(session_id, extracted, turn_range)
        store.mark_summarized(session_id, turn_ids)

        log.info(
            "Agentic compaction: %d turns → %d chars [session=%s, range=%s]",
            len(turns), len(extracted), session_id, turn_range,
        )

        # ── 2. L2 Daily log 기록 ─────────────────────────────────────────
        if config is not None:
            try:
                from multiclaws.memory.daily_log import append_to_daily_log
                short_id = session_id[-8:] if len(session_id) > 8 else session_id
                append_to_daily_log(config, extracted, heading=f"Session {short_id}")
                log.debug("L2 daily log updated for session %s", session_id)
            except Exception as e:
                log.warning("L2 daily log write failed: %s", e)

        # ── 3. L3 MEMORY.md 병합 ─────────────────────────────────────────
        if config is not None:
            try:
                from multiclaws.memory.durable_memory import merge_compaction_result
                update_map = merge_compaction_result(config, extracted)
                updated = [k for k, v in update_map.items() if v]
                if updated:
                    log.info("L3 MEMORY.md updated sections: %s", updated)
            except Exception as e:
                log.warning("L3 MEMORY.md merge failed: %s", e)

    except Exception as exc:
        log.error("Agentic compaction failed for session %s: %s", session_id, exc)
