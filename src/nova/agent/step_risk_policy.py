"""
StepRiskPolicy and ConfirmationManager for Phase 5.3C-B interrupted-step remediation.

Invariants:
- StepRiskPolicy is pure / stateless. It never touches SQLite or the event bus.
- ConfirmationManager is in-process only. Tokens expire after TTL_SECONDS (5 min).
- No token is ever reused: claim() deletes it atomically on first use.
"""
from __future__ import annotations

import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, NamedTuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------

#: Tools classified as HIGH_RISK because an unknown second execution may cause
#: destructive, irreversible, or idempotency-violating side effects.
_HIGH_RISK_TOOLS: frozenset[str] = frozenset({
    # System destructive / power
    "shutdown",
    "restart",
    # File-system destructive
    "delete_file",
    "remove_file",
    "rmdir",
    "overwrite_file",
    "truncate_file",
    # External write/send
    "send_email",
    "send_message",
    "post_request",
    "http_post",
    "http_put",
    "http_delete",
    "http_patch",
    "write_file",
    # Database/state mutations
    "db_write",
    "db_delete",
    "db_truncate",
    "execute_sql",
    # Payment / financial
    "charge_payment",
    "refund_payment",
    "transfer_funds",
    # Shell / process execution with side effects
    "run_command",
    "shell_exec",
    "subprocess_run",
    # Cloud / infrastructure mutations
    "create_instance",
    "terminate_instance",
    "deploy_service",
    "destroy_resource",
})


class RiskLevel:
    LOW = "low"
    HIGH = "high"


def classify_step_risk(tool: str, parameters: Optional[Dict] = None) -> str:
    """
    Return RiskLevel.HIGH if the tool is on the high-risk list,
    RiskLevel.LOW otherwise.

    This is conservative and intentionally simple: any tool whose
    second execution may be destructive is HIGH_RISK.
    """
    tool_lower = (tool or "").lower().strip()
    if tool_lower in _HIGH_RISK_TOOLS:
        return RiskLevel.HIGH
    # Additional parameter-based heuristics
    if tool_lower == "power":
        action = (parameters or {}).get("action", "").lower().strip() if isinstance(parameters, dict) else ""
        if action == "hibernate":
            return RiskLevel.HIGH
    if tool_lower in ("file_operation", "file", "file_control"):
        action = (parameters or {}).get("action", "").lower().strip() if isinstance(parameters, dict) else ""
        if action == "delete_file":
            return RiskLevel.HIGH
    return RiskLevel.LOW


# ---------------------------------------------------------------------------
# Confirmation management
# ---------------------------------------------------------------------------

_CONFIRMATION_TTL_SECONDS = 300  # 5 minutes


class _PendingConfirmation(NamedTuple):
    task_id: str
    step_index: int
    tool: str
    token: str
    expires_at: datetime


class ConfirmationManager:
    """
    Manages pending high-risk retry confirmation tokens.

    Thread-safe via threading.Lock (sync path called from async context via
    asyncio.to_thread is fine because Lock is reentrant-free but short-lived).

    Each (task_id, step_index) key holds at most one pending token.
    Issuing a new token for the same key supersedes the old one.
    """

    def __init__(self, ttl_seconds: int = _CONFIRMATION_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        # key: (task_id, step_index) -> _PendingConfirmation
        self._pending: Dict[tuple[str, int], _PendingConfirmation] = {}

    def issue(self, task_id: str, step_index: int, tool: str) -> _PendingConfirmation:
        """
        Issue a new confirmation token for (task_id, step_index).
        If a previous token exists for the same key, it is replaced.
        Returns the PendingConfirmation with the token and expiry.
        """
        token = secrets.token_hex(8)  # 16 hex chars – human-enterable
        expires_at = datetime.utcnow() + timedelta(seconds=self._ttl)
        pending = _PendingConfirmation(
            task_id=task_id,
            step_index=step_index,
            tool=tool,
            token=token,
            expires_at=expires_at,
        )
        with self._lock:
            self._pending[(task_id, step_index)] = pending
        logger.info(
            "ConfirmationManager: issued token %s for task=%s step=%s expires=%s",
            token, task_id, step_index, expires_at.isoformat(),
        )
        return pending

    def claim(self, task_id: str, step_index: int, token: str) -> bool:
        """
        Validate and consume a confirmation token for (task_id, step_index).

        Returns True if the token matches and has not expired.
        Returns False if the key is not found or the token does not match.
        Raises ConfirmationExpiredError if token matched but has expired.

        The token is deleted upon first use (single-use guarantee).
        """
        from .exceptions import ConfirmationExpiredError, ConfirmationMismatchError

        key = (task_id, step_index)
        with self._lock:
            pending = self._pending.get(key)
            if pending is None:
                return False  # no pending confirmation for this step
            # Always delete – even on mismatch or expiry – to prevent brute-force
            del self._pending[key]

        if pending.token != token:
            raise ConfirmationMismatchError(task_id=task_id, step_index=step_index)

        if datetime.utcnow() > pending.expires_at:
            raise ConfirmationExpiredError(task_id=task_id, step_index=step_index, token=token)

        return True

    def has_pending(self, task_id: str, step_index: int) -> bool:
        """Return True if there is a non-expired pending confirmation for (task_id, step_index)."""
        key = (task_id, step_index)
        with self._lock:
            pending = self._pending.get(key)
            if pending is None:
                return False
            if datetime.utcnow() > pending.expires_at:
                del self._pending[key]
                return False
            return True

    def clear(self, task_id: str, step_index: int) -> None:
        """Discard any pending confirmation for (task_id, step_index) without consuming it."""
        with self._lock:
            self._pending.pop((task_id, step_index), None)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_confirmation_manager: Optional[ConfirmationManager] = None


def get_confirmation_manager() -> ConfirmationManager:
    """Return the process-singleton ConfirmationManager."""
    global _confirmation_manager
    if _confirmation_manager is None:
        _confirmation_manager = ConfirmationManager()
    return _confirmation_manager
