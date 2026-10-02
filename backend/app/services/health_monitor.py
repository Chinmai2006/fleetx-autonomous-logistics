from __future__ import annotations

import time
from typing import List, Literal

from pydantic import BaseModel

from app.services.audit_log import audit_log
from app.services.platform_registry import platform_registry_service
from app.services.task_coordination import task_coordination_service
from protocols.messages import AgentStatus, TaskStatus


class AgentHealth(BaseModel):
    agent_id: str
    health: Literal["HEALTHY", "WARNING", "CRITICAL"]
    battery_pct: float
    status: str
    available: bool
    connectivity_age_seconds: float
    uptime_seconds: float
    workload: int
    failures: int
    recent_errors: int
    task_history: int
    recommendations: List[str]


class AgentHealthMonitor:
    def __init__(self, registry=platform_registry_service, coordination=task_coordination_service):
        self.registry = registry
        self.coordination = coordination

    def inspect_all(self) -> List[AgentHealth]:
        now = time.time()
        tasks = self.coordination.list_tasks()
        events = audit_log.list_events(limit=1000)
        results = []
        for agent in self.registry.registry.get_all_agents():
            history = [event for event in events if event.agent_id == agent.agent_id]
            failures = sum(event.event_type in ("mission.failed", "agent.failure") for event in history)
            recent_errors = sum(
                event.event_type in ("agent.error", "security.agent_identity_mismatch")
                for event in history
            )
            assigned = [task for task in tasks if task.assigned_agent_id == agent.agent_id]
            workload = sum(task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED) for task in assigned)
            age = max(0.0, now - agent.last_seen)
            uptime = max(0.0, now - agent.registered_at)
            recommendations = []
            critical = agent.status in (AgentStatus.OFFLINE, AgentStatus.ERROR) or age > self.registry.registry.offline_timeout_seconds * 2 or agent.state.battery_pct < 15
            warning = age > self.registry.registry.offline_timeout_seconds or agent.state.battery_pct < 35 or failures > 0 or recent_errors > 0
            if agent.state.battery_pct < 35:
                recommendations.append("Recharge before another long mission")
            if agent.status in (AgentStatus.OFFLINE, AgentStatus.ERROR) or age > self.registry.registry.offline_timeout_seconds:
                recommendations.append("Restore heartbeat connectivity and inspect recent task history")
            if workload > 1:
                recommendations.append("Rebalance assigned work")
            if failures:
                recommendations.append("Review failed task records before returning to duty")
            health = "CRITICAL" if critical else "WARNING" if warning else "HEALTHY"
            results.append(
                AgentHealth(
                    agent_id=agent.agent_id,
                    health=health,
                    battery_pct=agent.state.battery_pct,
                    status=agent.status.value,
                    available=agent.state.is_available,
                    connectivity_age_seconds=age,
                    uptime_seconds=uptime,
                    workload=workload,
                    failures=failures,
                    recent_errors=recent_errors,
                    task_history=len(assigned),
                    recommendations=recommendations,
                )
            )
        return results


agent_health_monitor = AgentHealthMonitor()