"""
L2 Daily Log: workspace/memory/YYYY-MM-DD.md 파일 기반 일일 로그.

설계 원칙:
  - 세션 시작 시 오늘 + 어제 자동 로드 → context_builder에 전달
  - Agentic Compaction이 핵심 사실을 이 파일에 타임스탬프와 함께 기록
  - 마크다운 헤딩(##) 기준으로 구조화 → FTS5 청킹 친화적

파일 경로: {workspace}/memory/YYYY-MM-DD.md
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiclaws.config import PicoConfig


def get_memory_dir(config: "PicoConfig") -> Path:
    d = config.workspace / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_daily_log_path(config: "PicoConfig", d: date | None = None) -> Path:
    d = d or date.today()
    return get_memory_dir(config) / f"{d.isoformat()}.md"


def append_to_daily_log(config: "PicoConfig", content: str, heading: str = "") -> None:
    """
    핵심 사실을 오늘의 L2 로그에 추가.
    Agentic Compaction 완료 후 호출된다.

    Args:
        config:   PicoConfig (workspace 경로 제공)
        content:  마크다운 형식 요약 텍스트
        heading:  섹션 제목 (타임스탬프 자동 포함)
    """
    path = get_daily_log_path(config)
    ts = datetime.now().strftime("%H:%M")
    title = f"[{ts}] {heading}" if heading else f"[{ts}] Compaction"
    entry = f"\n## {title}\n\n{content.strip()}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def load_recent_daily_logs(config: "PicoConfig", n_days: int = 2) -> str:
    """
    최근 n_days 일치 로그를 합쳐서 반환.
    context_builder에서 L2 슬롯에 삽입한다.

    Returns:
        합쳐진 마크다운 문자열 (오래된 것 먼저). 없으면 "".
    """
    today = date.today()
    combined: list[str] = []
    for i in range(n_days - 1, -1, -1):  # n-1 → 0 (오래된 것 먼저)
        path = get_daily_log_path(config, today - timedelta(days=i))
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                combined.append(f"# Daily Log: {(today - timedelta(days=i)).isoformat()}\n\n{text}")
    return "\n\n---\n\n".join(combined)


def get_daily_log_stats(config: "PicoConfig") -> dict:
    """오늘 로그 파일 상태 요약 (CEO status 보고용)."""
    path = get_daily_log_path(config)
    if not path.exists():
        return {"exists": False, "size_bytes": 0, "sections": 0}
    text = path.read_text(encoding="utf-8")
    sections = text.count("\n## ")
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": len(text.encode()),
        "sections": sections,
        "date": date.today().isoformat(),
    }
