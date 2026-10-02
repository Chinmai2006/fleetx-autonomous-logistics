from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel

from app.services.platform_registry import platform_registry_service
from app.services.task_coordination import task_coordination_service
from protocols.messages import AgentStatus, TaskStatus


class RiskEvent(BaseModel):
    risk_id: str
    severity: Literal["INFO", "WARNING", "CRITICAL"]
    condition: str
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    recommended_action: str
    detected_at: datetime


class RiskEngine:
    LOW_BATTERY_WARNING_PCT = 35.0
    LOW_BATTERY_CRITICAL_PCT = 20.0
    MAX_ROUTE_COST = 100.0

    def __init__(self, registry=platform_registry_service, coordination=task_coordination_service):
        self.registry = registry
        self.coordination = coordination

    def evaluate(self, active_only: bool = False) -> List[RiskEvent]:
        """Evaluate operational risks across the fleet.

        When active_only=True, AGENT_UNAVAILABLE alerts are only raised for
        offline agents that still have active (non-terminal) task assignments.
        This prevents stale historical/test agents from flooding the alert panel
        while preserving legitimate connectivity failures.
        """
        agents = self.registry.registry.get_all_agents()
        tasks = self.coordination.list_tasks()
        active_tasks = [task for task in tasks if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)]
        workload = {}
        for task in active_tasks:
            if task.assigned_agent_id:
                workload[task.assigned_agent_id] = workload.get(task.assigned_agent_id, 0) + 1
        risks: List[RiskEvent] = []

        def add(severity, condition, action, agent_id=None, task_id=None):
            identity = f"{severity}:{condition}:{agent_id or ''}:{task_id or ''}"
            risks.append(
                RiskEvent(
                    risk_id=identity,
                    severity=severity,
                    condition=condition,
                    agent_id=agent_id,
                    task_id=task_id,
                    recommended_action=action,
                    detected_at=datetime.now(timezone.utc),
                )
            )

        for agent in agents:
            archived = bool(agent.metadata.get("archived"))
            age = max(0.0, datetime.now(timezone.utc).timestamp() - agent.last_seen)
            is_offline = agent.status == AgentStatus.OFFLINE or age > self.registry.registry.offline_timeout_seconds
            has_active_work = workload.get(agent.agent_id, 0) > 0

            if not archived and is_offline:
                # In active_only mode: only alert if the offline agent has active work
                # that needs to be handed off. Pure historical agents are skipped.
                if not active_only or has_active_work:
                    add("CRITICAL", "AGENT_UNAVAILABLE", "Restore connectivity or hand off assigned work", agent_id=agent.agent_id)

            # ERROR status always warrants an alert regardless of mode
            if agent.status == AgentStatus.ERROR:
                add("CRITICAL", "AGENT_ERROR", "Inspect agent and reassign active work", agent_id=agent.agent_id)

            # Battery alerts only for non-archived, non-purely-offline historical agents
            if not archived and not (is_offline and not has_active_work):
                if agent.state.battery_pct < self.LOW_BATTERY_CRITICAL_PCT:
                    add("CRITICAL", "LOW_BATTERY", "Recharge or exclude from new assignments", agent_id=agent.agent_id)
                elif agent.state.battery_pct < self.LOW_BATTERY_WARNING_PCT:
                    add("WARNING", "LOW_BATTERY", "Schedule charging before the next mission", agent_id=agent.agent_id)

            if workload.get(agent.agent_id, 0) > 1:
                add("WARNING", "AGENT_OVERLOADED", "Rebalance work through decentralized negotiation", agent_id=agent.agent_id)

        for task in tasks:
            if task.status == TaskStatus.FAILED:
                add("CRITICAL", "MISSION_FAILED", "Observe failure and request safe replanning", task_id=task.task_id, agent_id=task.assigned_agent_id)
            if task.estimated_cost is not None and task.estimated_cost > self.MAX_ROUTE_COST:
                add("WARNING", "EXCESSIVE_ROUTE_COST", "Review route distance, payload, and priority", task_id=task.task_id)
            if task.deadline and task.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED):
                seconds_left = (task.deadline.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds() if task.deadline.tzinfo is None else (task.deadline - datetime.now(timezone.utc)).total_seconds()
                estimated_seconds = ((task.estimated_distance_km or 0.0) / 20.0) * 3600.0
                if seconds_left <= 0 or seconds_left < estimated_seconds:
                    add("WARNING", "DEADLINE_RISK", "Reprioritize or select a feasible route and agent", task_id=task.task_id)
            if task.assigned_agent_id:
                agent = self.registry.registry.get_agent(task.assigned_agent_id)
                if agent and agent.payload_capacity_kg < task.payload_weight:
                    add("CRITICAL", "INSUFFICIENT_PAYLOAD_CAPACITY", "Reject assignment and renegotiate safely", agent_id=agent.agent_id, task_id=task.task_id)
        return risks


risk_engine = RiskEngine()