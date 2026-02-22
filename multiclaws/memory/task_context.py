"""
v3.6 Task Context: mybot INSTRUNCTION.md 패턴 적용.

핵심 아이디어:
  - 각 태스크/대화 세션마다 workspace/context/{session_id[-8:]}.md 생성
  - 대화 진행 중 핵심 결정·발견을 즉시 기록 (fire-and-forget X — 즉시 append)
  - CEO/Expert 에이전트가 시스템 프롬프트에 이 파일을 항상 주입
  - 2600자 제한으로 토큰 효율 유지 (mybot 벤치마크 기반)

사용법:
  ctx = TaskContext(session_id, workspace_path)
  ctx.append("사용자가 Python 3.11 환경 사용 중임을 확인")
  ctx.append("CTO에게 Dockerfile 분석 태스크 위임 완료")
  system_prompt += ctx.as_system_block()
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_MAX_CHARS = 2600  # mybot 벤치마크 기반 — LLM 컨텍스트 효율 최적값
_CONTEXT_DIR_NAME = "context"


class TaskContext:
    """
    세션별 즉시 기록 컨텍스트 파일.
    마크다운 형식, 최대 _MAX_CHARS 문자 유지 (초과 시 오래된 항목 자동 압축).
    """

    def __init__(self, session_id: str, workspace: str | Path) -> None:
        self.session_id = session_id
        self._short_id = session_id[-8:] if len(session_id) >= 8 else session_id
        self._dir = Path(workspace) / _CONTEXT_DIR_NAME
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{self._short_id}.md"
        self._ensure_header()

    # ── 파일 초기화 ──────────────────────────────────────────────────────
    def _ensure_header(self) -> None:
        """파일이 없으면 헤더만 생성."""
        if not self._path.exists():
            date_str = datetime.now().strftime("%Y-%m-%d")
            self._path.write_text(
                f"# Task Context — {self._short_id}\n"
                f"_Created: {date_str}_\n\n",
                encoding="utf-8",
            )

    # ── 기록 API ─────────────────────────────────────────────────────────
    def append(self, note: str, agent: str = "") -> None:
        """
        핵심 발견/결정을 즉시 파일에 기록.
        초과 시 _trim()으로 오래된 항목 제거.
        """
        ts = datetime.now().strftime("%H:%M")
        prefix = f"[{ts}]" + (f" **{agent}**" if agent else "")
        entry = f"- {prefix}: {note.strip()}\n"

        with self._path.open("a", encoding="utf-8") as f:
            f.write(entry)

        self._trim()

    def update_section(self, heading: str, content: str) -> None:
        """
        ## {heading} 섹션을 upsert.
        태스크 상태, 환경 정보 등 덮어쓰기가 필요한 정보에 사용.
        """
        text = self._path.read_text(encoding="utf-8")
        pattern = rf"(## {re.escape(heading)}\n)(.*?)(?=\n## |\Z)"
        new_section = f"## {heading}\n{content.strip()}\n"

        if re.search(pattern, text, re.DOTALL):
            text = re.sub(pattern, new_section, text, flags=re.DOTALL)
        else:
            text += f"\n{new_section}"

        self._path.write_text(text, encoding="utf-8")
        self._trim()

    # ── 읽기 API ─────────────────────────────────────────────────────────
    def load(self) -> str:
        """현재 컨텍스트 파일 전체 읽기."""
        if self._path.exists():
            return self._path.read_text(encoding="utf-8")
        return ""

    def as_system_block(self) -> str:
        """
        시스템 프롬프트에 주입할 형태로 반환.
        내용이 없으면 빈 문자열.
        """
        content = self.load().strip()
        if not content:
            return ""
        return f"\n\n---\n## 현재 태스크 컨텍스트\n{content}\n---\n"

    def clear(self) -> None:
        """세션 종료 시 컨텍스트 초기화 (헤더만 유지)."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        self._path.write_text(
            f"# Task Context — {self._short_id}\n"
            f"_Cleared: {date_str}_\n\n",
            encoding="utf-8",
        )

    # ── 자동 트림 ─────────────────────────────────────────────────────────
    def _trim(self) -> None:
        """
        _MAX_CHARS 초과 시 오래된 bullet 항목부터 제거.
        헤더와 ## 섹션은 항상 보존.
        """
        text = self._path.read_text(encoding="utf-8")
        if len(text) <= _MAX_CHARS:
            return

        lines = text.splitlines(keepends=True)

        # 헤더 (첫 3줄) + 섹션 구분
        header_lines: list[str] = []
        body_lines: list[str] = []
        in_header = True
        for i, line in enumerate(lines):
            if in_header and i < 3:
                header_lines.append(line)
            else:
                in_header = False
                body_lines.append(line)

        # bullet 항목(- 로 시작)만 제거 대상
        bullet_indices = [
            i for i, l in enumerate(body_lines)
            if l.startswith("- [")
        ]

        removed = 0
        while len("".join(header_lines + body_lines)) > _MAX_CHARS and bullet_indices:
            idx = bullet_indices.pop(0)
            body_lines[idx] = ""  # 빈 줄로 교체 (인덱스 유지)
            removed += 1

        self._path.write_text("".join(header_lines + body_lines), encoding="utf-8")


# ── 모듈 레벨 헬퍼 ────────────────────────────────────────────────────────
def get_task_context(session_id: str, workspace: str | Path) -> TaskContext:
    """편의 팩토리 함수 — 단순 import 후 바로 사용 가능."""
    return TaskContext(session_id, workspace)
