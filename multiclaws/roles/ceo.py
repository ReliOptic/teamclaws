"""
CEO PicoClaw: Chairman-CEO-Boardroom 3계층 구조의 중재자. (v3.6)

이사회 프로토콜 (Boardroom Protocol):
  1. INTERPRET  — Chairman의 의도 파악 (한 번만 되물음)
  2. CFO CHECK  — 예산·모델 배정 결재
  3. CSO CHECK  — 보안 정책 검토 (거부권)
  4. DELEGATE   — CTO(코드) 또는 CKO(리서치) 또는 직접 처리
  5. RETRY      — Expert 실패 시 2-Strike Rule → Chairman 보고
  6. REPORT     — 결과 종합 후 Chairman에게 보고

CEO는 직접 코드를 실행하지 않는다. 판단하고 위임한다.
"""
from __future__ import annotations

import json
from typing import Any

from multiclaws.core.picoclaw import PicoClaw
from multiclaws.llm.router import LLMRouter
from multiclaws.memory.context_builder import build_context
from multiclaws.memory.summarizer import maybe_summarize
from multiclaws.memory.task_context import get_task_context
from multiclaws.roles.cfo import CFO
from multiclaws.roles.coo import COO
from multiclaws.roles.cso import CSO
from multiclaws.roles.permissions import get_tools_for_role
from multiclaws.tools.builtins.delegate import DelegateTaskTool
from multiclaws.tools.registry import Tool, get_registry


# ── CreatePlanTool ─────────────────────────────────────────────────────────────
class CreatePlanTool(Tool):
    """
    CEO가 Chairman에게 실행 계획을 제시하고 Task Queue에 등록한다.
    각 단계는 CSO/CFO 결재 후 CTO/CKO에게 위임된다.
    """
    name = "create_plan"
    description = (
        "Break a complex goal into ordered subtasks for expert agents. "
        "Each step specifies agent (cto/cko/communicator) and task payload. "
        "Dependency links prevent steps from running before predecessors complete."
    )
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent":           {"type": "string",
                                            "description": "cto | cko | communicator"},
                        "task":            {"type": "object"},
                        "depends_on_step": {"type": "integer"},
                    },
                    "required": ["agent", "task"],
                },
            },
        },
        "required": ["goal", "steps"],
    }

    def __init__(self, store=None) -> None:
        self._store = store

    async def execute(self, goal: str, steps: list, **_) -> dict:  # type: ignore[override]
        if not self._store:
            return {"error": "CreatePlanTool has no store."}
        task_ids: list[str] = []
        for step in steps:
            task_id = self._store.create_task(
                assigned_to=step["agent"],
                input_data=step["task"],
            )
            task_ids.append(task_id)
            dep_idx = step.get("depends_on_step")
            if dep_idx is not None and 0 <= dep_idx < len(task_ids) - 1:
                self._store.add_task_dependency(task_id, task_ids[dep_idx])
        return {"goal": goal, "tasks_created": len(task_ids), "task_ids": task_ids}


# ── System Prompt ──────────────────────────────────────────────────────────────
CEO_SYSTEM = """You are the CEO of TeamClaws — Chief of Staff in a Boardroom structure.

Hierarchy:
  Chairman (User) → CEO (You) → CTO | CKO | Communicator

Your exact protocol for every request:
1. INTERPRET: State your understanding. If ambiguous, ask exactly ONE clarifying question.
2. PLAN: For complex tasks (3+ steps), use create_plan first. For simple tasks, go to step 3.
3. DELEGATE: Use delegate_task to assign work — CTO for code/files, CKO for research.
4. WAIT: Block until expert returns result. You do not execute code yourself.
5. REPORT: Synthesize results clearly for the Chairman.

Expert roster:
- cto:          Code writing, debugging, file I/O, shell commands, technical architecture
- cko:          Web research, URL fetching, information gathering, knowledge synthesis
- communicator: Drafting messages, documentation, reports, notifications

Rules:
- You NEVER run code or fetch URLs yourself
- If an expert fails twice (2-Strike Rule), report to Chairman with error details
- CFO manages your model/budget; CSO enforces security — both are already active
- Be concise. Chairman is busy. One paragraph max unless detail was requested."""


