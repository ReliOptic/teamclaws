"""
시맨틱 청킹: 마크다운 헤딩(## / #) 기준으로 분리.
SHA-256 chunk_id로 중복 색인 방지.

사용처:
  - L3 MEMORY.md 변경 시 COO 재색인 트리거
  - Agentic Compaction 결과 색인
"""
from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiclaws.memory.store import MemoryStore


def chunk_markdown(text: str) -> list[dict]:
    """
    마크다운 헤딩(#, ##, ###) 기준으로 섹션 분리.

    Returns:
        [{"chunk_id": str, "heading": str, "chunk_text": str}, ...]
    """
    # # 또는 ## 또는 ### 헤딩 앞에서 분리
    pattern = re.compile(r'\n(?=#{1,3} )', re.MULTILINE)
    raw_sections = pattern.split(text)

    chunks: list[dict] = []
    for section in raw_sections:
        section = section.strip()
        if not section:
            continue

        # 첫 줄이 헤딩인지 확인
        first_line = section.split('\n', 1)[0]
        if first_line.startswith('#'):
            heading = first_line.lstrip('#').strip()
        else:
            heading = ""

        # SHA-256 (앞 16자) — 내용 기반 고유 ID
        chunk_id = hashlib.sha256(section.encode("utf-8")).hexdigest()[:16]
        chunks.append({
            "chunk_id": chunk_id,
            "heading":  heading,
            "chunk_text": section,
        })

    return chunks


def index_markdown_to_fts(store: "MemoryStore", text: str) -> int:
    """
    마크다운을 청킹하여 memory_chunks_fts에 색인.
    chunk_id가 이미 존재하면 스킵 (멱등성 보장).

    Returns:
        새로 색인된 청크 수
    """
    chunks = chunk_markdown(text)
    new_count = 0

    for chunk in chunks:
        # chunk_id 기반 중복 체크
        with store._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM memory_chunks_fts WHERE chunk_id = ?",
                (chunk["chunk_id"],),
            ).fetchone()

            if not exists:
                conn.execute(
                    "INSERT INTO memory_chunks_fts(chunk_text, heading, chunk_id) "
                    "VALUES (?, ?, ?)",
                    (chunk["chunk_text"], chunk["heading"], chunk["chunk_id"]),
                )
                new_count += 1

    return new_count


def reindex_memory_file(store: "MemoryStore", file_path: str) -> int:
    """
    파일 경로에서 마크다운을 읽어 전체 재색인.
    COO 재색인 콜백에서 사용.

    Returns:
        새로 색인된 청크 수 (0이면 변경 없음)
    """
    from pathlib import Path
    path = Path(file_path)
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    return index_markdown_to_fts(store, text)
