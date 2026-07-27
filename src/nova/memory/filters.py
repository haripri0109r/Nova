"""
Memory filters for rejecting unwanted memories.
"""
from __future__ import annotations

import re
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class MemoryFilters:
    """Filters for rejecting unwanted memories."""

    def __init__(self):
        # Patterns that indicate content should NOT be stored
        self._ignore_patterns = [
            # Greetings
            r"^(hi|hello|hey|hiya|howdy|greetings)\b",
            r"^(good (morning|afternoon|evening|night))\b",
            
            # Simple acknowledgments
            r"^(ok|okay|okey|sure|yeah|yeah|yep|yeah|yea)\b",
            r"^(thanks?|thank you|thx|thx)\b",
            r"^(you're welcome|welcome|no problem)\b",
            
            # Small talk
            r"(how are you|how's it going|what's up|what's new)\b",
            r"(nice to meet you|good to see you)\b",
            
            # Commands (these are actions, not memories to store)
            r"^(open|close|launch|start|stop|run|execute|play|pause|stop|pause)\b",
            r"^(turn on|turn off|turn up|turn down|mute|unmute)\b",
            r"^(set|change|adjust|increase|decrease)\s+\w+\b",
            
            # System commands
            r"^(what time|what date|what day)\b",
            r"^(shutdown|restart|sleep|hibernate|lock)\b",
        ]
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self._ignore_patterns]

    def should_reject(self, content: str) -> Tuple[bool, str]:
        """Check if content should be rejected.
        
        Returns:
            Tuple of (should_reject, reason)
        """
        if not content or not content.strip():
            return True, "empty_content"

        content_lower = content.lower().strip()

        # Check ignore patterns
        for pattern in self._compiled:
            if pattern.search(content):
                return True, "ignored_pattern"

        # Very short content
        if len(content.strip()) < 3:
            return True, "too_short"

        # Repetitive content
        words = content.lower().split()
        if len(words) > 5:
            unique_words = set(content.lower().split())
            if len(unique_words) / len(words) < 0.3:
                return True, "repetitive"

        # Commands that are actions, not memories
        command_patterns = [
            r"^(open|close|launch|start|stop|run|execute)\b",
            r"(turn on|turn off|turn up|turn down)\b",
            r"(mute|unmute|volume)\s*\d*\b",
        ]
        for pattern in command_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True, "command"

        # Very short content (duplicate check removed)
        # if len(content.strip()) < 4:
        #     return True, "too_short"

        return False, ""

    def should_store(self, content: str) -> bool:
        """Check if content should be stored."""
        reject, reason = self.should_reject(content)
        return not reject

    def filter_memories(self, memories: list) -> list:
        """Filter a list of memories, returning only those that should be kept."""
        filtered = []
        for memory in memories:
            if self.should_store(memory.content):
                filtered.append(memory)
        return filtered


# Global instance
_memory_filters = None


def get_memory_filters() -> "MemoryFilters":
    """Get the global MemoryFilters instance."""
    global _memory_filters
    if _memory_filters is None:
        _memory_filters = MemoryFilters()
    return _memory_filters