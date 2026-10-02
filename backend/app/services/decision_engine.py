from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.services.health_monitor import AgentHealthMonitor
from app.services.platform_registry import platform_registry_service
from app.services.risk_engine import RiskEngine
from app.services.route_planner import RoutePlan, RoutePlanner, route_planner
from app.services.task_coordination import task_coordination_service
from protocols.messages import AgentStatus, TaskCreate, TaskStatus


class DispatchCandidate(BaseModel):
    agent_id: str
    score: float
    eligible: bool
    factors: Dict[str, object] = Field(default_factory=dict)
    explanation: str


class PlatformDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: f"DEC-{uuid.uuid4().hex[:10].upper()}")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    task_type: str
    selected_agent_id: Optional[str] = None
    route: Optional[RoutePlan] = None
    candidates: List[DispatchCandidate] = Field(default_factory=list)
    risk_count: int = 0
    mission_priority_score: float = 0.0
    mission_priority_summary: str
    summary: str
    factors: List[str] = Field(default_factory=list)


class MissionDispatchIntelligence:
    def explain(self, request: TaskCreate) -> str:
        return f"Dispatch evaluation for {request.task_type} from {request.origin} to {request.destination}"


class RouteOptimizationIntelligence:
    def __init__(self, planner: RoutePlanner = route_planner):
        self.planner = planner

    def evaluate(self, request: TaskCreate) -> Optional[RoutePlan]:
        try:
            return self.planner.plan_task(request)
        except HTTPException:
            return None


class FleetOptimizationIntelligence:
    def __init__(self, registry=platform_registry_service, coordination=task_coordination_service):
        self.registry = registry
        self.coordination = coordination

    def candidates(
        self,
        request: TaskCreate,
        route: Optional[RoutePlan],
        risk_events=None,
        health_reports=None,
    ) -> List[DispatchCandidate]:
        tasks = self.coordination.list_tasks()
        risk_events = risk_events or []
        health_reports = health_reports or []
        health_by_agent = {report.agent_id: report.health for report in health_reports}
        load_by_agent: Dict[str, int] = {}
        for task in tasks:
            if task.assigned_agent_id and task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                load_by_agent[task.assigned_agent_id] = load_by_agent.get(task.assigned_agent_id, 0) + 1
        candidates = []
        now = time.time()
        for agent in self.registry.registry.get_all_agents():
            capability_match = set(request.required_capabilities).issubset(agent.capabilities)
            payload_match = agent.payload_capacity_kg >= request.payload_weight
            battery_ok = agent.state.battery_pct >= 20.0
            available = agent.status == AgentStatus.IDLE and agent.state.is_available and now - agent.last_seen <= self.registry.registry.offline_timeout_seconds
            deadline_feasible = True
            if request.deadline and route:
                deadline = request.deadline.replace(tzinfo=timezone.utc) if request.deadline.tzinfo is None else request.deadline
                deadline_feasible = datetime.now(timezone.utc).timestamp() + route.estimated_travel_time_minutes * 60 <= deadline.timestamp()
            health = health_by_agent.get(agent.agent_id, "WARNING")
            agent_risks = [risk.condition for risk in risk_events if risk.agent_id == agent.agent_id]
            risk_clear = not any(risk.severity == "CRITICAL" and risk.agent_id == agent.agent_id for risk in risk_events)
            factors: Dict[str, object] = {
                "capability_match": capability_match,
                "payload_capacity": payload_match,
                "battery_pct": agent.state.battery_pct,
                "available": available,
                "workload": load_by_agent.get(agent.agent_id, 0),
                "route_cost": route.route_cost if route else None,
                "deadline_feasible": deadline_feasible,
                "health": health,
                "risk_conditions": agent_risks,
            }
            eligible = capability_match and payload_match and battery_ok and available and deadline_feasible and health != "CRITICAL" and risk_clear
            battery_score = max(0.0, min(1.0, agent.state.battery_pct / 100.0))
            workload_score = 1.0 / (1.0 + load_by_agent.get(agent.agent_id, 0))
            route_score = 1.0 / (1.0 + route.route_cost) if route else 0.5
            deadline_score = float(deadline_feasible)
            health_score = 1.0 if health == "HEALTHY" else 0.6 if health == "WARNING" else 0.0
            score = 0.25 * battery_score + 0.20 * workload_score + 0.15 * route_score + 0.15 * float(capability_match and payload_match) + 0.15 * deadline_score + 0.10 * health_score
            reason = "eligible" if eligible else ", ".join(
                label for valid, label in (
                    (capability_match, "capability mismatch"),
                    (payload_match, "insufficient payload capacity"),
                    (battery_ok, "low battery"),
                    (available, "unavailable or stale heartbeat"),
                    (deadline_feasible, "deadline infeasible"),
                    (health != "CRITICAL", "critical health"),
                    (risk_clear, "critical operational risk"),
                ) if not valid
            )
            candidates.append(DispatchCandidate(agent_id=agent.agent_id, score=score, eligible=eligible, factors=factors, explanation=reason))
        return sorted(candidates, key=lambda candidate: (not candidate.eligible, -candidate.score, candidate.agent_id))


