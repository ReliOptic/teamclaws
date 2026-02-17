"""Researcher PicoClaw: web search + summarize. (§6-2)"""
from __future__ import annotations

from typing import Any

from multiclaws.core.picoclaw import PicoClaw
from multiclaws.llm.router import LLMRouter
from multiclaws.roles.permissions import get_tools_for_role
from multiclaws.tools.registry import get_registry

RESEARCHER_SYSTEM = """You are a Researcher agent. Your job is to gather, verify, and summarize information.
Use web_fetch to retrieve URLs. Use file_read to read local files.
Return structured, factual summaries. Cite sources. Be concise."""


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
        query = task.get("query", task.get("message", ""))
        session_id = task.get("session_id", "researcher:default")

        messages = [
            {"role": "system", "content": RESEARCHER_SYSTEM},
            {"role": "user", "content": query},
        ]

        registry = get_registry()
        tools = get_tools_for_role(self.role)

        for _ in range(3):
            content = await self._router.complete(
                messages=messages,
                agent_role=self.role,
                task_type="simple",
            )
            messages.append({"role": "assistant", "content": content})
            break  # extend with tool loop if needed

        return {"result": content, "query": query}
