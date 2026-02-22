"""Communicator PicoClaw: message relay. (v3.6: team insight recording)"""
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
        session_id  = task.get("session_id", "communicator:default")
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

        # v3.6: 팀 유기체 성장 — 커뮤니케이션 결과를 공유 인사이트로 기록
        if self.store and content:
            try:
                summary = content.strip()[:150].replace("\n", " ")
                self.store.push_agent_insight(
                    session_id=session_id,
                    agent_role=self.role,
                    insight_type="task_result",
                    content=f"메시지 작성 완료 (tone={tone}): {summary}",
                )
            except Exception:
                pass  # 인사이트 기록 실패는 태스크 실패로 이어지지 않음

        return {"result": content}
