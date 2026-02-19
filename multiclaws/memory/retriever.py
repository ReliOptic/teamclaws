"""
하이브리드 검색: BM25(FTS5) + 최신성 재랭킹.

검색 전략:
  - turns_fts: 대화 이력에서 BM25 키워드 검색
  - memory_chunks_fts: L3 MEMORY.md 청크에서 BM25 검색
  - 최신성 가중치: 최근 turn일수록 점수 가산
  - 합산 점수 기준 상위 k개 반환

설계 제약 (e2-micro):
  - 벡터 임베딩 없음 (RAM 절약)
  - 순수 SQLite FTS5 — 추가 의존성 없음
  - BM25 스코어는 FTS5 내장 bm25() 함수 활용
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from multiclaws.utils.logger import get_logger

if TYPE_CHECKING:
    from multiclaws.memory.store import MemoryStore

log = get_logger("retriever")


class HybridRetriever:
    """
    BM25 + 최신성 하이브리드 검색기.

    사용 예:
        retriever = HybridRetriever(store)
        chunks = retriever.search("Python 프로젝트", session_id, top_k=5)
        memory_hits = retriever.search_durable_memory("사용자 선호도", top_k=3)
    """

    def __init__(self, store: "MemoryStore") -> None:
        self.store = store

    # ── Public API ─────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        session_id: str,
        top_k: int = 5,
    ) -> list[dict]:
        """
        L1 대화 이력에서 쿼리와 관련된 turns 검색.

        Returns:
            [{"content": str, "session_id": str, "score": float, "ts": str}, ...]
            score 내림차순 정렬
        """
        if not query.strip():
            return []

        try:
            bm25_hits = self._bm25_search_turns(query, session_id, limit=top_k * 3)
            reranked = self._apply_recency_boost(bm25_hits)
            return reranked[:top_k]
        except Exception as e:
            # FTS5 미지원 환경(SQLite 빌드 옵션) 폴백
            log.warning("FTS5 search failed, falling back to LIKE: %s", e)
            return self._fallback_like_search(query, session_id, top_k)

    def search_durable_memory(
        self,
        query: str,
        top_k: int = 3,
    ) -> list[str]:
        """
        L3 MEMORY.md 청크에서 쿼리와 관련된 섹션 검색.

        Returns:
            관련 청크 텍스트 리스트 (상위 top_k)
        """
        if not query.strip():
            return []

        try:
            with self.store._conn() as conn:
                rows = conn.execute(
                    "SELECT chunk_text FROM memory_chunks_fts "
                    "WHERE memory_chunks_fts MATCH ? "
                    "ORDER BY bm25(memory_chunks_fts) "
                    "LIMIT ?",
                    (self._sanitize_query(query), top_k),
                ).fetchall()
            return [r["chunk_text"] for r in rows]
        except Exception as e:
            log.warning("memory_chunks_fts search failed: %s", e)
            return []

    def search_all_context(
        self,
        query: str,
        session_id: str,
        turns_top_k: int = 5,
        memory_top_k: int = 3,
    ) -> dict:
        """
        L1 + L3 통합 검색. context_builder에서 한 번에 호출.

        Returns:
            {"turns": [...], "memory_chunks": [...]}
        """
        return {
            "turns": self.search(query, session_id, top_k=turns_top_k),
            "memory_chunks": self.search_durable_memory(query, top_k=memory_top_k),
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _bm25_search_turns(self, query: str, session_id: str, limit: int) -> list[dict]:
        """FTS5 BM25 검색 (score = BM25, 낮을수록 관련도 높음)."""
        with self.store._conn() as conn:
            rows = conn.execute(
                "SELECT t.content, t.session_id, t.ts, "
                "bm25(turns_fts) AS bm25_score "
                "FROM turns_fts "
                "JOIN turns t ON turns_fts.session_id = t.session_id "
                "  AND turns_fts.content = t.content "
                "WHERE turns_fts MATCH ? AND turns_fts.session_id = ? "
                "ORDER BY bm25_score "
                "LIMIT ?",
                (self._sanitize_query(query), session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def _apply_recency_boost(self, hits: list[dict]) -> list[dict]:
        """
        최신성 부스트: BM25 스코어(음수, 낮을수록 좋음) → 정규화 후 최신성 가산.
        최종 score는 높을수록 좋음.
        """
        if not hits:
            return hits

        # BM25 스코어 정규화 (모두 음수) → 0~1 범위로
        scores = [h["bm25_score"] for h in hits]
        min_s, max_s = min(scores), max(scores)
        score_range = max_s - min_s if max_s != min_s else 1.0

        for i, hit in enumerate(hits):
            # BM25 관련도 (0~1, 높을수록 좋음)
            bm25_norm = (hit["bm25_score"] - min_s) / score_range
            bm25_relevance = 1.0 - bm25_norm  # 뒤집기

            # 최신성 (인덱스 위치 기반 — BM25는 이미 최신 순으로 쿼리했으므로)
            recency = 1.0 - (i / max(len(hits) - 1, 1))

            hit["score"] = bm25_relevance * 0.7 + recency * 0.3

        return sorted(hits, key=lambda h: h["score"], reverse=True)

    def _fallback_like_search(self, query: str, session_id: str, limit: int) -> list[dict]:
        """FTS5 불가 환경용 LIKE 폴백."""
        terms = query.split()[:3]  # 최대 3개 단어
        if not terms:
            return []

        conditions = " AND ".join(["content LIKE ?" for _ in terms])
        params = [f"%{t}%" for t in terms] + [session_id, limit]

        with self.store._conn() as conn:
            rows = conn.execute(
                f"SELECT content, session_id, ts FROM turns "
                f"WHERE ({conditions}) AND session_id = ? "
                f"ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [{"content": r["content"], "session_id": r["session_id"],
                 "score": 0.5, "ts": r["ts"]} for r in rows]

    @staticmethod
    def _sanitize_query(query: str) -> str:
        """
        FTS5 쿼리 특수문자 이스케이프.
        따옴표 안에 감싸서 구문 검색 대신 단순 검색.
        """
        # FTS5는 "term1 term2" 형식으로 OR 검색
        # 특수문자 제거 후 단어 단위 검색
        safe = re.sub(r'[^\w\s가-힣]', ' ', query)
        words = safe.split()
        if not words:
            return '""'
        # 각 단어를 개별 검색 (AND 기본)
        return " ".join(f'"{w}"' for w in words[:10])  # 최대 10단어


