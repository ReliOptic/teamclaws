"""
CEO PicoClaw: Chairman-CEO-Expert 3계층 구조의 중재자. (§6-2 v3.3)

역할 정의:
  - Chairman(사용자)의 모호한 의도를 구체적 Task로 변환(Alignment)
  - "누가 이 일을 해야 하는가?" 판단 후 Expert 호출 (Blocking = 보고 체계)
  - 스스로 실행하지 않음. 결과를 수신·종합하여 Chairman에게 보고

의도적으로 Blocking:
  _inline_dispatch()는 하위 에이전트 결과를 기다린 뒤 CEO가 종합.
  백그라운드 루프 없음 — OS 스케줄러(cron/at)를 쓰는 것이 더 지능적.
"""
from __future__ import annotations

import json
from typing import Any

from multiclaws.core.picoclaw import PicoClaw
from multiclaws.llm.router import LLMRouter
from multiclaws.memory.context_builder import build_context
from multiclaws.memory.summarizer import maybe_summarize
from multiclaws.roles.permissions import get_tools_for_role
from multiclaws.tools.builtins.delegate import DelegateTaskTool
from multiclaws.tools.registry import Tool, get_registry


# ── CreatePlanTool ─────────────────────────────────────────────────────────────
class CreatePlanTool(Tool):
    """
    CEO가 Chairman에게 실행 계획을 제시하고 Task Queue에 등록한다.
    CEO 자신이 실행하는 게 아니라 Expert 순서와 의존관계를 정의한다.
    """
    name = "create_plan"
    description = (
        "Break a complex goal into ordered subtasks, assign each to an expert agent, "
        "and persist to the task queue with dependency links. "
        "Use delegate_task to actually execute each step after planning."
    )
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "High-level goal to achieve"},
            "steps": {
                "type": "array",
                "description": "Ordered list of expert subtasks",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent":           {"type": "string",
                                            "description": "researcher | coder | communicator"},
                        "task":            {"type": "object",
                                            "description": "Task payload for the agent"},
                        "depends_on_step": {"type": "integer",
                                            "description": "0-based index of step this depends on"},
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
CEO_SYSTEM = """You are the CEO of TeamClaws — the Chief of Staff between the user (Chairman) and expert agents.

Your role:
1. UNDERSTAND: Clarify the Chairman's intent. Ask exactly one clarifying question if the goal is ambiguous.
2. JUDGE: Decide whether to answer directly (simple) or delegate to experts (complex).
3. DELEGATE: Use delegate_task to assign work to the right expert. WAIT for their result.
4. REPORT: Synthesize expert results into a clear, concise answer for the Chairman.

Expert agents available:
- researcher: web research, URL fetching, information gathering
- coder: code writing, file operations, shell execution, run_python
- communicator: message drafting, documentation, notifications

Decision rules:
- Direct answer: factual questions, explanations, opinions — no tool needed
- Delegate: anything requiring code execution, web access, file I/O, multi-step workflows
- Plan first: use create_plan for goals with 3+ steps, then execute each step via delegate_task

You do NOT run code or fetch URLs yourself. You coordinate.
When delegating, always wait for the result and include it in your response to the Chairman.
Be concise. The Chairman is busy."""


# ── CEOAgent ───────────────────────────────────────────────────────────────────
class CEOAgent(PicoClaw):
    role = "ceo"
    description = "Chief of Staff — translates Chairman intent into Expert tasks, synthesizes results"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._router: LLMRouter | None = None
        self._registry = None

    def run(self) -> None:
        self._router = LLMRouter(self.config)
        self._registry = get_registry()
        # Wire delegate dispatcher (Blocking = 보고 체계 안전장치)
        self._inject_delegate_dispatcher()
        # CreatePlanTool needs store — register after store is ready
        self._registry.register(CreatePlanTool(store=self.store))
        super().run()

    def _inject_delegate_dispatcher(self) -> None:
        """Wire inline blocking dispatcher into DelegateTaskTool."""
        delegate_tool = self._registry.get("delegate_task")
        if isinstance(delegate_tool, DelegateTaskTool):
            delegate_tool._dispatcher = self._inline_dispatch

    async def _inline_dispatch(self, agent_role: str, task: dict) -> dict:
        """
        Dispatch a task to an Expert and BLOCK until result is received.
        This is intentional — CEO must wait for Expert's report before
        synthesizing a response for the Chairman.
        """
        from multiclaws.roles.coder import CoderAgent
        from multiclaws.roles.researcher import ResearcherAgent

        agent_map: dict[str, type] = {
            "researcher": ResearcherAgent,
            "coder":      CoderAgent,
        }
        cls = agent_map.get(agent_role)
        if cls is None:
            return {"error": f"Unknown expert role: '{agent_role}'. "
                             f"Available: {list(agent_map)}"}

        expert = cls(config=self.config)
        expert._store = self.store          # share store for cost/audit logging
        expert._router = LLMRouter(self.config)
        return await expert.handle_task(task)

    async def handle_task(self, task: dict[str, Any]) -> dict[str, Any]:
        session_id = task.get("session_id", "ceo:default:session")
        user_msg   = task.get("message", task.get("content", ""))

        if not user_msg:
            return {"result": "No message provided"}

        # Persist Chairman's message
        self.store.push_turn(session_id, "user", user_msg, agent_role=self.role)

        # Build token-budgeted context
        budget     = self.config.agent_budget(self.role)
        summaries  = self.store.load_latest_summaries(session_id)
        short_term = self.store.get_context(session_id)
        messages, _ = build_context(CEO_SYSTEM, summaries, short_term, budget)

        tools   = get_tools_for_role(self.role)

        # React loop — CEO judges, delegates, waits, synthesizes
        for _ in range(self.config.max_tool_iterations):
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
                    tool_result = await self._registry.execute(
                        tool_name, tool_args, self.role, tools,
                        audit_fn=self.store.audit,
                    )
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "tool",      "content": json.dumps(tool_result)})
                    continue
                except json.JSONDecodeError:
                    pass  # not valid JSON → treat as final answer

            # Final answer — persist and summarize if needed
            self.store.push_turn(session_id, "assistant", content, agent_role=self.role)
            await maybe_summarize(
                self.store, self._router, session_id, self.role,
                every_n=self.config.memory.summarize_every_n_turns,
            )
            return {"result": content, "session_id": session_id}

        return {"result": "Max iterations reached without final answer",
                "session_id": session_id}
