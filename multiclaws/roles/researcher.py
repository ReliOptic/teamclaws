"""Researcher PicoClaw: web search + summarize. (v3.6: team insight recording)"""
from __future__ import annotations

import json
from typing import Any

from multiclaws.core.picoclaw import PicoClaw
from multiclaws.llm.router import LLMRouter
from multiclaws.roles.permissions import get_tools_for_role
from multiclaws.tools.registry import get_registry

RESEARCHER_SYSTEM = """You are a Researcher agent. Your job is to gather, verify, and summarize information.
Use web_fetch to retrieve URLs. Use file_read to read local files.
Return structured, factual summaries. Cite sources. Be concise.

To use a tool, respond with JSON only (no other text):
{"tool": "web_fetch", "args": {"url": "https://example.com"}}

When done, respond with plain text (your final answer)."""


class ResearcherAgent(PicoClaw):
    role = "researcher"
    description = "Web research and information gathering specialist"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._router: LLMRouter | None = None

    def run(self) -> None:
        self._router = LLMRouter(self.config)
        super().run()

    async def handle_task(self, task: dict[str, Any]) -> dict[str, Any]:
        query      = task.get("query", task.get("message", ""))
        session_id = task.get("session_id", "researcher:default")
        # CFO-injected model parameters (optional)
        task_type  = task.get("_task_type", "simple")
        max_tokens = task.get("_max_tokens", self.config.agent_budget(self.role).max_output_tokens)

        messages = [
            {"role": "system", "content": RESEARCHER_SYSTEM},
            {"role": "user",   "content": query},
        ]

        registry = get_registry()
        tools = get_tools_for_role(self.role)
        content = ""

        for _ in range(self.config.max_tool_iterations):
            content = await self._router.complete(
                messages=messages,
                agent_role=self.role,
                task_type=task_type,
                max_tokens=max_tokens,
            )
            messages.append({"role": "assistant", "content": content})

            if content.strip().startswith("{") and '"tool"' in content:
                try:
                    tool_call = json.loads(content)
                    tool_name = tool_call.get("tool", "")
                    tool_args = tool_call.get("args", {})
                    tool_result = await registry.execute(
                        tool_name, tool_args, self.role, tools,
                        audit_fn=self.store.audit if self.store else None,
                    )
                    messages.append({"role": "tool", "content": json.dumps(tool_result)})
                    continue
                except json.JSONDecodeError:
                    pass

            # Final answer (plain text)
            break

        # v3.6: 팀 유기체 성장 — 리서치 결과를 공유 인사이트로 기록
        if self.store and content:
            try:
                summary = content.strip()[:200].replace("\n", " ")
                self.store.push_agent_insight(
                    session_id=session_id,
                    agent_role=self.role,
                    insight_type="task_result",
                    content=f"리서치 완료 — {query[:80]!r}: {summary}",
                )
            except Exception:
                pass  # 인사이트 기록 실패는 태스크 실패로 이어지지 않음

        return {"result": content, "query": query}
