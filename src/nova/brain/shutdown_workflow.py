"""
Shutdown Precondition Workflow Manager.

Manages session-isolated pending shutdown state and detects natural language
continuation and cancellation phrases during a multi-turn shutdown interaction.

Invariants:
- Thread-safe: protected by internal threading lock.
- Session-scoped: state is strictly isolated by session_id.
- TTL expiration: 5 minutes (300 seconds), matching ConfirmationManager.
- No unsafe global shared state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import re
import threading
from typing import Dict, List, Optional

logger = logging.getLogger("nova.brain.shutdown_workflow")

_SHUTDOWN_WORKFLOW_TTL_SECONDS = 300  # 5 minutes


@dataclass(frozen=True)
class PendingShutdown:
    """Represents an active pending shutdown workflow for a specific session."""
    session_id: str
    open_applications: List[str]
    created_at: datetime
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


class ShutdownWorkflowManager:
    """
    Session-scoped manager for pending shutdown workflows.
    """

    def __init__(self, ttl_seconds: int = _SHUTDOWN_WORKFLOW_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._pending: Dict[str, PendingShutdown] = {}

    def set_pending(self, session_id: str, open_applications: List[str]) -> PendingShutdown:
        """Record or overwrite pending shutdown state for the given session."""
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=self._ttl)
        pending = PendingShutdown(
            session_id=session_id or "default",
            open_applications=list(open_applications),
            created_at=now,
            expires_at=expires_at,
        )
        with self._lock:
            self._pending[session_id or "default"] = pending
        logger.info(
            "ShutdownWorkflowManager: pending shutdown set for session=%s apps=%s expires=%s",
            session_id, open_applications, expires_at.isoformat(),
        )
        return pending

    def is_pending(self, session_id: str) -> bool:
        """Return True if session has an active, non-expired pending shutdown workflow."""
        sid = session_id or "default"
        with self._lock:
            pending = self._pending.get(sid)
            if pending is None:
                return False
            if pending.is_expired:
                del self._pending[sid]
                return False
            return True

    def get_pending(self, session_id: str) -> Optional[PendingShutdown]:
        """Retrieve active pending shutdown state for session if not expired."""
        sid = session_id or "default"
        with self._lock:
            pending = self._pending.get(sid)
            if pending is None:
                return None
            if pending.is_expired:
                del self._pending[sid]
                return None
            return pending

    def update_pending(self, session_id: str, open_applications: List[str]) -> Optional[PendingShutdown]:
        """Update remaining open applications for an active pending shutdown."""
        sid = session_id or "default"
        with self._lock:
            pending = self._pending.get(sid)
            if pending is None or pending.is_expired:
                if pending and pending.is_expired:
                    del self._pending[sid]
                return None
            updated = PendingShutdown(
                session_id=sid,
                open_applications=list(open_applications),
                created_at=pending.created_at,
                expires_at=datetime.utcnow() + timedelta(seconds=self._ttl),
            )
            self._pending[sid] = updated
            return updated

    def clear_pending(self, session_id: str) -> None:
        """Clear pending shutdown state for the given session."""
        sid = session_id or "default"
        with self._lock:
            self._pending.pop(sid, None)
        logger.debug("ShutdownWorkflowManager: cleared pending shutdown for session=%s", sid)

    def clear_all(self) -> None:
        """Clear all pending sessions (primarily for testing)."""
        with self._lock:
            self._pending.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_workflow_manager: Optional[ShutdownWorkflowManager] = None


def get_shutdown_workflow_manager() -> ShutdownWorkflowManager:
    """Return the process-singleton ShutdownWorkflowManager."""
    global _workflow_manager
    if _workflow_manager is None:
        _workflow_manager = ShutdownWorkflowManager()
    return _workflow_manager


# ---------------------------------------------------------------------------
# Natural Language Continuation & Cancellation Heuristics
# ---------------------------------------------------------------------------

_CANCELLATION_PATTERN = re.compile(
    r"^(?:please\s+)?(?:"
    r"cancel(?:\s+shutdown)?"
    r"|never\s*mind"
    r"|don'?t\s+shut\s*down(?:\s+(?:the\s+|my\s+)?(?:pc|computer|system|laptop))?"
    r"|dont\s+shut\s*down(?:\s+(?:the\s+|my\s+)?(?:pc|computer|system|laptop))?"
    r"|don'?t\s+shutdown(?:\s+(?:the\s+|my\s+)?(?:pc|computer|system|laptop))?"
    r"|dont\s+shutdown(?:\s+(?:the\s+|my\s+)?(?:pc|computer|system|laptop))?"
    r"|forget\s+it"
    r"|stop(?:\s+shutdown)?"
    r"|abort(?:\s+shutdown)?"
    r")$",
    re.IGNORECASE,
)

_CONTINUATION_PATTERN = re.compile(
    r"^(?:please\s+)?(?:"
    r"done(?:[,\s]+(?:shutdown|shut\s*down))?"
    r"|all\s+closed"
    r"|they(?:'?re|\s+are)\s+(?:all\s+)?closed"
    r"|they(?:'?re|\s+are)\s+done"
    r"|all\s+are\s+closed"
    r"|closed"
    r"|ready(?:[,\s]+(?:shutdown|shut\s*down))?"
    r"|i'?m\s+ready(?:[,\s]+(?:shutdown|shut\s*down))?"
    r"|im\s+ready(?:[,\s]+(?:shutdown|shut\s*down))?"
    r"|okay(?:[,\s]+(?:shutdown|shut\s*down))?"
    r"|ok(?:[,\s]+(?:shutdown|shut\s*down))?"
    r"|shut\s*down\s+now"
    r"|now\s+shut\s+(?:it\s+)?down"
    r"|now\s+shutdown"
    r")$",
    re.IGNORECASE,
)


def is_cancellation_phrase(text: str) -> bool:
    """Return True if text expresses an intent to cancel a pending shutdown."""
    cleaned = text.strip()
    return bool(_CANCELLATION_PATTERN.match(cleaned))


def is_continuation_phrase(text: str) -> bool:
    """Return True if text expresses continuation of an active pending shutdown."""
    cleaned = text.strip()
    return bool(_CONTINUATION_PATTERN.match(cleaned))
