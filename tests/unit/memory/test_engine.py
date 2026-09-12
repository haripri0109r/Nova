"""
Unit tests for MemoryEngine initialization and basic operations.
"""
import sys
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Mock heavy dependencies
sys.modules['llama_cpp'] = MagicMock()
sys.modules['torch'] = MagicMock()
sys.modules['cv2'] = MagicMock()
sys.modules['faster_whisper'] = MagicMock()
sys.modules['sounddevice'] = MagicMock()
sys.modules['elevenlabs'] = MagicMock()
sys.modules['apscheduler'] = MagicMock()
sys.modules['apscheduler.schedulers.asyncio'] = MagicMock()
sys.modules['apscheduler.triggers'] = MagicMock()
sys.modules['apscheduler.triggers.cron'] = MagicMock()
sys.modules['apscheduler.triggers.interval'] = MagicMock()
sys.modules['apscheduler.triggers.date'] = MagicMock()
sys.modules['wmi'] = MagicMock()
sys.modules['pycaw'] = MagicMock()
sys.modules['comtypes'] = MagicMock()
sys.modules['win32com'] = MagicMock()
sys.modules['win32com.client'] = MagicMock()

import asyncio
from src.nova.memory import (
    MemoryEngine,
    InMemoryStore,
    DefaultEmbeddingProvider,
    MemoryRecord,
    MemoryScope,
    MemoryType,
    MemoryNotFoundError,
)


class TestMemoryEngineInit:
    """Tests for MemoryEngine initialization."""

    @pytest.mark.asyncio
    async def test_initialize_with_defaults(self):
        """Test MemoryEngine initializes with default components."""
        engine = MemoryEngine()
        await engine.initialize()
        
        assert engine._initialized is True
        assert engine._store is not None
        assert engine._embedding_provider is not None
        assert isinstance(engine._store, InMemoryStore)
        assert isinstance(engine._embedding_provider, DefaultEmbeddingProvider)
        
        # Cleanup
        await engine.cleanup()

    @pytest.mark.asyncio
    async def test_initialize_with_custom_store(self):
        """Test MemoryEngine initializes with custom store."""
        custom_store = Mock()
        custom_store.create = AsyncMock()
        custom_store.get = AsyncMock()
        custom_store.update = AsyncMock()
        custom_store.delete = AsyncMock()
        custom_store.search = AsyncMock(return_value=[])
        custom_store.get_recent = AsyncMock(return_value=[])
        custom_store.filter = AsyncMock(return_value=[])
        custom_store.clear_session = AsyncMock(return_value=0)
        custom_store.clear_all = AsyncMock(return_value=0)
        custom_store.cleanup_expired = AsyncMock(return_value=0)
        custom_store.get_stats = AsyncMock(return_value={})
        custom_store.health_check = AsyncMock(return_value={"status": "healthy"})
        
        engine = MemoryEngine()
        await engine.initialize(store=custom_store)
        
        assert engine._store is custom_store
        await engine.cleanup()

    @pytest.mark.asyncio
    async def test_initialize_with_custom_embedding_provider(self):
        """Test MemoryEngine initializes with custom embedding provider."""
        custom_provider = Mock()
        custom_provider.generate_embeddings = AsyncMock(return_value=[[0.1] * 384])
        custom_provider.generate_embedding = AsyncMock(return_value=[0.1] * 384)
        
        engine = MemoryEngine()
        await engine.initialize(embedding_provider=custom_provider)
        
        assert engine._embedding_provider is custom_provider
        await engine.cleanup()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self):
        """Test initialize can be called multiple times."""
        engine = MemoryEngine()
        await engine.initialize()
        first_store = engine._store
        first_provider = engine._embedding_provider
        
        # Call initialize again
        await engine.initialize()
        
        # Should reuse existing components
        assert engine._store is first_store
        assert engine._embedding_provider is first_provider
        await engine.cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_cancels_background_task(self):
        """Test cleanup cancels the auto-cleanup task."""
        engine = MemoryEngine()
        await engine.initialize(auto_cleanup=True, cleanup_interval=0.1)
        
        assert engine._cleanup_task is not None
        assert not engine._cleanup_task.done()
        
        await engine.cleanup()
        
        assert engine._cleanup_task.cancelled() or engine._cleanup_task.done()


