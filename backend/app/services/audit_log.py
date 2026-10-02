from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"AUD-{uuid.uuid4().hex[:12].upper()}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str
    actor: str = "platform"
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    result: str = "recorded"
    summary: str
    details: Dict[str, Any] = Field(default_factory=dict)


class AuditLog:
    """In-memory, bounded audit trail. Credentials and payload secrets are never accepted."""

    def __init__(self, max_events: int = 20000):
        self.max_events = max(100, max_events)
        self._events: List[AuditEvent] = []
        self._lock = threading.RLock()

    def record(
        self,
        event_type: str,
        summary: str,
        actor: str = "platform",
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        result: str = "recorded",
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            summary=summary,
            actor=actor,
            agent_id=agent_id,
            task_id=task_id,
            result=result,
            details=details or {},
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.max_events:
                del self._events[:len(self._events) - self.max_events]
        return event.model_copy(deep=True)

    def list_events(
        self,
        event_type: Optional[str] = None,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[AuditEvent]:
        with self._lock:
            events = list(reversed(self._events))
        if event_type:
            events = [event for event in events if event.event_type == event_type]
        if task_id:
            events = [event for event in events if event.task_id == task_id]
        if agent_id:
            events = [event for event in events if event.agent_id == agent_id]
        return [event.model_copy(deep=True) for event in events[:max(1, min(limit, 1000))]]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


audit_log = AuditLog()