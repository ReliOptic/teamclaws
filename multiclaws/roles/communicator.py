"""Communicator PicoClaw: message relay. (§6-2)"""
from __future__ import annotations

from typing import Any

from multiclaws.core.picoclaw import PicoClaw
from multiclaws.llm.router import LLMRouter

COMMUNICATOR_SYSTEM = """You are a Communicator agent. Your job is to draft, format, and relay messages.
Write clear, concise, human-friendly content. Adapt tone to context (formal/casual)."""


class CommunicatorAgent(PicoClaw):
    role = "communicator"
    description = "Message drafting and notification relay specialist"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._router: LLMRouter | None = None

    def run(self) -> None:
        self._router = LLMRouter(self.config)
        super().run()

    async def handle_task(self, task: dict[str, Any]) -> dict[str, Any]:
        content_req = task.get("content", task.get("message", ""))
        tone = task.get("tone", "professional")

        messages = [
            {"role": "system", "content": COMMUNICATOR_SYSTEM},
            {"role": "user", "content": f"Tone: {tone}\n\n{content_req}"},
        ]

        content = await self._router.complete(
            messages=messages,
            agent_role=self.role,
            task_type="fast",
        )
        return {"result": content}