class RiskSafetyIntelligence:
    def __init__(self, engine: Optional[RiskEngine] = None):
        self.engine = engine or RiskEngine()

    def inspect(self):
        return self.engine.evaluate()


class HealthMaintenanceIntelligence:
    def __init__(self, monitor: Optional[AgentHealthMonitor] = None):
        self.monitor = monitor or AgentHealthMonitor()

    def inspect(self):
        return self.monitor.inspect_all()


class DecisionEngine:
    """Advisory ranker; its recommendation never replaces decentralized assignment."""

    def __init__(self, registry=platform_registry_service, coordination=task_coordination_service, planner: RoutePlanner = route_planner):
        self.dispatch = MissionDispatchIntelligence()
        self.routes = RouteOptimizationIntelligence(planner)
        self.fleet = FleetOptimizationIntelligence(registry, coordination)
        self.risk_safety = RiskSafetyIntelligence(RiskEngine(registry, coordination))
        self.health_maintenance = HealthMaintenanceIntelligence(AgentHealthMonitor(registry, coordination))
        self._decisions: List[PlatformDecision] = []

    def evaluate(self, request: TaskCreate) -> PlatformDecision:
        route = self.routes.evaluate(request)
        risks = self.risk_safety.inspect()
        health = self.health_maintenance.inspect()
        candidates = self.fleet.candidates(request, route, risks, health)
        eligible = next((candidate for candidate in candidates if candidate.eligible), None)
        selected = eligible.agent_id if eligible else None
        urgency = 0.5
        urgency_summary = "No deadline supplied; neutral urgency"
        if request.deadline:
            deadline = request.deadline.replace(tzinfo=timezone.utc) if request.deadline.tzinfo is None else request.deadline
            remaining_minutes = (deadline - datetime.now(timezone.utc)).total_seconds() / 60.0
            route_minutes = route.estimated_travel_time_minutes if route else 0.0
            urgency = 1.0 if remaining_minutes <= 0 else max(0.0, min(1.0, route_minutes / remaining_minutes))
            urgency_summary = "Deadline pressure included" if urgency > 0 else "Deadline currently feasible"
        mission_priority_score = round(request.priority / 5.0 * 0.7 + urgency * 0.3, 3)
        factors = ["capability match", "payload capacity", "battery", "availability", "workload"]
        if route:
            factors.append("route cost")
        if request.deadline:
            factors.append("deadline feasibility")
        factors.append("mission priority")
        summary = (
            f"{selected} is the top eligible dispatch candidate; final allocation remains with agent negotiation"
            if selected
            else "No currently eligible candidate; existing safety validation and negotiation must determine next action"
        )
        decision = PlatformDecision(
            task_type=request.task_type,
            selected_agent_id=selected,
            route=route,
            candidates=candidates,
            risk_count=len(risks),
            mission_priority_score=mission_priority_score,
            mission_priority_summary=urgency_summary,
            summary=summary,
            factors=factors,
        )
        self._decisions.append(decision)
        self._decisions = self._decisions[-1000:]
        return decision

    def recent(self, limit: int = 100) -> List[PlatformDecision]:
        return list(reversed(self._decisions[-max(1, min(limit, 500)):]))


decision_engine = DecisionEngine()