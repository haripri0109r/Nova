"""Memory Engine retrieval engine – semantic ranking only."""
from __future__ import annotations

import math
from datetime import datetime
from typing import List, Optional

from .models import MemoryRecord, MemorySearchResult
from .storage import MemoryStore
from .embeddings import EmbeddingProvider
from .config import MemoryConfig
from .types import MemoryScope, MemoryType
from .exceptions import MemoryRetrievalError


class RetrievalEngine:
    """Semantic ranking engine – reads from storage, ranks, returns top‑k."""

    def __init__(
        self,
        store: MemoryStore,
        embedding_provider: EmbeddingProvider,
        config: Optional[MemoryConfig] = None,
    ) -> None:
        self._store = store
        self._embedding = embedding_provider
        self._config = config or MemoryConfig()
        # configurable candidate pool size for re‑ranking
        self._candidate_pool_size = getattr(self._config, "candidate_pool_size", 200)
        # ranking weights (could be moved to config later)
        self._weight_similarity = 0.70
        self._weight_importance = 0.20
        self._weight_recency = 0.10
        # recency half‑life in hours
        self._recency_half_life_hours = 24.0

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def search(
        self,
        query: str,
        top_k: int = 5,
        scope: Optional[MemoryScope] = None,
        memory_type: Optional[MemoryType] = None,
        session_id: Optional[str] = None,
    ) -> List[MemorySearchResult]:
        """Return top‑k memories ranked by semantic similarity, importance, recency."""
        if not query or not query.strip():
            return []

        # 1️⃣  query embedding
        query_emb = await self._generate_query_embedding(query)

        # 2️⃣  fetch candidate memories from storage (large pool)
        candidates = await self._store.list(
            limit=self._candidate_pool_size,
            scope=scope,
            memory_type=memory_type,
            session_id=session_id,
        )

        if not candidates:
            return []

        # 3️⃣  rank
        ranked = self._rank(query_emb, candidates, top_k)

        return ranked

    async def get_recent(self, limit: int = 10) -> List[MemoryRecord]:
        """Return the most recent memories (no ranking)."""
        return await self._store.list(limit=limit)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    async def _generate_query_embedding(self, query: str) -> List[float]:
        try:
            emb = await self._embedding.embed(query)
            return emb
        except Exception as exc:  # pragma: no cover
            raise MemoryRetrievalError(f"Failed to generate query embedding: {exc}") from exc

    def _is_expired(self, record: MemoryRecord) -> bool:
        """Check if a memory record has expired."""
        if record.expires_at is None:
            return False
        return datetime.utcnow() > record.expires_at

    def _rank(
        self,
        query_emb: List[float],
        candidates: List[MemoryRecord],
        top_k: int,
    ) -> List[MemorySearchResult]:
        scored: List[tuple[MemoryRecord, float]] = []
        for rec in candidates:
            if self._is_expired(rec):
                continue
            sim = self._cosine_similarity(query_emb, rec.embedding)
            if sim <= 0.0:
                continue
            recency = self._recency_score(rec.created_at)
            importance = self._importance_weight(rec.importance)
            score = (
                self._weight_similarity * sim
                + self._weight_importance * importance
                + self._weight_recency * recency
            )
            scored.append((rec, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_k]
        return [
            MemorySearchResult(memory=rec, score=score, matched_fields=["content"])
            for rec, score in top
        ]

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _recency_score(self, created_at: datetime, half_life_hours: float = 24.0) -> float:
        """Exponential decay based on age."""
        hours = (datetime.utcnow() - created_at).total_seconds() / 3600.0
        return math.exp(-hours / half_life_hours)

    def _importance_weight(self, importance: float) -> float:
        """Linear mapping 0‑1 → 0‑1 (identity, can be tweaked)."""
        return max(0.0, min(1.0, importance))


__all__ = ["RetrievalEngine"]