from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.audit_log import audit_log
from app.services.decision_engine import PlatformDecision, decision_engine
from app.services.planner import PlanningResult, RuleBasedPlanner, get_planner
from app.services.platform_registry import platform_registry_service
from app.services.self_healing import self_healing_engine
from app.services.task_coordination import task_coordination_service
from protocols.messages import AgentStatus, Task, TaskCreate, TaskStatus

logger = logging.getLogger("AgenticOrchestrator")


class AgenticPhase(str, Enum):
    OBSERVE = "OBSERVE"
    PLAN = "PLAN"
    VALIDATE = "VALIDATE"
    EXECUTE = "EXECUTE"
    OBSERVE_RESULT = "OBSERVE_RESULT"
    REPLAN = "REPLAN"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class AgenticObservation(BaseModel):
    observed_at: datetime = Field(default_factory=datetime.utcnow)
    summary: str
    task_status: Optional[str] = None
    agent_states: Dict[str, str] = Field(default_factory=dict)


class AgenticExecutionState(BaseModel):
    task_id: str
    phase: AgenticPhase = AgenticPhase.OBSERVE
    task: Optional[Task] = None
    current_plan: Optional[PlanningResult] = None
    subtask_ids: List[str] = Field(default_factory=list)
    assignments: Dict[str, Optional[str]] = Field(default_factory=dict)
    completed_subtasks: List[str] = Field(default_factory=list)
    failed_subtasks: List[str] = Field(default_factory=list)
    observations: List[AgenticObservation] = Field(default_factory=list)
    observation_summary: str = ""
    plan_summary: str = ""
    decision: Optional[PlatformDecision] = None
    healing_id: Optional[str] = None
    replan_count: int = 0
    max_replans: int
    replan_reason: Optional[str] = None
    requested_action: Optional[str] = None
    final_outcome: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgenticLogisticsTools:
    """Allow-listed wrappers over live registry, task coordinator, and workflow state."""

    def __init__(self, orchestrator: "AgenticOrchestrator"):
        self.orchestrator = orchestrator
        self.coordination = orchestrator.coordination
        self.registry = orchestrator.registry

    def get_fleet_state(self) -> List[dict]:
        return [entry.model_dump(mode="json") for entry in self.registry.registry.get_all_agents()]

    def get_agent_capabilities(self, agent_id: str) -> Optional[dict]:
        entry = self.registry.registry.get_agent(agent_id)
        if entry is None:
            return None
        return {
            "agent_id": entry.agent_id,
            "capabilities": list(entry.capabilities),
            "payload_capacity_kg": entry.payload_capacity_kg,
            "supported_operations": list(entry.supported_operations),
            "status": entry.status.value,
            "battery_pct": entry.state.battery_pct,
            "is_available": entry.state.is_available,
        }

    def inspect_task(self, task_id: str) -> dict:
        task = self.coordination.get_task(task_id)
        if task is None:
            return {"task": None, "subtasks": []}
        return {
            "task": task.model_dump(mode="json"),
            "subtasks": [item.model_dump(mode="json") for item in self.coordination.get_subtasks(task_id)],
        }

    def create_decomposition_plan(self, request: TaskCreate, task_id: str) -> PlanningResult:
        plan = self.orchestrator._resolve_plan(request, task_id)
        self.orchestrator.validate_plan(request, plan)
        return plan

    def request_task_negotiation(self, task_id: str) -> bool:
        return self.coordination.request_task_negotiation(task_id)

    def request_handoff(self, task_id: str, reason: str) -> bool:
        return self.coordination.request_agentic_handoff(task_id, reason)

    def inspect_execution_status(self, task_id: str) -> Optional[dict]:
        state = self.orchestrator.get_state(task_id)
        return state.model_dump(mode="json") if state else None

    def invoke(self, tool_name: str, **arguments: Any) -> Any:
        tools = {
            "get_fleet_state": self.get_fleet_state,
            "get_agent_capabilities": self.get_agent_capabilities,
            "inspect_task": self.inspect_task,
            "create_decomposition_plan": self.create_decomposition_plan,
            "request_task_negotiation": self.request_task_negotiation,
            "request_handoff": self.request_handoff,
            "inspect_execution_status": self.inspect_execution_status,
        }
        if tool_name not in tools:
            raise ValueError(f"Unsupported logistics tool: {tool_name}")
        return tools[tool_name](**arguments)


