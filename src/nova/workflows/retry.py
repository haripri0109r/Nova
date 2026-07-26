"""
Retry policy definitions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Callable, Any, Dict
import asyncio
import random


@dataclass
class RetryPolicy:
    """
    Configures retry behavior for a node.
    """
    max_attempts: int = 3
    base_delay: float = 1.0          # seconds
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: float = 0.1              # fraction of delay
    retryable_exceptions: tuple = (Exception,)
    should_retry: Optional[Callable[[Exception], bool]] = None

    def should_retry_attempt(self, attempt: int, exc: Exception) -> bool:
        if attempt >= self.max_attempts:
            return False
        if not isinstance(exc, self.retryable_exceptions):
            return False
        if self.should_retry and not self.should_retry(exc):
            return False
        return True

    def next_delay(self, attempt: int) -> float:
        delay = min(self.base_delay * (self.exponential_base ** (attempt - 1)), self.max_delay)
        jitter_range = delay * self.jitter
        return delay + random.uniform(-jitter_range, jitter_range)

    async def wait(self, attempt: int) -> None:
        delay = self.next_delay(attempt)
        await asyncio.sleep(delay)