async def _create_engine():
    """Helper to create and initialize an engine."""
    engine = MemoryEngine()
    await engine.initialize()
    return engine


class TestMemoryEngineOperations:
    """Tests for MemoryEngine memory operations."""

    @pytest.mark.asyncio
    async def test_add_memory(self):
        """Test adding a memory returns record with ID."""
        engine = await _create_engine()
        try:
            result = await engine.add_memory(
                content="Test memory content",
                scope="short_term",
                type_="conversation",
                metadata={"key": "value"},
                tags=["tag1", "tag2"],
                session_id="session-123",
                importance=0.8,
            )
            
            assert "id" in result
            assert result["content"] == "Test memory content"
            assert result["scope"] == "short_term"
            assert result["type"] == "conversation"
            assert result["metadata"] == {"key": "value"}
            assert result["tags"] == ["tag1", "tag2"]
            assert result["session_id"] == "session-123"
            assert result["importance"] == 0.8
            assert "embedding" in result
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_add_memory_invalid_scope(self):
        """Test adding memory with invalid scope raises ValueError."""
        engine = await _create_engine()
        try:
            with pytest.raises(ValueError, match="Invalid scope"):
                await engine.add_memory(content="Test", scope="invalid_scope")
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_search_memories(self):
        """Test searching memories."""
        engine = await _create_engine()
        try:
            # Add test memories
            await engine.add_memory(content="I love python programming", scope="short_term", type_="fact")
            await engine.add_memory(content="My favorite color is blue", scope="short_term", type_="preference")
            await engine.add_memory(content="The meeting is at 3pm", scope="short_term", type_="conversation")
            
            results = await engine.search(query="python", top_k=5)
            
            assert isinstance(results, list)
            assert len(results) > 0
            # Should find the python memory
            assert any("python" in r["content"].lower() for r in results)
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_search_with_scope_filter(self):
        """Test search with scope filter."""
        engine = await _create_engine()
        try:
            await engine.add_memory(content="Short term memory", scope="short_term")
            await engine.add_memory(content="Long term memory", scope="long_term")
            
            results = await engine.search(query="memory", scope="long_term")
            
            assert len(results) == 1
            assert results[0]["scope"] == "long_term"
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_get_recent(self):
        """Test getting recent memories."""
        engine = await _create_engine()
        try:
            await engine.add_memory(content="First memory", scope="short_term")
            await asyncio.sleep(0.01)
            await engine.add_memory(content="Second memory", scope="short_term")
            await asyncio.sleep(0.01)
            await engine.add_memory(content="Third memory", scope="short_term")
            
            results = await engine.get_recent(limit=2)
            
            assert len(results) == 2
            # Should be ordered by updated_at descending (most recent first)
            assert results[0]["content"] == "Third memory"
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_get_memory_by_id(self):
        """Test retrieving specific memory by ID."""
        engine = await _create_engine()
        try:
            added = await engine.add_memory(content="Specific memory", scope="short_term")
            memory_id = added["id"]
            
            result = await engine.get_memory(memory_id)
            
            assert result["id"] == memory_id
            assert result["content"] == "Specific memory"
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_get_memory_not_found(self):
        """Test getting non-existent memory raises MemoryNotFoundError."""
        engine = await _create_engine()
        try:
            with pytest.raises(MemoryNotFoundError):
                await engine.get_memory("non-existent-id")
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_update_memory(self):
        """Test updating a memory."""
        engine = await _create_engine()
        try:
            added = await engine.add_memory(content="Original content", scope="short_term")
            memory_id = added["id"]
            
            updated = await engine.update_memory(
                memory_id=memory_id,
                content="Updated content",
                importance=0.9,
            )
            
            assert updated["id"] == memory_id
            assert updated["content"] == "Updated content"
            assert updated["importance"] == 0.9
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_update_memory_not_found(self):
        """Test updating non-existent memory raises MemoryNotFoundError."""
        engine = await _create_engine()
        try:
            with pytest.raises(MemoryNotFoundError):
                await engine.update_memory("non-existent-id", content="New content")
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_delete_memory(self):
        """Test deleting a memory."""
        engine = await _create_engine()
        try:
            added = await engine.add_memory(content="To be deleted", scope="short_term")
            memory_id = added["id"]
            
            result = await engine.delete_memory(memory_id)
            
            assert result is True
            
            # Verify it's gone
            with pytest.raises(MemoryNotFoundError):
                await engine.get_memory(memory_id)
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_delete_memory_not_found(self):
        """Test deleting non-existent memory raises MemoryNotFoundError."""
        engine = await _create_engine()
        try:
            with pytest.raises(MemoryNotFoundError):
                await engine.delete_memory("non-existent-id")
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_clear_session(self):
        """Test clearing all memories for a session."""
        engine = await _create_engine()
        try:
            session_id = "test-session-123"
            await engine.add_memory(content="Memory 1", session_id=session_id)
            await engine.add_memory(content="Memory 2", session_id=session_id)
            await engine.add_memory(content="Memory 3", session_id="other-session")
            
            deleted_count = await engine.clear_session(session_id)
            
            assert deleted_count == 2
            
            # Verify other session's memory still exists
            results = await engine.search(query="Memory 3")
            assert len(results) == 1
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_clear_all(self):
        """Test clearing all memories."""
        engine = await _create_engine()
        try:
            await engine.add_memory(content="Memory 1")
            await engine.add_memory(content="Memory 2")
            await engine.add_memory(content="Memory 3")
            
            deleted_count = await engine.clear_all()
            
            assert deleted_count == 3
            
            results = await engine.get_recent(limit=10)
            assert len(results) == 0
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check returns expected structure."""
        engine = await _create_engine()
        try:
            health = await engine.health_check()
            
            assert "status" in health
            assert health["status"] == "healthy"
            assert "storage_backend" in health
            assert "total_memories" in health
        finally:
            await engine.cleanup()

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting memory statistics."""
        engine = await _create_engine()
        try:
            await engine.add_memory(content="Test 1", scope="short_term")
            await engine.add_memory(content="Test 2", scope="long_term")
            await engine.add_memory(content="Test 3", scope="short_term")
            
            stats = await engine.get_stats()
            
            assert stats["total_memories"] == 3
            assert stats["short_term_count"] == 2
            assert stats["long_term_count"] == 1
            assert "session_count" in stats
            assert "total_size_bytes" in stats
        finally:
            await engine.cleanup()


