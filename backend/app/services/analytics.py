from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel

from app.services.agentic_orchestrator import agentic_orchestrator
from app.services.audit_log import AuditEvent, audit_log
from app.services.platform_registry import platform_registry_service
from app.services.task_coordination import task_coordination_service
from protocols.messages import AgentStatus, TaskStatus


class FleetAnalytics(BaseModel):
    total_agents: int
    active_agents: int
    online_agents: int
    offline_agents: int
    utilization_pct: float
    average_battery_pct: float
    battery_buckets: dict[str, int]
    active_missions: int
    missions_completed: int
    missions_failed: int
    negotiations: int
    handoffs: int
    replans: int


class MissionAnalytics(BaseModel):
    task_id: str
    planning_time_seconds: Optional[float] = None
    negotiation_time_seconds: Optional[float] = None
    execution_time_seconds: Optional[float] = None
    total_duration_seconds: float
    agents_involved: List[str]
    subtask_count: int
    replans: int
    handoffs: int
    completion_state: str


class PlatformAnalytics:
    def __init__(self, registry=platform_registry_service, coordination=task_coordination_service):
        self.registry = registry
        self.coordination = coordination

    def fleet(self) -> FleetAnalytics:
        now = time.time()
        agents = [entry for entry in self.registry.registry.get_all_agents() if not entry.metadata.get("archived")]
        tasks = self.coordination.list_tasks()
        roots = [task for task in tasks if not task.parent_task_id]
        active_agents = [entry for entry in agents if entry.status not in (AgentStatus.OFFLINE, AgentStatus.ERROR) and now - entry.last_seen <= self.registry.registry.offline_timeout_seconds]
        busy = sum(entry.status == AgentStatus.BUSY for entry in active_agents)
        values = [entry.state.battery_pct for entry in agents]
        buckets = {
            "0-19": sum(value < 20 for value in values),
            "20-49": sum(20 <= value < 50 for value in values),
            "50-79": sum(50 <= value < 80 for value in values),
            "80-100": sum(value >= 80 for value in values),
        }
        events = audit_log.list_events(limit=1000)
        return FleetAnalytics(
            total_agents=len(agents),
            active_agents=len(active_agents),
            online_agents=len(active_agents),
            offline_agents=len(agents) - len(active_agents),
            utilization_pct=(busy / len(active_agents) * 100.0) if active_agents else 0.0,
            average_battery_pct=(sum(values) / len(values)) if values else 0.0,
            battery_buckets=buckets,
            active_missions=sum(task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED) for task in roots),
            missions_completed=sum(task.status == TaskStatus.COMPLETED for task in roots),
            missions_failed=sum(task.status == TaskStatus.FAILED for task in roots),
            negotiations=sum(task.negotiation_status not in ("NOT_STARTED",) for task in tasks),
            handoffs=sum(event.event_type.startswith("handoff.") or event.event_type == "self_healing.handoff" for event in events),
            replans=sum(event.event_type == "mission.replanned" for event in events),
        )

    def mission(self, task_id: str) -> Optional[MissionAnalytics]:
        task = self.coordination.get_task(task_id)
        if task is None:
            return None
        subtasks = self.coordination.get_subtasks(task_id)
        events = list(reversed(audit_log.list_events(task_id=task_id, limit=1000)))
        event_types = [event.event_type for event in events]
        created_at = task.created_at.replace(tzinfo=timezone.utc) if task.created_at.tzinfo is None else task.created_at
        ended = next((event.timestamp for event in reversed(events) if event.event_type in ("mission.completed", "mission.failed")), datetime.now(timezone.utc))
        total = max(0.0, (ended - created_at).total_seconds())
        plan_event = next((event for event in events if event.event_type == "decision.dispatch"), None)
        announcement = next((event for event in events if event.event_type == "mission.created"), None)
        assignment = next((event for event in events if event.event_type == "assignment.confirmed"), None)
        completion = next((event for event in events if event.event_type == "mission.completed"), None)
        replans = sum(name == "mission.replanned" for name in event_types)
        handoffs = sum(name.startswith("handoff.") or name.startswith("self_healing.handoff") for name in event_types)
        negotiation_seconds = (assignment.timestamp - announcement.timestamp).total_seconds() if assignment and announcement else None
        execution_seconds = (completion.timestamp - assignment.timestamp).total_seconds() if completion and assignment else None
        planning_seconds = (announcement.timestamp - plan_event.timestamp).total_seconds() if announcement and plan_event else None
        agents = sorted({item.assigned_agent_id for item in subtasks if item.assigned_agent_id})
        return MissionAnalytics(
            task_id=task_id,
            planning_time_seconds=planning_seconds,
            negotiation_time_seconds=negotiation_seconds,
            execution_time_seconds=execution_seconds,
            total_duration_seconds=total,
            agents_involved=agents,
            subtask_count=len(subtasks),
            replans=replans,
            handoffs=handoffs,
            completion_state=task.status.value,
        )


platform_analytics = PlatformAnalytics()