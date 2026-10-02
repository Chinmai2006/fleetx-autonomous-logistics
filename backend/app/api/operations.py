from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.agentic_orchestrator import agentic_orchestrator
from app.services.audit_log import AuditEvent, audit_log
from app.services.decision_engine import PlatformDecision, decision_engine
from app.services.health_monitor import AgentHealth, agent_health_monitor
from app.services.risk_engine import RiskEvent, risk_engine
from app.services.route_planner import RoutePlan, RoutePlanRequest, route_planner
from app.services.self_healing import HealingRecord, self_healing_engine
from app.services.analytics import FleetAnalytics, MissionAnalytics, platform_analytics
from app.services.security import require_role
from protocols.messages import TaskCreate

router = APIRouter()


@router.post("/routes/plan", response_model=RoutePlan)
async def plan_route(request: RoutePlanRequest):
    return route_planner.plan(request)


@router.post("/routes/optimize", response_model=PlatformDecision)
async def optimize_route(task: TaskCreate):
    decision = decision_engine.evaluate(task)
    audit_log.record(
        "decision.route_optimization",
        decision.summary,
        details={"decision_id": decision.decision_id, "route_cost": decision.route.route_cost if decision.route else None},
    )
    return decision


@router.post("/decisions/evaluate", response_model=PlatformDecision)
async def evaluate_decision(task: TaskCreate, role: str = Depends(require_role)):
    decision = decision_engine.evaluate(task)
    audit_log.record(
        "decision.evaluated",
        decision.summary,
        actor=role,
        details={"decision_id": decision.decision_id, "recommended_agent": decision.selected_agent_id},
    )
    return decision


@router.get("/decisions/recent", response_model=List[PlatformDecision])
async def recent_decisions(limit: int = Query(default=100, ge=1, le=500), role: str = Depends(require_role)):
    return decision_engine.recent(limit)


@router.get("/risks", response_model=List[RiskEvent])
async def list_risks(
    active_only: bool = Query(
        default=True,
        description="When true (default), suppresses AGENT_UNAVAILABLE alerts for offline agents with no active task assignments. Set false to see all historical agent alerts.",
    )
):
    return risk_engine.evaluate(active_only=active_only)


@router.get("/agents/{agent_id}/health", response_model=AgentHealth)
async def get_agent_health(agent_id: str):
    health = next((item for item in agent_health_monitor.inspect_all() if item.agent_id == agent_id), None)
    if health is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return health


@router.get("/self-healing", response_model=List[HealingRecord])
async def list_healing_records(task_id: Optional[str] = None, role: str = Depends(require_role)):
    return self_healing_engine.list_records(task_id)


@router.get("/audit", response_model=List[AuditEvent])
async def list_audit_events(
    event_type: Optional[str] = None,
    task_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=1000),
    role: str = Depends(require_role),
):
    return audit_log.list_events(event_type, task_id, agent_id, limit)


@router.get("/analytics/fleet", response_model=FleetAnalytics)
async def fleet_analytics():
    return platform_analytics.fleet()


@router.get("/analytics/missions/{task_id}", response_model=MissionAnalytics)
async def mission_analytics(task_id: str):
    analytics = platform_analytics.mission(task_id)
    if analytics is None:
        raise HTTPException(status_code=404, detail=f"Mission '{task_id}' not found")
    return analytics


@router.get("/agentic/intelligence")
async def intelligence_modules():
    return {
        "modules": [
            {"name": "Mission / Dispatch Intelligence", "status": "active"},
            {"name": "Route Optimization Intelligence", "status": "active"},
            {"name": "Fleet Optimization Intelligence", "status": "active"},
            {"name": "Risk & Safety Intelligence", "status": "active"},
            {"name": "Health / Maintenance Intelligence", "status": "active"},
        ],
        "workflow_count": len(agentic_orchestrator.list_states()),
        "llm_optional": True,
    }