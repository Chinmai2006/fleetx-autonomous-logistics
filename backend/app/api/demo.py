"""
Demo / test-harness endpoints.

These exist exclusively to support live demonstrations and integration tests.
They operate against REAL platform state — they do not fake or mock results.
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.services.audit_log import audit_log
from app.services.agentic_orchestrator import agentic_orchestrator
from app.services.platform_registry import platform_registry_service
from app.services.task_coordination import task_coordination_service
from protocols.messages import AgentStatus, TaskCreate, TaskStatus

router = APIRouter()


@router.post("/demo/agents/{agent_id}/fail", summary="Simulate agent failure mid-mission")
async def simulate_agent_failure(agent_id: str):
    """
    Force an agent into OFFLINE/ERROR state while it holds an active task.

    The platform's existing systems (agentic orchestrator, risk engine, self-healing)
    will detect the failure through their normal polling cycle and initiate replan +
    replacement negotiation exactly as they would for a real hardware failure.

    Only operates if the agent is currently ASSIGNED/IN_PROGRESS on a task.
    Does NOT fake healing results — those flow through the real MQTT negotiation path.
    """
    registry = platform_registry_service.registry
    agent = registry.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in registry")

    # Find an active task held by this agent
    tasks = task_coordination_service.list_tasks()
    active_task = next(
        (
            t for t in tasks
            if t.assigned_agent_id == agent_id
            and t.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS)
        ),
        None,
    )
    if active_task is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Agent '{agent_id}' has no active task assignment. "
                "Assign a mission first, then trigger failure."
            ),
        )

    # Push agent into OFFLINE state directly in registry
    with registry._lock:
        entry = registry._registry.get(agent_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not in internal registry")
        entry.status = AgentStatus.OFFLINE
        # Back-date last_seen beyond the offline timeout so the orchestrator
        # immediately sees the agent as disconnected on its next poll cycle.
        entry.last_seen = time.time() - registry.offline_timeout_seconds - 5.0
        entry.state.is_available = False
        entry.state.status = AgentStatus.OFFLINE

    audit_log.record(
        "demo.agent_failure_simulated",
        f"Demo: forced agent {agent_id} offline while holding task {active_task.task_id}",
        agent_id=agent_id,
        task_id=active_task.task_id,
        result="simulated",
        details={"trigger": "demo_endpoint", "affected_task": active_task.task_id},
    )

    # Ensure the parent task is tracked by the agentic orchestrator so that
    # its monitor loop can detect the failure and trigger replan/handoff.
    # Tasks created via POST /api/v1/tasks are not automatically registered;
    # we register them here on first failure so the self-healing path fires.
    parent_task_id = active_task.parent_task_id or active_task.task_id
    if agentic_orchestrator.get_state(parent_task_id) is None:
        parent_task = task_coordination_service.get_task(parent_task_id)
        if parent_task is not None:
            # Build a minimal TaskCreate from the parent task for the orchestrator request store
            request = TaskCreate(
                task_type=parent_task.task_type,
                origin=parent_task.origin,
                destination=parent_task.destination,
                payload_weight=parent_task.payload_weight,
                priority=parent_task.priority,
                deadline=parent_task.deadline,
                estimated_distance_km=parent_task.estimated_distance_km,
                required_capabilities=list(parent_task.required_capabilities),
                cooperative=True,
                metadata=dict(parent_task.metadata),
            )
            from app.services.agentic_orchestrator import AgenticExecutionState, AgenticPhase
            state = AgenticExecutionState(
                task_id=parent_task_id,
                max_replans=agentic_orchestrator.max_replans,
                phase=AgenticPhase.OBSERVE_RESULT,
                subtask_ids=list(parent_task.subtask_ids),
            )
            with agentic_orchestrator._lock:
                agentic_orchestrator._states[parent_task_id] = state
                agentic_orchestrator._requests[parent_task_id] = request

    return {
        "status": "failure_injected",
        "agent_id": agent_id,
        "affected_task_id": active_task.task_id,
        "affected_parent_task_id": active_task.parent_task_id,
        "message": (
            f"Agent {agent_id} forced offline. "
            "The agentic orchestrator will detect failure on its next poll "
            "and trigger replan → self-healing → replacement negotiation → handoff."
        ),
    }


@router.get("/demo/eligible-failure-agents", summary="List agents eligible for demo failure simulation")
async def eligible_failure_agents():
    """
    Returns agents that currently hold an active task assignment and could
    be meaningfully failed for a live demonstration.
    """
    registry = platform_registry_service.registry
    tasks = task_coordination_service.list_tasks()
    active_assignments: dict[str, str] = {
        t.assigned_agent_id: t.task_id
        for t in tasks
        if t.assigned_agent_id
        and t.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS)
    }
    now = time.time()
    result = []
    for agent_id, task_id in active_assignments.items():
        agent = registry.get_agent(agent_id)
        if agent and agent.status not in (AgentStatus.OFFLINE, AgentStatus.ERROR):
            result.append({
                "agent_id": agent_id,
                "agent_type": agent.agent_type,
                "status": agent.status.value,
                "battery_pct": agent.state.battery_pct,
                "active_task_id": task_id,
                "last_seen_seconds_ago": round(now - agent.last_seen, 1),
            })
    return result
