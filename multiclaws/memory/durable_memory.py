"""
L3 Durable Memory: workspace/MEMORY.md — 사용자 선호·규칙·영구 사실.

설계 원칙:
  - 파일 기반: 사용자가 직접 편집 가능 (투명성)
  - Agentic Compaction이 KEY FACTS / USER PREFERENCES 섹션 업데이트
  - COO(watchdog)가 파일 변경 감지 → FTS5 자동 재색인
  - SHA-256 해시로 중복 섹션 방지

파일 경로: {workspace}/MEMORY.md
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiclaws.config import PicoConfig

# 표준 섹션 헤딩
SECTION_KEY_FACTS = "KEY FACTS"
SECTION_USER_PREFS = "USER PREFERENCES"
SECTION_OPEN_TASKS = "OPEN TASKS"
SECTION_CONCLUSIONS = "CONCLUSIONS"

_STANDARD_SECTIONS = [
    SECTION_KEY_FACTS,
    SECTION_USER_PREFS,
    SECTION_OPEN_TASKS,
    SECTION_CONCLUSIONS,
]


def get_memory_file(config: "PicoConfig") -> Path:
    return config.workspace / "MEMORY.md"


def load_durable_memory(config: "PicoConfig") -> str:
    """
    MEMORY.md 전체를 문자열로 반환.
    없으면 빈 문자열.
    """
    path = get_memory_file(config)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _parse_sections(text: str) -> dict[str, str]:
    """
    ## 섹션 제목 → 내용 딕셔너리로 파싱.
    중첩 헤딩(###)은 내용에 포함.
    """
    pattern = re.compile(r'^## (.+?)$', re.MULTILINE)
    matches = list(pattern.finditer(text))
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[heading] = text[start:end].strip()
    return sections


def _build_file(sections: dict[str, str], extra_intro: str = "") -> str:
    """섹션 딕셔너리를 마크다운 파일 문자열로 재조립."""
    lines = ["# TeamClaws — Persistent Memory\n"]
    if extra_intro:
        lines.append(extra_intro + "\n")
    lines.append(f"_Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n")

    # 표준 섹션 순서 보장
    ordered_keys = [k for k in _STANDARD_SECTIONS if k in sections]
    other_keys = [k for k in sections if k not in _STANDARD_SECTIONS]

    for key in ordered_keys + other_keys:
        content = sections[key].strip()
        if content:
            lines.append(f"\n## {key}\n\n{content}\n")

    return "\n".join(lines)


def upsert_memory_section(config: "PicoConfig", heading: str, content: str) -> bool:
    """
    ## {heading} 섹션을 업데이트하거나 추가.
    내용이 동일하면 (SHA-256 비교) 스킵 → False 반환.
    변경된 경우 → True 반환.

    Args:
        config:  PicoConfig
        heading: 섹션 제목 (예: "KEY FACTS")
        content: 마크다운 내용
    """
    content = content.strip()
    if not content:
        return False

    path = get_memory_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 기존 파일 로드
    existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    sections = _parse_sections(existing_text)

    # 해시 비교 — 동일하면 스킵
    new_hash = hashlib.sha256(content.encode()).hexdigest()
    old_hash = hashlib.sha256(sections.get(heading, "").encode()).hexdigest()
    if new_hash == old_hash:
        return False

    # 업데이트
    sections[heading] = content
    new_text = _build_file(sections)
    path.write_text(new_text, encoding="utf-8")
    return True


def merge_compaction_result(config: "PicoConfig", compaction_text: str) -> dict[str, bool]:
    """
    Agentic Compaction 결과(마크다운)를 파싱하여 각 섹션을 MEMORY.md에 병합.

    Returns:
        {section_heading: was_updated} 딕셔너리
    """
    sections = _parse_sections(compaction_text)
    results: dict[str, bool] = {}
    for heading, content in sections.items():
        if content.strip():
            results[heading] = upsert_memory_section(config, heading, content)
    return results


def get_memory_stats(config: "PicoConfig") -> dict:
    """MEMORY.md 상태 요약 (CEO status 보고용)."""
    path = get_memory_file(config)
    if not path.exists():
        return {"exists": False, "size_bytes": 0, "sections": []}
    text = path.read_text(encoding="utf-8")
    sections = list(_parse_sections(text).keys())
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": len(text.encode()),
        "sections": sections,
        "section_count": len(sections),
    }