class AgenticOrchestrator:
    """Bounded observe/plan/validate/delegate/observe workflow."""

    def __init__(
        self,
        coordination=task_coordination_service,
        registry=platform_registry_service,
        max_replans: Optional[int] = None,
        poll_interval_seconds: float = 0.25,
    ):
        self.coordination = coordination
        self.registry = registry
        self.max_replans = max(0, max_replans if max_replans is not None else settings.AGENTIC_MAX_REPLANS)
        self.poll_interval_seconds = max(0.05, poll_interval_seconds)
        self.tools = AgenticLogisticsTools(self)
        self._states: Dict[str, AgenticExecutionState] = {}
        self._requests: Dict[str, TaskCreate] = {}
        self._lock = threading.RLock()
        self._running = False
        self._monitor: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._monitor = threading.Thread(target=self._monitor_loop, name="AgenticOrchestrator", daemon=True)
        self._monitor.start()

    def stop(self) -> None:
        self._running = False
        if self._monitor and self._monitor is not threading.current_thread():
            self._monitor.join(timeout=1.0)

    def create_task(self, request: TaskCreate) -> Task:
        task_id = f"TASK-{os.urandom(4).hex().upper()}"
        state = AgenticExecutionState(task_id=task_id, max_replans=self.max_replans)
        with self._lock:
            self._states[task_id] = state
            self._requests[task_id] = request.model_copy(deep=True)

        try:
            self._record_observation(state, "Observed current fleet and task request")
            state.decision = decision_engine.evaluate(request)
            audit_log.record(
                "decision.dispatch",
                state.decision.summary,
                task_id=task_id,
                details={
                    "decision_id": state.decision.decision_id,
                    "selected_candidate": state.decision.selected_agent_id,
                    "factors": state.decision.factors,
                },
            )
            state.phase = AgenticPhase.PLAN
            plan = self._resolve_plan(request, task_id)
            state.current_plan = plan
            state.plan_summary = plan.reasoning_summary
            state.phase = AgenticPhase.VALIDATE
            # Use require_live_agents=False: the agentic orchestrator is designed to handle
            # agent unavailability dynamically through replan/handoff. Blocking here because
            # an agent is momentarily BUSY would prevent valid missions from being created.
            self.validate_plan(request, plan, require_live_agents=False)
            state.phase = AgenticPhase.EXECUTE
            state.requested_action = "Delegate subtasks through existing MQTT negotiation"
            task = self.coordination.create_task_with_plan(request, plan)
            state.task_id = task.task_id
            state.task = task
            state.subtask_ids = list(task.subtask_ids)
            state.phase = AgenticPhase.OBSERVE_RESULT
            self.observe_execution(task.task_id)
            return task
        except HTTPException:
            state.phase = AgenticPhase.FAILED
            state.updated_at = datetime.utcnow()
            raise
        except ValueError as exc:
            state.phase = AgenticPhase.FAILED
            state.final_outcome = f"Agentic task rejected: {exc}"
            state.updated_at = datetime.utcnow()
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            state.phase = AgenticPhase.FAILED
            state.final_outcome = f"Agentic task failed: {exc}"
            state.updated_at = datetime.utcnow()
            raise HTTPException(status_code=500, detail=f"Agentic orchestration error: {exc}")

    def _resolve_plan(self, request: TaskCreate, task_id: str) -> PlanningResult:
        try:
            candidate = get_planner().plan(request, task_id)
            if candidate is None:
                raise ValueError("Planner returned no plan")
            plan = PlanningResult.model_validate(candidate)
            if plan.task_id != task_id:
                raise ValueError("Planner task_id does not match request")
            return plan
        except Exception:
            logger.exception("Planner unavailable or invalid; using RuleBasedPlanner")
            fallback = RuleBasedPlanner().plan(request, task_id)
            if fallback is None:
                raise HTTPException(status_code=422, detail="No deterministic plan is available")
            return PlanningResult.model_validate(fallback)

    def validate_plan(
        self,
        request: TaskCreate,
        plan: PlanningResult,
        require_live_agents: bool = True,
    ) -> None:
        plan = PlanningResult.model_validate(plan)
        if not plan.subtasks:
            raise ValueError("A cooperative plan must contain subtasks")
        known_agents = self.registry.registry.get_all_agents()
        for step in plan.subtasks:
            if not step.origin.strip() or not step.destination.strip():
                raise ValueError("Subtask origin and destination are required")
            if not step.required_capabilities:
                raise ValueError(f"Subtask {step.subtask_type} has no required capabilities")
            if not math.isfinite(step.estimated_distance_km) or step.estimated_distance_km < 0:
                raise ValueError(f"Subtask {step.subtask_type} has invalid distance")
            if require_live_agents and known_agents and not any(
                entry.status != AgentStatus.OFFLINE
                and entry.state.is_available
                and entry.state.battery_pct >= 20.0
                and set(step.required_capabilities).issubset(entry.capabilities)
                and entry.payload_capacity_kg >= request.payload_weight
                for entry in known_agents
            ):
                raise ValueError(f"No currently eligible agent can perform {step.subtask_type}")

    def observe_execution(self, task_id: str) -> Optional[AgenticExecutionState]:
        with self._lock:
            state = self._states.get(task_id)
            if state is None:
                return None
            self.registry.registry.check_offline_agents()
            snapshot = self.tools.inspect_task(task_id)
            if snapshot["task"] is None:
                return state.model_copy(deep=True)
            task = Task.model_validate(snapshot["task"])
            subtasks = [Task.model_validate(item) for item in snapshot["subtasks"]]
            state.task = task
            state.subtask_ids = [item.task_id for item in subtasks]
            state.assignments = {item.task_id: item.assigned_agent_id for item in subtasks}
            completed = {item.task_id for item in subtasks if item.status == TaskStatus.COMPLETED}
            state.completed_subtasks = sorted(set(state.completed_subtasks) | completed)
            state.observation_summary = (
                f"Task {task.task_id} is {task.status.value}; "
                f"{len(state.completed_subtasks)}/{len(subtasks)} subtasks completed"
            )
            agent_states: Dict[str, str] = {}
            for item in subtasks:
                if item.assigned_agent_id:
                    agent = self.registry.registry.get_agent(item.assigned_agent_id)
                    agent_states[item.assigned_agent_id] = agent.status.value if agent else "UNKNOWN"
            self._append_observation(state, state.observation_summary, task.status.value, agent_states)
            if task.status == TaskStatus.COMPLETED:
                state.phase = AgenticPhase.COMPLETE
                if state.final_outcome is None:
                    state.final_outcome = f"Task completed; all {len(subtasks)} subtasks completed"
                if state.healing_id and state.failed_subtasks:
                    recovered = next((item for item in subtasks if item.task_id == state.failed_subtasks[-1]), None)
                    # single-task: the task itself is the recovered item
                    if recovered is None and task.task_id == (state.failed_subtasks[-1] if state.failed_subtasks else None):
                        recovered = task
                    if recovered and recovered.assigned_agent_id and recovered.handoff_state.value == "REPLACED":
                        self_healing_engine.mark_recovered(state.healing_id, recovered.assigned_agent_id)
            elif state.phase not in (AgenticPhase.REPLAN, AgenticPhase.FAILED):
                state.phase = AgenticPhase.OBSERVE_RESULT
            state.updated_at = datetime.utcnow()
            return state.model_copy(deep=True)

    def get_state(self, task_id: str) -> Optional[AgenticExecutionState]:
        with self._lock:
            state = self._states.get(task_id)
            return state.model_copy(deep=True) if state else None

    def list_states(self) -> List[AgenticExecutionState]:
        with self._lock:
            return [state.model_copy(deep=True) for state in self._states.values()]

    def process_once(self) -> None:
        with self._lock:
            task_ids = [key for key, value in self._states.items() if value.phase not in (AgenticPhase.COMPLETE, AgenticPhase.FAILED)]
        for task_id in task_ids:
            self._process_task(task_id)

    def _process_task(self, task_id: str) -> None:
        state = self.observe_execution(task_id)
        if state is None or state.phase in (AgenticPhase.COMPLETE, AgenticPhase.FAILED):
            return
        snapshot = self.tools.inspect_task(task_id)
        if snapshot["task"] is None:
            return
        task = Task.model_validate(snapshot["task"])
        subtasks = [Task.model_validate(item) for item in snapshot["subtasks"]]

        failure = None

        # --- cooperative path: check each subtask ---
        for subtask in subtasks:
            if subtask.status == TaskStatus.FAILED:
                failure = (subtask, f"Subtask {subtask.task_id} reported FAILED")
                break
            if subtask.assigned_agent_id and subtask.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS):
                agent = self.registry.registry.get_agent(subtask.assigned_agent_id)
                if agent is None or agent.status in (AgentStatus.OFFLINE, AgentStatus.ERROR):
                    failure = (subtask, f"Assigned agent {subtask.assigned_agent_id} is unavailable")
                    break

        # --- single-task path: no subtasks, check the task itself ---
        if not subtasks and not failure:
            if task.status == TaskStatus.FAILED:
                failure = (task, f"Task {task.task_id} reported FAILED")
            elif task.assigned_agent_id and task.status in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS):
                agent = self.registry.registry.get_agent(task.assigned_agent_id)
                if agent is None or agent.status in (AgentStatus.OFFLINE, AgentStatus.ERROR):
                    failure = (task, f"Assigned agent {task.assigned_agent_id} is unavailable")

        if failure:
            self._replan_and_handoff(task_id, failure[0], failure[1])
            return

        with self._lock:
            current = self._states[task_id]
            healing_id = current.healing_id
            failed_subtask_id = current.failed_subtasks[-1] if current.failed_subtasks else None
        if healing_id and failed_subtask_id:
            recovered = next((item for item in subtasks if item.task_id == failed_subtask_id), None)
            # for single tasks the recovered item is the task itself
            if recovered is None and task.task_id == failed_subtask_id:
                recovered = task
            if recovered and recovered.handoff_state.value == "REPLACED" and recovered.assigned_agent_id:
                self_healing_engine.mark_recovered(healing_id, recovered.assigned_agent_id)
        rejected = next((item for item in subtasks if item.handoff_state.value == "REJECTED"), None)
        # for single tasks check the task itself
        if rejected is None and not subtasks and task.handoff_state.value == "REJECTED":
            rejected = task
        if rejected:
            with self._lock:
                current = self._states[task_id]
                current.phase = AgenticPhase.FAILED
                current.final_outcome = f"No replacement accepted subtask {rejected.task_id}"
                if current.healing_id:
                    self_healing_engine.mark_handoff(current.healing_id, "REJECTED")
                current.updated_at = datetime.utcnow()

    def _replan_and_handoff(self, task_id: str, failed_subtask: Task, reason: str) -> None:
        with self._lock:
            state = self._states.get(task_id)
            request = self._requests.get(task_id)
            if state is None or request is None or state.phase in (AgenticPhase.REPLAN, AgenticPhase.COMPLETE, AgenticPhase.FAILED):
                return
            if failed_subtask.task_id not in state.failed_subtasks:
                state.failed_subtasks.append(failed_subtask.task_id)
                healing = self_healing_engine.detect(
                    task_id,
                    failed_subtask,
                    reason,
                    request.payload_weight,
                )
                state.healing_id = healing.healing_id
            if state.replan_count >= state.max_replans:
                state.phase = AgenticPhase.FAILED
                state.replan_reason = reason
                state.final_outcome = f"Maximum replans ({state.max_replans}) reached; task stopped safely"
                if state.healing_id:
                    self_healing_engine.mark_handoff(state.healing_id, "REPLAN_LIMIT_REACHED")
                state.updated_at = datetime.utcnow()
                return
            state.phase = AgenticPhase.REPLAN
            state.replan_count += 1
            state.replan_reason = reason
            state.updated_at = datetime.utcnow()
            audit_log.record(
                "mission.replanned",
                reason,
                task_id=task_id,
                details={"replan_count": state.replan_count, "failed_subtask_id": failed_subtask.task_id},
            )

        revised_request = request.model_copy(deep=True)
        revised_request.metadata = {
            **revised_request.metadata,
            "agentic_replan_reason": reason,
            "failed_subtask_id": failed_subtask.task_id,
            "previous_assignment": failed_subtask.assigned_agent_id,
        }
        # Determine whether this is a single non-cooperative task or a cooperative subtask.
        is_single_task = not failed_subtask.parent_task_id and not failed_subtask.is_parent
        revised_plan = None
        try:
            if is_single_task:
                # Skip cooperative decomposition; validate replacement eligibility directly.
                # Small bounded wait: a dynamically launched replacement agent may not yet
                # have completed MQTT registration when this check first runs.  Poll for up
                # to _REPLACEMENT_WAIT_SECONDS before treating absence as a permanent failure.
                if not self._wait_for_eligible_replacement_for_task(failed_subtask, revised_request.payload_weight):
                    raise ValueError("No currently eligible replacement can perform the failed task")
            else:
                revised_plan = self._resolve_plan(revised_request, task_id)
                self.validate_plan(revised_request, revised_plan, require_live_agents=False)
                matching_step = next(
                    (
                        step for step in revised_plan.subtasks
                        if step.subtask_type == failed_subtask.subtask_type
                        and set(step.required_capabilities) == set(failed_subtask.required_capabilities)
                    ),
                    None,
                )
                if matching_step is None:
                    raise ValueError("Revised plan changed the failed subtask safety contract")
                # Small bounded wait: a dynamically launched replacement agent may not yet
                # have completed MQTT registration when this check first runs.
                if not self._wait_for_eligible_replacement(matching_step, revised_request.payload_weight):
                    raise ValueError("No currently eligible replacement can perform the failed subtask")
        except Exception as exc:
            with self._lock:
                state = self._states[task_id]
                state.phase = AgenticPhase.FAILED
                state.final_outcome = f"Replan rejected by deterministic validation: {exc}"
                if state.healing_id:
                    self_healing_engine.mark_handoff(state.healing_id, "VALIDATION_REJECTED")
                state.updated_at = datetime.utcnow()
            return

        with self._lock:
            state = self._states[task_id]
            if not is_single_task:
                state.current_plan = revised_plan
                state.plan_summary = revised_plan.reasoning_summary
            state.requested_action = f"request_handoff({failed_subtask.task_id}) via existing negotiation"
            state.phase = AgenticPhase.EXECUTE
        accepted = self.tools.invoke("request_handoff", task_id=failed_subtask.task_id, reason=reason)
        with self._lock:
            state = self._states[task_id]
            if accepted:
                state.phase = AgenticPhase.OBSERVE_RESULT
                if state.healing_id:
                    self_healing_engine.mark_handoff(state.healing_id, "REQUESTED")
                self._append_observation(state, f"Requested replacement for {failed_subtask.task_id}", failed_subtask.status.value, {})
            else:
                state.phase = AgenticPhase.FAILED
                state.final_outcome = f"Existing coordination rejected handoff for {failed_subtask.task_id}"
                if state.healing_id:
                    self_healing_engine.mark_handoff(state.healing_id, "REQUEST_FAILED")
            state.updated_at = datetime.utcnow()

    # Seconds to wait for a dynamically registered replacement to appear in the registry.
    # Bounded to avoid holding up the monitor loop indefinitely; if no replacement appears
    # within this window the existing deterministic failure path is preserved.
    _REPLACEMENT_WAIT_SECONDS: float = 3.0
    _REPLACEMENT_POLL_SECONDS: float = 0.25

    def _wait_for_eligible_replacement(self, step, payload_weight: float) -> bool:
        """Poll for replacement eligibility up to _REPLACEMENT_WAIT_SECONDS.

        A dynamically launched agent may not yet have completed MQTT registration
        when _replan_and_handoff first checks.  This gives the registry a bounded
        window to synchronize before the check is treated as a permanent failure.
        replan_count is NOT incremented here; this wait happens inside a single
        replan attempt.
        """
        deadline = time.time() + self._REPLACEMENT_WAIT_SECONDS
        while True:
            if self._has_eligible_replacement(step, payload_weight):
                return True
            remaining = deadline - time.time()
            if remaining <= 0:
                return False
            time.sleep(min(self._REPLACEMENT_POLL_SECONDS, remaining))

    def _wait_for_eligible_replacement_for_task(self, task: Task, payload_weight: float) -> bool:
        """Poll for single-task replacement eligibility up to _REPLACEMENT_WAIT_SECONDS."""
        deadline = time.time() + self._REPLACEMENT_WAIT_SECONDS
        while True:
            if self._has_eligible_replacement_for_task(task, payload_weight):
                return True
            remaining = deadline - time.time()
            if remaining <= 0:
                return False
            time.sleep(min(self._REPLACEMENT_POLL_SECONDS, remaining))

    def _has_eligible_replacement(self, step, payload_weight: float) -> bool:
        now = time.time()
        return any(
            entry.status == AgentStatus.IDLE
            and entry.state.is_available
            and entry.state.battery_pct >= 20.0
            and set(step.required_capabilities).issubset(entry.capabilities)
            and entry.payload_capacity_kg >= payload_weight
            and now - entry.last_seen <= self.registry.registry.offline_timeout_seconds
            for entry in self.registry.registry.get_all_agents()
        )

    def _has_eligible_replacement_for_task(self, task: Task, payload_weight: float) -> bool:
        """Check replacement eligibility for a single non-cooperative task."""
        now = time.time()
        return any(
            entry.agent_id != task.assigned_agent_id
            and entry.status == AgentStatus.IDLE
            and entry.state.is_available
            and entry.state.battery_pct >= 20.0
            and set(task.required_capabilities).issubset(entry.capabilities)
            and entry.payload_capacity_kg >= payload_weight
            and now - entry.last_seen <= self.registry.registry.offline_timeout_seconds
            for entry in self.registry.registry.get_all_agents()
        )

    def _record_observation(self, state: AgenticExecutionState, summary: str) -> None:
        fleet = self.tools.get_fleet_state()
        self._append_observation(state, summary, None, {entry["agent_id"]: entry["status"] for entry in fleet})
        state.observation_summary = summary

    @staticmethod
    def _append_observation(state: AgenticExecutionState, summary: str, task_status: Optional[str], agent_states: Dict[str, str]) -> None:
        state.observations.append(AgenticObservation(summary=summary, task_status=task_status, agent_states=agent_states))
        state.observations = state.observations[-50:]

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self.process_once()
            except Exception:
                logger.exception("Agentic observation cycle failed")
            time.sleep(self.poll_interval_seconds)


agentic_orchestrator = AgenticOrchestrator()