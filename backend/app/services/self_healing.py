from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.services.audit_log import audit_log
from app.services.platform_registry import platform_registry_service
from protocols.messages import AgentStatus, Task


class HealingRecord(BaseModel):
    healing_id: str = Field(default_factory=lambda: f"HEAL-{uuid.uuid4().hex[:10].upper()}")
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    task_id: str
    failed_subtask_id: str
    failed_agent_id: Optional[str] = None
    failure: str
    impact: str
    replacement_candidates: List[str] = Field(default_factory=list)
    selected_candidate: Optional[str] = None
    decision: str
    handoff_result: str = "PENDING"
    recovery_status: str = "DETECTED"
    recovered_at: Optional[datetime] = None


class SelfHealingEngine:
    def __init__(self, registry=platform_registry_service):
        self.registry = registry
        self._records: List[HealingRecord] = []
        self._lock = threading.RLock()

    def detect(self, task_id: str, failed_task: Task, reason: str, payload_weight: float) -> HealingRecord:
        candidates = []
        now = time.time()
        for agent in self.registry.registry.get_all_agents():
            if agent.agent_id == failed_task.assigned_agent_id:
                continue
            if (
                agent.status == AgentStatus.IDLE
                and agent.state.is_available
                and agent.state.battery_pct >= 20
                and agent.payload_capacity_kg >= payload_weight
                and set(failed_task.required_capabilities).issubset(agent.capabilities)
                and now - agent.last_seen <= self.registry.registry.offline_timeout_seconds
            ):
                candidates.append(agent)
        candidates.sort(key=lambda agent: (-agent.state.battery_pct, agent.agent_id))
        record = HealingRecord(
            task_id=task_id,
            failed_subtask_id=failed_task.task_id,
            failed_agent_id=failed_task.assigned_agent_id,
            failure=reason,
            impact="Subtask assignment failed; mission may be incomplete",
            replacement_candidates=[agent.agent_id for agent in candidates],
            selected_candidate=candidates[0].agent_id if candidates else None,
            decision="Replan, validate, and request replacement through decentralized handoff" if candidates else "No eligible replacement currently available",
        )
        with self._lock:
            self._records.append(record)
            self._records = self._records[-2000:]
        audit_log.record(
            "self_healing.detected",
            f"Detected failure on {failed_task.task_id}; {len(candidates)} eligible replacements observed",
            agent_id=failed_task.assigned_agent_id,
            task_id=task_id,
            details={"healing_id": record.healing_id, "replacement_candidates": record.replacement_candidates},
        )
        return record.model_copy(deep=True)

    def mark_handoff(self, healing_id: str, result: str) -> Optional[HealingRecord]:
        with self._lock:
            record = next((item for item in self._records if item.healing_id == healing_id), None)
            if record is None:
                return None
            record.handoff_result = result
            record.recovery_status = "NEGOTIATING" if result == "REQUESTED" else "FAILED"
            updated = record.model_copy(deep=True)
        audit_log.record("self_healing.handoff", f"Handoff {result.lower()} for {record.failed_subtask_id}", task_id=record.task_id, agent_id=record.failed_agent_id, result=result, details={"healing_id": healing_id})
        return updated

    def mark_recovered(self, healing_id: str, replacement_id: str) -> Optional[HealingRecord]:
        with self._lock:
            record = next((item for item in self._records if item.healing_id == healing_id), None)
            if record is None:
                return None
            record.selected_candidate = replacement_id
            record.handoff_result = "ACCEPTED"
            record.recovery_status = "RECOVERED"
            record.recovered_at = datetime.now(timezone.utc)
            updated = record.model_copy(deep=True)
        audit_log.record("self_healing.recovered", f"Replacement {replacement_id} accepted for {record.failed_subtask_id}", task_id=record.task_id, agent_id=replacement_id, result="RECOVERED", details={"healing_id": healing_id})
        return updated

    def list_records(self, task_id: Optional[str] = None) -> List[HealingRecord]:
        with self._lock:
            records = list(reversed(self._records))
        if task_id:
            records = [record for record in records if record.task_id == task_id]
        return [record.model_copy(deep=True) for record in records]


self_healing_engine = SelfHealingEngine()