class TestDefaultEmbeddingProvider:
    """Tests for DefaultEmbeddingProvider."""

    @pytest.mark.asyncio
    async def test_generate_embeddings(self):
        """Test embedding generation returns correct dimensions."""
        provider = DefaultEmbeddingProvider(dimensions=384)
        
        embeddings = await provider.generate_embeddings(["test 1", "test 2", "test 3"])
        
        assert len(embeddings) == 3
        for emb in embeddings:
            assert len(emb) == 384
            assert all(isinstance(v, float) for v in emb)

    @pytest.mark.asyncio
    async def test_generate_embedding_single(self):
        """Test single embedding generation."""
        provider = DefaultEmbeddingProvider()
        
        emb = await provider.generate_embedding("single test")
        
        assert len(emb) == 384
        assert all(isinstance(v, float) for v in emb)

    @pytest.mark.asyncio
    async def test_deterministic_embeddings(self):
        """Test embeddings are deterministic for same input."""
        provider = DefaultEmbeddingProvider()
        
        emb1 = await provider.generate_embedding("same input")
        emb2 = await provider.generate_embedding("same input")
        
        assert emb1 == emb2

    @pytest.mark.asyncio
    async def test_different_inputs_different_embeddings(self):
        """Test different inputs produce different embeddings."""
        provider = DefaultEmbeddingProvider()
        
        emb1 = await provider.generate_embedding("input one")
        emb2 = await provider.generate_embedding("input two")
        
        assert emb1 != emb2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])