"""
CEO PicoClaw: orchestration + delegation. (§6-2)
Simple → handle directly.
Complex → decompose → delegate via task queue.
"""
from __future__ import annotations

import json
from typing import Any

from multiclaws.config import get_config
from multiclaws.core.picoclaw import PicoClaw
from multiclaws.llm.router import LLMRouter
from multiclaws.memory.summarizer import maybe_summarize
from multiclaws.memory.store import MemoryStore
from multiclaws.roles.permissions import get_tools_for_role
from multiclaws.tools.registry import get_registry

CEO_SYSTEM = """You are the CEO of TeamClaws — an AI multi-agent system.
Your job: understand the user's goal, decide if you can handle it directly or need to delegate.

Available agents you can delegate to:
- researcher: web research, information gathering
- coder: code writing, file operations, shell commands
- communicator: message drafting, notifications

Rules:
1. Prefer direct answers for simple questions (no delegation needed)
2. For complex multi-step tasks, decompose and delegate
3. ALWAYS synthesize results before responding to user
4. Track costs — avoid redundant re-prompting
5. Use delegate_task tool to assign work to other agents

Respond concisely. The user is busy."""


class CEOAgent(PicoClaw):
    role = "ceo"
    description = "Chief orchestrator — handles user requests and delegates to specialists"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._router: LLMRouter | None = None
        self._registry = None

    def run(self) -> None:
        self._router = LLMRouter(self.config)
        self._registry = get_registry()
        super().run()

    async def handle_task(self, task: dict[str, Any]) -> dict[str, Any]:
        session_id = task.get("session_id", "ceo:default:session")
        user_msg = task.get("message", task.get("content", ""))
        platform = task.get("platform", "cli")

        if not user_msg:
            return {"result": "No message provided"}

        # Persist user turn
        self.store.push_turn(session_id, "user", user_msg, agent_role=self.role)

        # Build context: summaries + short-term
        summaries = self.store.load_latest_summaries(session_id)
        short_term = self.store.get_context(session_id)

        messages: list[dict] = [{"role": "system", "content": CEO_SYSTEM}]
        if summaries:
            messages.append({
                "role": "system",
                "content": "MEMORY SUMMARY:\n" + "\n---\n".join(summaries),
            })
        messages.extend(short_term[-10:])  # last 10 turns

        # Tool schemas for CEO
        tools = get_tools_for_role(self.role)
        schemas = self._registry.schemas_for(tools) if self._registry else []

        # React loop (max 5 iterations per §2-4)
        for iteration in range(self.config.max_tool_iterations):
            resp = await self._router.complete_full(
                messages=messages,
                agent_role=self.role,
                task_type="complex",
            )
            content = resp.content

            # Check for tool call (simplified — extend with function calling if needed)
            if content.strip().startswith("{") and '"tool"' in content:
                try:
                    tool_call = json.loads(content)
                    tool_name = tool_call.get("tool", "")
                    tool_args = tool_call.get("args", {})
                    tool_result = await self._registry.execute(
                        tool_name, tool_args, self.role, tools,
                        audit_fn=self.store.audit,
                    )
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "tool", "content": json.dumps(tool_result)})
                    continue
                except json.JSONDecodeError:
                    pass

            # Final answer
            self.store.push_turn(session_id, "assistant", content, agent_role=self.role)

            # Auto-summarize if needed
            if self._router:
                await maybe_summarize(
                    self.store, self._router, session_id, self.role,
                    every_n=self.config.memory.summarize_every_n_turns,
                )

            return {"result": content, "session_id": session_id}

        return {"result": "Max iterations reached", "session_id": session_id}
