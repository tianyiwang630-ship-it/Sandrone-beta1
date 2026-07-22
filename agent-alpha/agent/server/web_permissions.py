from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


class PermissionNotFoundError(LookupError):
    pass


class PermissionConflictError(RuntimeError):
    pass


@dataclass
class _PendingPermission:
    permission_id: str
    request_id: str
    session_id: str
    prompt: dict[str, Any]
    requested_at: datetime
    expires_at: datetime
    event: threading.Event = field(default_factory=threading.Event)
    decision: str | None = None
    instruction: str | None = None
    state: str = "pending"

    def to_payload(self) -> dict[str, Any]:
        return {
            "permission_id": self.permission_id,
            **self.prompt,
            "requested_at": self.requested_at.isoformat(timespec="seconds"),
            "expires_at": self.expires_at.isoformat(timespec="seconds"),
        }


class WebPermissionBroker:
    """Coordinate synchronous tool approval with HTTP polling and decisions."""

    def __init__(self, *, timeout_seconds: float = 600):
        self.timeout_seconds = timeout_seconds
        self._lock = threading.RLock()
        self._pending_by_id: dict[str, _PendingPermission] = {}
        self._pending_by_request: dict[str, _PendingPermission] = {}
        self._terminal: OrderedDict[str, str] = OrderedDict()

    def request(
        self,
        request_id: str,
        session_id: str,
        prompt: dict[str, Any],
    ) -> bool | dict[str, str]:
        requested_at = datetime.now(timezone.utc)
        pending = _PendingPermission(
            permission_id=uuid.uuid4().hex,
            request_id=request_id,
            session_id=session_id,
            prompt=dict(prompt),
            requested_at=requested_at,
            expires_at=requested_at + timedelta(seconds=self.timeout_seconds),
        )
        with self._lock:
            existing = self._pending_by_request.get(request_id)
            if existing is not None:
                self._cancel_locked(existing, "replaced")
            self._pending_by_id[pending.permission_id] = pending
            self._pending_by_request[request_id] = pending

        pending.event.wait(timeout=self.timeout_seconds)
        with self._lock:
            if pending.state == "pending":
                self._finish_locked(pending, "expired")
            state = pending.state
            decision = pending.decision
            instruction = pending.instruction

        if state == "expired":
            return {"permission_denied_reason": "Permission request timed out"}
        if state in {"cancelled", "replaced"}:
            return {"permission_denied_reason": "Permission request cancelled"}
        if decision == "allow_once":
            return True
        if decision == "retry_with_context":
            return {"retry_with_context": instruction or ""}
        return False

    def pending_for_request(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            pending = self._pending_by_request.get(request_id)
            return pending.to_payload() if pending is not None and pending.state == "pending" else None

    def resolve(self, permission_id: str, decision: str, instruction: str | None = None) -> None:
        with self._lock:
            pending = self._pending_by_id.get(permission_id)
            if pending is None:
                if permission_id in self._terminal:
                    raise PermissionConflictError("Permission request is no longer pending")
                raise PermissionNotFoundError("Permission request not found")
            pending.decision = decision
            pending.instruction = instruction
            self._finish_locked(pending, "resolved")

    def cancel_session(self, session_id: str) -> None:
        with self._lock:
            pending_items = [item for item in self._pending_by_id.values() if item.session_id == session_id]
            for pending in pending_items:
                self._cancel_locked(pending, "cancelled")

    def cancel_request(self, request_id: str) -> None:
        with self._lock:
            pending = self._pending_by_request.get(request_id)
            if pending is not None:
                self._cancel_locked(pending, "cancelled")

    def cancel_all(self) -> None:
        with self._lock:
            for pending in list(self._pending_by_id.values()):
                self._cancel_locked(pending, "cancelled")

    def _cancel_locked(self, pending: _PendingPermission, state: str) -> None:
        self._finish_locked(pending, state)

    def _finish_locked(self, pending: _PendingPermission, state: str) -> None:
        pending.state = state
        self._pending_by_id.pop(pending.permission_id, None)
        if self._pending_by_request.get(pending.request_id) is pending:
            self._pending_by_request.pop(pending.request_id, None)
        self._terminal[pending.permission_id] = state
        while len(self._terminal) > 256:
            self._terminal.popitem(last=False)
        pending.event.set()
