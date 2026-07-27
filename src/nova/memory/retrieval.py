"""
Memory retrieval and ranking logic.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any, Tuple
import math
import logging
from datetime import datetime

from .models import MemoryRecord, MemorySearchParams, MemorySearchResult
from .embeddings import EmbeddingProvider


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not vec1 or not vec2:
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(x * x for x in vec1))
    norm2 = math.sqrt(sum(x * x for x in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


class RetrievalEngine:
    """Handles memory search and ranking."""

    def __init__(self, store, embedding_provider):
        self._store = store
        self._embedding_provider = embedding_provider

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not vec1 or not vec2:
            return 0.0
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(x * x for x in vec1))
        norm2 = math.sqrt(sum(x * x for x in vec2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    def _recency_score(self, created_at: datetime, half_life_hours: float = 24.0) -> float:
        """Calculate recency score with exponential decay."""
        hours_ago = (datetime.utcnow() - created_at).total_seconds() / 3600
        return math.exp(-hours_ago / half_life_hours)

    def _importance_weight(self, importance: float) -> float:
        """Convert importance (0-1) to weight multiplier."""
        return 0.5 + importance  # 0.5 to 1.5

    async def search(
        self,
        query: str,
        top_k: int = 5,
        scope: Optional[str] = None,
        type_: Optional[str] = None,
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_importance: float = 0.0,
        min_score: float = 0.0,
    ) -> List[Tuple[MemoryRecord, float]]:
        """Search memories and return ranked results."""
        # Generate query embedding
        query_embedding = await self._generate_query_embedding(query)
        
        # Get candidate memories from store
        candidates = await self._store.search(
            query="",  # We'll do our own filtering
            top_k=100,  # Get more candidates for re-ranking
            scope=None,
            type_=None,
            session_id=None,
            tags=None,
            min_importance=0.0,
            min_score=0.0,
        )

        # Filter by parameters
        filtered = []
        for record in candidates:
            if record.is_expired():
                continue
            if scope and record.scope != scope:
                continue
            if type_ and record.type != type_:
                continue
            if session_id and record.session_id != session_id:
                continue
            if tags and not any(tag in record.tags for tag in tags):
                continue
            if record.importance < min_importance:
                continue
            filtered.append(record)

        # Score each candidate
        results = []
        for record in filtered:
            # Semantic similarity
            semantic_score = 0.0
            if record.embedding and len(record.embedding) > 0:
                semantic_score = cosine_similarity(query_embedding, record.embedding)
            
            # Recency score
            recency_score = self._recency_score(record.created_at)
            
            # Importance weight
            importance_weight = self._importance_weight(record.importance)
            
            # Tag matching bonus
            tag_bonus = 0.0
            if tags and record.tags:
                matching_tags = set(record.tags) & set(tags)
                tag_bonus = 0.1 * len(matching_tags)
            
            # Combined score
            score = (semantic_score * 0.5 + recency_score * 0.2 + 
                    importance_weight * 0.2 + 0.1)  # Base score
            
            if score >= min_score:
                results.append((record, score))
        
        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        
        # Apply min_score filter
        filtered = [(r, s) for r, s in results if s >= 0.0]
        
        return filtered[:top_k]

    async def _generate_query_embedding(self, query: str) -> List[float]:
        """Generate embedding for query text."""
        try:
            embeddings = await self._embedding_provider.generate_embeddings([query])
            return embeddings[0] if embeddings else []
        except Exception as e:
            logging.warning(f"Failed to generate query embedding: {e}")
            return []