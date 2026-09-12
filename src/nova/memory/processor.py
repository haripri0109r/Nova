"""Memory Engine preprocessing – classification, filtering, and tag normalization."""
from __future__ import annotations

import re
from typing import List

from pydantic import BaseModel, Field

from .models import MemoryRecord
from .types import MemoryType
from .exceptions import MemoryProcessorError


class ProcessedMemory(BaseModel):
    """Result of preprocessing a raw memory."""
    content: str
    memory_type: MemoryType
    importance: float = Field(ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    accepted: bool


class MemoryProcessor:
    """Stateless processor for classification, filtering, tagging, and importance."""

    # Compiled regex patterns for classification
    _PREFERENCE_PATTERNS = [
        r"\b(i like|i prefer|i love|i hate|i enjoy|i dislike)\b",
        r"\b(my (favorite|preferred))\b",
        r"\b(i usually|i normally|i typically|i always|i never)\b",
    ]
    _FACT_PATTERNS = [
        r"\b(my (name|birthday|birth date|age|address|phone|email|job|work)\s+is)\b",
        r"\b(i (am|was) born (on|in))\b",
        r"\b(i (live|work|study) (at|in))\b",
        r"\b(my (name|birthday|age) is)\b",
    ]
    _SKILL_RESULT_PATTERNS = [
        r"\b(i (opened|closed|launched|started|stopped|created|deleted|updated|installed|uninstalled))\b",
        r"\b(set|change|adjust|increase|decrease|turn on|turn off|enable|disable)\b",
        r"\b(opened|closed|launched|executed|completed)\b",
    ]
    _COMMAND_PATTERNS = [
        r"^(open|close|launch|start|stop|run|execute|play|pause|stop|mute|unmute)\b",
        r"^(set|change|adjust|increase|decrease|turn on|turn off)\b",
        r"^(search|find|look for|google|youtube)\b",
    ]
    _GREETING_PATTERNS = [
        r"^(hi|hello|hey|hiya|howdy)\b",
        r"^(good (morning|afternoon|evening|night))\b",
    ]
    _SMALL_TALK_PATTERNS = [
        r"\b(how are you|what's up|what's new|how's it going)\b",
        r"\b(nice (to meet|meeting) you)\b",
    ]

    def __init__(self) -> None:
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        self._preference_re = [re.compile(p, re.IGNORECASE) for p in self._PREFERENCE_PATTERNS]
        self._fact_re = [re.compile(p, re.IGNORECASE) for p in self._FACT_PATTERNS]
        self._skill_result_re = [re.compile(p, re.IGNORECASE) for p in self._SKILL_RESULT_PATTERNS]
        self._command_re = [re.compile(p, re.IGNORECASE) for p in self._COMMAND_PATTERNS]
        self._greeting_re = [re.compile(p, re.IGNORECASE) for p in self._GREETING_PATTERNS]
        self._small_talk_re = [re.compile(p, re.IGNORECASE) for p in self._SMALL_TALK_PATTERNS]

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def process(self, content: str) -> "ProcessedMemory":
        """Run the full preprocessing pipeline."""
        cleaned = self.clean_content(content)
        if self.should_reject(cleaned):
            return ProcessedMemory(
                content=cleaned,
                memory_type=MemoryType.CONVERSATION,
                importance=0.0,
                tags=[],
                accepted=False,
            )
        mem_type = self.classify(cleaned)
        importance = self.calculate_importance(cleaned, mem_type)
        tags = self.normalize_tags(self._extract_tags(cleaned))
        return ProcessedMemory(
            content=cleaned,
            memory_type=mem_type,
            importance=importance,
            tags=tags,
            accepted=True,
        )

    def classify(self, content: str) -> MemoryType:
        """Return the memory type for the given text."""
        if not content or not content.strip():
            return MemoryType.CONVERSATION

        text_lower = content.lower().strip()

        # Ignore greetings, small talk, commands
        if self._is_greeting(text_lower) or self._is_small_talk(text_lower) or self._is_command(text_lower):
            return MemoryType.CONVERSATION

        # Preferences
        if self._is_preference(text_lower):
            return MemoryType.PREFERENCE

        # Facts
        if self._is_fact(text_lower):
            return MemoryType.FACT

        # Skill results
        if self._is_skill_result(text_lower):
            return MemoryType.SKILL_RESULT

        # Default
        return MemoryType.CONVERSATION

    def should_reject(self, content: str) -> bool:
        """True if the content should not be stored."""
        if not content or not content.strip():
            return True
        # Very short content
        if len(content.strip()) < 3:
            return True
        # Repetitive
        words = content.lower().split()
        if len(words) > 5:
            unique = set(words)
            if len(unique) / len(words) < 0.3:
                return True
        return False

    def normalize_tags(self, tags: List[str]) -> List[str]:
        """Normalize tags: lower‑case, strip, unique, max 10."""
        normalized = []
        seen = set()
        for t in tags:
            nt = t.strip().lower()
            if nt and nt not in seen:
                seen.add(nt)
                normalized.append(nt)
        return normalized[:10]

    def calculate_importance(self, content: str, mem_type: MemoryType) -> float:
        """Heuristic importance 0‑1 based on type and length."""
        base = {
            MemoryType.PREFERENCE: 0.8,
            MemoryType.FACT: 0.9,
            MemoryType.SKILL_RESULT: 0.7,
            MemoryType.CONVERSATION: 0.3,
            MemoryType.SESSION: 0.2,
        }.get(mem_type, 0.3)

        # Length boost up to +0.2
        length_boost = min(len(content) / 500.0, 0.2)
        return min(base + length_boost, 1.0)

    def clean_content(self, content: str) -> str:
        """Trim whitespace, collapse multiple spaces."""
        return re.sub(r"\s+", " ", content.strip())

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _is_greeting(self, text: str) -> bool:
        return any(p.search(text) for p in self._greeting_re)

    def _is_small_talk(self, text: str) -> bool:
        return any(p.search(text) for p in self._small_talk_re)

    def _is_command(self, text: str) -> bool:
        return any(p.search(text) for p in self._command_re)

    def _is_preference(self, text: str) -> bool:
        return any(p.search(text) for p in self._preference_re)

    def _is_fact(self, text: str) -> bool:
        return any(p.search(text) for p in self._fact_re)

    def _is_skill_result(self, text: str) -> bool:
        return any(p.search(text) for p in self._skill_result_re)

    def _extract_tags(self, content: str) -> List[str]:
        """Very naive tag extraction: words longer than 3 chars, alphanumeric."""
        words = re.findall(r"\b\w{4,}\b", content.lower())
        # Keep only alphabetic words
        return [w for w in words if w.isalpha()][:20]


__all__ = ["MemoryProcessor", "ProcessedMemory"]