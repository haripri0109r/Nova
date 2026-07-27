"""
Memory Classifier - classifies memories before storage.
"""
from __future__ import annotations

from typing import Optional, Tuple
from enum import Enum
import re
from datetime import datetime

from .models import MemoryRecord, MemoryType, MemoryScope


class MemoryCategory(str, Enum):
    """High-level memory categories."""
    PREFERENCE = "preference"
    FACT = "fact"
    SKILL_RESULT = "skill_result"
    CONVERSATION = "conversation"
    IGNORE = "ignore"


class MemoryClassifier:
    """Classifies memories before storage to determine their type and importance."""

    # Patterns for different categories
    PREFERENCE_PATTERNS = [
        r"\b(i like|i prefer|i love|i hate|i enjoy|i dislike)\b",
        r"\b(my (favorite|preferred|preferred)\b",
        r"\b(i usually|i normally|i typically|i always|i never)\b",
        r"\b(set|change|make)\s+(my|the)\s+\w+\s+to\b",
    ]

    FACT_PATTERNS = [
        r"\b(my (name|birthday|birth date|age|address|phone|email|job|work)\s+is)\b",
        r"\b(i (am|was) born (on|in))\b",
        r"\b(i (live|work|study) (at|in))\b",
        r"\b(my (name|birthday|age) is)\b",
    ]

    SKILL_RESULT_PATTERNS = [
        r"\b(i (opened|closed|launched|started|stopped|created|deleted|updated|installed|uninstalled))\b",
        r"\b(set|change|adjust|increase|decrease|turn on|turn off|enable|disable)\b",
        r"\b(opened|closed|launched|executed|completed)\b",
    ]

    COMMAND_PATTERNS = [
        r"^(open|close|launch|start|stop|run|execute|play|pause|stop|mute|unmute)\b",
        r"^(set|change|adjust|increase|decrease|set|turn on|turn off)\b",
        r"^(search|find|look for|google|youtube)\b",
    ]

    GREETING_PATTERNS = [
        r"^(hi|hello|hey|hiya|howdy)\b",
        r"^(good (morning|afternoon|evening|night))\b",
        r"^(hi|hello|hey) (there|nova)\b",
    ]

    SMALL_TALK_PATTERNS = [
        r"\b(how are you|what's up|what's new|how's it going)\b",
        r"\b(nice (to meet|meeting) you)\b",
        r"\b(have a (good|nice|great) (day|night|weekend))\b",
    ]

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns for efficiency."""
        self._preference_regex = [re.compile(p, re.IGNORECASE) for p in self.PREFERENCE_PATTERNS]
        self._fact_regex = [re.compile(p, re.IGNORECASE) for p in self.FACT_PATTERNS]
        self._skill_result_regex = [re.compile(p, re.IGNORECASE) for p in self.SKILL_RESULT_PATTERNS]
        self._command_regex = [re.compile(p, re.IGNORECASE) for p in self.COMMAND_PATTERNS]
        self._greeting_regex = [re.compile(p, re.IGNORECASE) for p in self.GREETING_PATTERNS]
        self._small_talk_regex = [re.compile(p, re.IGNORECASE) for p in self.SMALL_TALK_PATTERNS]

    def classify(self, text: str, context: dict = None) -> Tuple[str, float]:
        """
        Classify text into memory category.
        
        Returns:
            Tuple of (category, importance_score)
        """
        if not text or not text.strip():
            return "ignore", 0.0

        text_lower = text.lower().strip()

        # Check for ignore patterns first
        if self._is_greeting(text) or self._is_small_talk(text):
            return "ignore", 0.0

        if self._is_command(text):
            return "ignore", 0.0

        # Check for preferences
        if self._is_preference(text):
            return "preference", 0.8

        # Check for facts
        if self._is_fact(text):
            return "fact", 0.9

        # Check for skill results
        if self._is_skill_result(text):
            return "skill_result", 0.7

        # Default to conversation
        return "conversation", 0.3

    def _is_greeting(self, text: str) -> bool:
        text_lower = text.lower()
        for pattern in self._greeting_regex:
            if pattern.search(text):
                return True
        return False

    def _is_small_talk(self, text: str) -> bool:
        text_lower = text.lower()
        for pattern in self._small_talk_regex:
            if pattern.search(text):
                return True
        return False

    def _is_command(self, text: str) -> bool:
        text_lower = text.lower()
        for pattern in self._command_regex:
            if pattern.search(text):
                return True
        return False

    def _is_preference(self, text: str) -> bool:
        text_lower = text.lower()
        for pattern in self._preference_regex:
            if pattern.search(text):
                return True
        return False

    def _is_fact(self, text: str) -> bool:
        text_lower = text.lower()
        for pattern in self._fact_regex:
            if pattern.search(text):
                return True
        return False

    def _is_skill_result(self, text: str) -> bool:
        text_lower = text.lower()
        for pattern in self._skill_result_regex:
            if pattern.search(text):
                return True
        return False


# Global instance
_classifier = None


def get_classifier() -> MemoryClassifier:
    """Get the global MemoryClassifier instance."""
    global _classifier
    if _classifier is None:
        _classifier = MemoryClassifier()
    return _classifier