# ── CEOAgent ───────────────────────────────────────────────────────────────────
class CEOAgent(PicoClaw):
    role = "ceo"
    description = "Chief of Staff — Boardroom orchestrator with CFO/CSO governance"

    # 2-Strike retry tracking: {task_hash: attempt_count}
    _retry_counts: dict[str, int] = {}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._router: LLMRouter | None = None
        self._registry = None
        self._cfo: CFO | None = None
        self._cso: CSO | None = None
        self._coo: COO | None = None

    def run(self) -> None:
        self._router   = LLMRouter(self.config)
        self._registry = get_registry()
        self._cfo      = CFO(self.config, self.store)
        self._cso      = CSO(self.store)
        self._coo      = COO(self.config, self.store)
        self._inject_delegate_dispatcher()
        self._registry.register(CreatePlanTool(store=self.store))
        self._setup_memory_watch()
        super().run()

    def _setup_memory_watch(self) -> None:
        """COO: MEMORY.md 변경 감지 → FTS5 자동 재색인 (v3.5)."""
        if not self._coo:
            return
        try:
            from multiclaws.memory.chunker import reindex_memory_file
            from multiclaws.utils.logger import get_logger
            _log = get_logger("ceo.memory_watch")

            memory_file = self.config.workspace / "MEMORY.md"
            memory_dir = str(memory_file.parent)

            def _on_memory_change(event_type: str, file_path: str) -> None:
                if event_type in ("modified", "created"):
                    count = reindex_memory_file(self.store, file_path)
                    if count > 0:
                        _log.info("MEMORY.md reindexed: %d new chunks", count)

            self._coo.watch(
                path=memory_dir,
                callback=_on_memory_change,
                pattern="MEMORY.md",
                description="L3 durable memory auto-reindex",
            )
        except Exception as e:
            from multiclaws.utils.logger import get_logger
            get_logger("ceo").warning("Memory watch setup failed (non-fatal): %s", e)

    def _inject_delegate_dispatcher(self) -> None:
        """Wire inline blocking dispatcher (보고 체계 안전장치)."""
        delegate_tool = self._registry.get("delegate_task")
        if isinstance(delegate_tool, DelegateTaskTool):
            delegate_tool._dispatcher = self._inline_dispatch

    async def _inline_dispatch(self, agent_role: str, task: dict) -> dict:
        """
        Dispatch to an Expert and BLOCK until result received.
        Wraps with CFO model decision + CSO security review.
        """
        from multiclaws.roles.coder import CoderAgent
        from multiclaws.roles.researcher import ResearcherAgent
        from multiclaws.roles.communicator import CommunicatorAgent

        # CTO/CKO naming aliases map to agent classes
        agent_map: dict[str, type] = {
            "cto":          CoderAgent,
            "coder":        CoderAgent,
            "cko":          ResearcherAgent,
            "researcher":   ResearcherAgent,
            "communicator": CommunicatorAgent,
        }
        cls = agent_map.get(agent_role)
        if cls is None:
            return {"error": f"Unknown expert: '{agent_role}'. "
                             f"Available: cto, cko, communicator"}

        task_text = json.dumps(task)

        # ── CFO: model allocation ────────────────────────────────────────────
        cfo_decision = self._cfo.allocate(task_text, agent_role) if self._cfo else None
        if cfo_decision and not cfo_decision.approved:
            return {
                "error": f"CFO veto: {cfo_decision.reason}",
                "cfo_action": "budget_exceeded",
            }

        # ── CSO: security review ─────────────────────────────────────────────
        cso_decision = self._cso.review(task_text, agent_role=agent_role) if self._cso else None
        if cso_decision and not cso_decision.approved:
            return {
                "error": f"CSO veto: {'; '.join(cso_decision.findings)}",
                "cso_action": "security_violation",
                "risk_level": cso_decision.risk_level,
            }

        # ── Instantiate expert with CFO-allocated model parameters ───────────
        expert = cls(config=self.config)
        expert._store  = self.store
        expert._router = LLMRouter(self.config, self.store)

        # Pass CFO's task_type override to the expert via task payload
        if cfo_decision:
            task = {**task, "_task_type": cfo_decision.task_type,
                    "_max_tokens": cfo_decision.max_tokens}

        return await expert.handle_task(task)

    # ── 2-Strike retry wrapper ─────────────────────────────────────────────────
    async def _dispatch_with_retry(
        self, agent_role: str, task: dict, task_key: str
    ) -> dict:
        """
        2-Strike Rule:
          Attempt 1: dispatch normally
          Attempt 2 (on error): same task, different framing hint
          Attempt 3: return error to CEO for Chairman escalation
        """
        MAX_STRIKES = 2
        attempts = self._retry_counts.get(task_key, 0)

        result = await self._inline_dispatch(agent_role, task)

        if "error" not in result:
            # Success — clear retry counter
            self._retry_counts.pop(task_key, None)
            return result

        attempts += 1
        self._retry_counts[task_key] = attempts

        if attempts < MAX_STRIKES:
            # Retry with hint
            retry_task = {**task, "_retry_hint": f"Previous attempt failed. Try alternative approach."}
            result2 = await self._inline_dispatch(agent_role, retry_task)
            if "error" not in result2:
                self._retry_counts.pop(task_key, None)
                return result2
            self._retry_counts[task_key] = MAX_STRIKES

        # 2 strikes — escalate to Chairman
        return {
            "error":      result.get("error", "Unknown error"),
            "escalate":   True,
            "agent_role": agent_role,
            "strikes":    self._retry_counts.get(task_key, MAX_STRIKES),
            "message":    (
                f"[Boardroom Escalation] {agent_role.upper()} failed after "
                f"{self._retry_counts.get(task_key, MAX_STRIKES)} attempt(s). "
                f"Chairman intervention required."
            ),
        }

    async def handle_task(self, task: dict[str, Any]) -> dict[str, Any]:
        session_id = task.get("session_id", "ceo:default:session")
        user_msg   = task.get("message", task.get("content", ""))

        if not user_msg:
            return {"result": "No message provided"}

        # Persist Chairman's message
        self.store.push_turn(session_id, "user", user_msg, agent_role=self.role)

        # ── v3.6: 4계층 메모리 로드 ──────────────────────────────────────
        budget     = self.config.agent_budget(self.role)
        summaries  = self.store.load_latest_summaries(session_id)
        short_term = self.store.get_context(session_id)  # v3.6: 자동 복구 포함

        # L3 Durable Memory (MEMORY.md)
        durable_memory = ""
        try:
            from multiclaws.memory.durable_memory import load_durable_memory
            durable_memory = load_durable_memory(self.config)
        except Exception:
            pass

        # L2 Daily Log (오늘+어제)
        daily_log = ""
        try:
            from multiclaws.memory.daily_log import load_recent_daily_logs
            daily_log = load_recent_daily_logs(self.config, n_days=2)
        except Exception:
            pass

        # Hybrid retrieval (FTS5)
        retrieved_chunks: list[str] = []
        try:
            from multiclaws.memory.retriever import HybridRetriever
            retriever = HybridRetriever(self.store)
            result = retriever.search_all_context(user_msg, session_id)
            retrieved_chunks = result.get("memory_chunks", [])
        except Exception:
            pass

        # v3.6: 팀 활동 컨텍스트 (팀 유기체 성장 메모리)
        team_context = ""
        try:
            team_context = self.store.get_team_context(session_id)
        except Exception:
            pass

        # v3.6: 태스크 즉시 기록 컨텍스트 (INSTRUNCTION.md 방식)
        task_ctx_block = ""
        try:
            task_ctx = get_task_context(session_id, self.config.workspace)
            task_ctx.append(f"Chairman 요청: {user_msg[:120]}", agent="chairman")
            task_ctx_block = task_ctx.as_system_block()
        except Exception:
            pass

        # 팀 컨텍스트 + 태스크 컨텍스트를 시스템 프롬프트에 병합
        system_prompt = CEO_SYSTEM
        if team_context:
            system_prompt = system_prompt + f"\n\n{team_context}"
        if task_ctx_block:
            system_prompt = system_prompt + task_ctx_block

        messages, _ = build_context(
            system_prompt, summaries, short_term, budget,
            daily_log=daily_log,
            durable_memory=durable_memory,
            retrieved_chunks=retrieved_chunks,
        )

        tools = get_tools_for_role(self.role)

        # React loop — INTERPRET → CFO/CSO → DELEGATE → REPORT
        for iteration in range(self.config.max_tool_iterations):
            resp    = await self._router.complete_full(
                messages=messages,
                agent_role=self.role,
                task_type="complex",
                max_tokens=budget.max_output_tokens,
            )
            content = resp.content

            # Detect JSON tool call
            if content.strip().startswith("{") and '"tool"' in content:
                try:
                    tool_call   = json.loads(content)
                    tool_name   = tool_call.get("tool", "")
                    tool_args   = tool_call.get("args", {})

                    # CSO check on tool execution
                    if self._cso and tool_name in ("shell_exec", "run_python", "file_write"):
                        cso = self._cso.review_tool_args(tool_name, tool_args,
                                                          agent_role=self.role)
                        if not cso.approved:
                            tool_result = {
                                "error": f"CSO blocked: {'; '.join(cso.findings)}",
                                "risk":  cso.risk_level,
                            }
                            messages.append({"role": "assistant", "content": content})
                            messages.append({"role": "tool",      "content": json.dumps(tool_result)})
                            continue

                    # For delegate_task, use retry wrapper
                    if tool_name == "delegate_task":
                        agent_target = tool_args.get("agent", "")
                        sub_task     = tool_args.get("task", {})
                        task_key     = f"{agent_target}:{hash(json.dumps(sub_task, sort_keys=True))}"
                        tool_result  = await self._dispatch_with_retry(
                            agent_target, sub_task, task_key
                        )
                    else:
                        tool_result = await self._registry.execute(
                            tool_name, tool_args, self.role, tools,
                            audit_fn=self.store.audit,
                        )

                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "tool",      "content": json.dumps(tool_result)})
                    continue
                except json.JSONDecodeError:
                    pass  # not valid JSON — treat as final answer

            # Final answer — persist and summarize (v3.6: team insight + task_ctx 기록)
            self.store.push_turn(session_id, "assistant", content, agent_role=self.role)

            # v3.6: CEO 결정을 팀 인사이트로 기록
            try:
                decision_summary = content.strip()[:200].replace("\n", " ")
                self.store.push_agent_insight(
                    session_id=session_id,
                    agent_role=self.role,
                    insight_type="decision",
                    content=decision_summary,
                )
            except Exception:
                pass

            # v3.6: 태스크 컨텍스트 파일에 CEO 응답 즉시 기록
            try:
                task_ctx = get_task_context(session_id, self.config.workspace)
                task_ctx.append(content.strip()[:150].replace("\n", " "), agent="ceo")
            except Exception:
                pass

            await maybe_summarize(
                self.store, self._router, session_id, self.role,
                every_n=self.config.memory.summarize_every_n_turns,
                config=self.config,
            )
            return {"result": content, "session_id": session_id}

        return {"result": "Max iterations reached without final answer",
                "session_id": session_id}
