import copy
import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional, Set, Any

import paho.mqtt.client as mqtt
from fastapi import HTTPException

from app.core.config import settings
from app.services.audit_log import audit_log
from app.services.platform_registry import platform_registry_service
from app.services.task_decomposition import decompose_task, should_decompose
from protocols.messages import (
    AgentEvent,
    AgentIdentity,
    AgentState,
    AgentStatus,
    EventType,
    HandoffState,
    MQTTMessagePayload,
    NegotiationAgreementPayload,
    NegotiationRequestPayload,
    NegotiationResponsePayload,
    NegotiationStatus,
    SubtaskCompletedPayload,
    SubtaskStatusUpdatePayload,
    Task,
    TaskAnnouncementPayload,
    TaskAssignmentPayload,
    TaskCreate,
    TaskHandoffDecisionPayload,
    TaskHandoffRequestPayload,
    TaskProposalPayload,
    TaskRejectPayload,
    TaskStatus,
    TaskStatusUpdatePayload,
)

logger = logging.getLogger("TaskCoordinationService")


class ProposalSafetyValidator:
    """Recheck hard constraints without ranking agent proposals."""

    MINIMUM_BATTERY_PCT = 20.0

    def __init__(self, registry):
        self.registry = registry

    def rejection_reason(
        self,
        task: Task,
        proposal: TaskProposalPayload,
        excluded_agent_ids: Optional[Set[str]] = None,
    ) -> Optional[str]:
        if excluded_agent_ids and proposal.agent_id in excluded_agent_ids:
            return "HANDOFF_REQUESTER_EXCLUDED"
        agent = self.registry.get_agent(proposal.agent_id)
        if not agent or agent.status == AgentStatus.OFFLINE:
            return "AGENT_NOT_REGISTERED_OR_OFFLINE"
        if agent.status != AgentStatus.IDLE or not agent.state.is_available or not proposal.available:
            return "AGENT_UNAVAILABLE"
        if time.time() - agent.last_seen > self.registry.offline_timeout_seconds:
            return "AGENT_OFFLINE_TIMEOUT"
        constraints = agent.metadata.get("operational_constraints", {})
        minimum_battery_pct = max(
            self.MINIMUM_BATTERY_PCT,
            float(constraints.get("minimum_battery_pct", self.MINIMUM_BATTERY_PCT)),
        )
        if proposal.battery_pct < minimum_battery_pct or agent.state.battery_pct < minimum_battery_pct:
            return "INSUFFICIENT_BATTERY"
        maximum_distance_km = constraints.get("maximum_distance_km")
        if maximum_distance_km is not None and (task.estimated_distance_km or 0.0) > float(maximum_distance_km):
            return "MAXIMUM_ROUTE_DISTANCE_EXCEEDED"
        if task.task_type in constraints.get("excluded_task_types", []):
            return "TASK_TYPE_NOT_ALLOWED"
        if not proposal.capability_match or not set(task.required_capabilities).issubset(proposal.capabilities):
            return "MISSING_CAPABILITIES"
        # Only recheck registered capabilities when the registry entry is populated.
        # An empty registry capability list means the agent has not yet re-advertised
        # (e.g. after a backend restart) — do not reject a valid self-attested proposal
        # in that case, as it would permanently drop proposals that should be eligible.
        if agent.capabilities and not set(task.required_capabilities).issubset(agent.capabilities):
            return "REGISTERED_CAPABILITY_MISMATCH"
        if proposal.payload_capacity_kg < task.payload_weight or agent.payload_capacity_kg < task.payload_weight:
            return "PAYLOAD_CAPACITY_EXCEEDED"
        if task.deadline and task.deadline.timestamp() <= time.time():
            return "DEADLINE_EXPIRED"
        return None


class TaskCoordinationService:
    """Coordinates task lifecycle events while leaving eligibility decisions to agents."""

    def __init__(self, proposal_window_seconds: float = 1.0, negotiation_window_seconds: float = 1.0):
        self.proposal_window_seconds = proposal_window_seconds
        self.negotiation_window_seconds = negotiation_window_seconds
        self.safety_validator = ProposalSafetyValidator(platform_registry_service.registry)
        self._tasks: Dict[str, Task] = {}
        self._negotiation_responses: Dict[str, Dict[str, NegotiationResponsePayload]] = {}
        self._negotiation_accepts: Dict[str, set[str]] = {}
        self._handoff_excluded: Dict[str, Set[str]] = {}
        self._pending_assignments: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._responses = threading.Condition(self._lock)
        self._running = False
        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"fastapi-task-coordinator-{os.getpid()}",
            )
        except AttributeError:
            self._client = mqtt.Client(client_id=f"fastapi-task-coordinator-{os.getpid()}")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        if settings.MQTT_USERNAME:
            self._client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD or None)
        if settings.MQTT_TLS_CA_CERT:
            self._client.tls_set(
                ca_certs=settings.MQTT_TLS_CA_CERT,
                certfile=settings.MQTT_TLS_CERTFILE or None,
                keyfile=settings.MQTT_TLS_KEYFILE or None,
            )

    def start(self) -> None:
        if self._running:
            return
        try:
            self._client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, 60)
            self._client.loop_start()
            self._running = True
            logger.info("TaskCoordinationService started.")
        except Exception:
            logger.exception("Failed to start TaskCoordinationService")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._client.loop_stop()
        self._client.disconnect()

    def create_task(self, request: TaskCreate) -> Task:
        if not self._client.is_connected():
            raise HTTPException(status_code=503, detail="Task MQTT coordinator is not connected")

        # Phase 5: Intelligent Planning
        from app.services.planner import PlanningResult, RuleBasedPlanner, get_planner
        planning_task_id = f"TASK-{os.urandom(4).hex().upper()}"
        plan = None
        try:
            candidate_plan = get_planner().plan(request, planning_task_id)
            if candidate_plan is not None:
                plan = PlanningResult.model_validate(candidate_plan)
                if not plan.subtasks or plan.task_id != planning_task_id:
                    plan = None
        except Exception:
            logger.exception("Intelligent planner failed; using deterministic fallback")

        if plan is None:
            try:
                plan = RuleBasedPlanner().plan(request, planning_task_id)
            except Exception:
                logger.exception("Deterministic rule-based planner failed")

        if plan and plan.subtasks:
            return self._create_planned_cooperative_task(request, plan)
        elif should_decompose(request):
            return self._create_cooperative_task(request)

        task = Task(**request.model_dump(exclude={"cooperative"}))
        if plan:
            task.plan_id = plan.plan_id
            task.reasoning_summary = plan.reasoning_summary
            task.estimated_cost = plan.estimated_cost
            task.confidence = plan.confidence
            task.fallback_status = plan.fallback_status

        with self._lock:
            self._tasks[task.task_id] = task
            task.status = TaskStatus.ANNOUNCED
            task.negotiation_status = NegotiationStatus.COLLECTING_PROPOSALS
        audit_log.record("mission.created", f"Created mission {task.task_id}", task_id=task.task_id)

        announcement = TaskAnnouncementPayload(task=task)
        if not self._publish(
            EventType.TASK_ANNOUNCEMENT,
            announcement.model_dump(),
            "logistics/broadcast/tasks",
        ):
            with self._lock:
                task.status = TaskStatus.FAILED
            raise HTTPException(status_code=503, detail="Could not publish task announcement")
        logger.info("Task %s announced over MQTT", task.task_id)

        deadline = time.monotonic() + self.proposal_window_seconds
        with self._responses:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._responses.wait(remaining)
            self._negotiate(task)
            return copy.deepcopy(task)

    def create_task_with_plan(self, request: TaskCreate, plan: Any) -> Task:
        """Delegate an already validated plan through the existing MQTT allocator."""
        if not self._client.is_connected():
            raise HTTPException(status_code=503, detail="Task MQTT coordinator is not connected")
        from app.services.planner import PlanningResult

        validated_plan = PlanningResult.model_validate(plan)
        if not validated_plan.subtasks:
            raise HTTPException(status_code=422, detail="Agentic plan must contain subtasks")
        return self._create_planned_cooperative_task(request, validated_plan)

    def request_task_negotiation(self, task_id: str) -> bool:
        """Re-announce an unassigned task through existing decentralized negotiation."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.assigned_agent_id is not None:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
                return False
        self._announce_and_allocate(
            task,
            announcement_event=(EventType.SUBTASK_ANNOUNCEMENT if task.is_subtask else EventType.TASK_ANNOUNCEMENT),
        )
        return task.assigned_agent_id is not None

    def request_agentic_handoff(self, task_id: str, reason: str) -> bool:
        """Route an observed failure through the existing handoff negotiation path."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.assigned_agent_id is None:
                return False
            handoff = TaskHandoffRequestPayload(
                task_id=task_id,
                parent_task_id=task.parent_task_id,
                from_agent_id=task.assigned_agent_id,
                reason=reason,
            )
        self._begin_handoff(handoff)
        return True

    def _create_planned_cooperative_task(self, request: TaskCreate, plan: Any) -> Task:
        """Create a cooperative task guided by the Intelligent Planner's output."""
        payload = request.model_dump(exclude={"cooperative"})
        if payload.get("task_type") == "delivery":
            payload["task_type"] = "cooperative_delivery"
        metadata = dict(payload.get("metadata") or {})
        metadata["cooperative"] = True
        payload["metadata"] = metadata
        
        parent = Task(**payload, is_parent=True, task_id=plan.task_id)
        parent.plan_id = plan.plan_id
        parent.reasoning_summary = plan.reasoning_summary
        parent.estimated_cost = plan.estimated_cost
        parent.confidence = plan.confidence
        parent.fallback_status = plan.fallback_status
        
        subtasks = []
        for index, step in enumerate(plan.subtasks, start=1):
            subtask_id = f"{parent.task_id}-ST{index}"
            subtasks.append(
                Task(
                    task_id=subtask_id,
                    task_type=step.subtask_type,
                    name=f"{parent.name or parent.task_type}:{step.subtask_type}",
                    description=step.description,
                    origin=step.origin,
                    destination=step.destination,
                    payload_weight=parent.payload_weight,
                    priority=parent.priority,
                    deadline=parent.deadline,
                    estimated_distance_km=step.estimated_distance_km,
                    required_capabilities=list(step.required_capabilities),
                    dependencies=step.dependencies,
                    status=TaskStatus.CREATED,
                    parent_task_id=parent.task_id,
                    is_parent=False,
                    subtask_type=step.subtask_type,
                    metadata={
                        **dict(parent.metadata),
                        "decomposition_rule": "intelligent_planner",
                        "step_index": index,
                        "step_count": len(plan.subtasks),
                    },
                )
            )
            
        parent.subtask_ids = [subtask.task_id for subtask in subtasks]
        parent.status = TaskStatus.ANNOUNCED
        parent.negotiation_status = NegotiationStatus.NOT_STARTED

        with self._lock:
            self._tasks[parent.task_id] = parent
            for subtask in subtasks:
                self._tasks[subtask.task_id] = subtask
        audit_log.record("mission.created", f"Created cooperative mission {parent.task_id}", task_id=parent.task_id, details={"subtask_count": len(subtasks), "plan_id": plan.plan_id})

        logger.info(
            "Parent task %s planned into %s subtasks: %s",
            parent.task_id,
            len(subtasks),
            parent.subtask_ids,
        )

        for subtask in subtasks:
            self._announce_and_allocate(subtask, announcement_event=EventType.SUBTASK_ANNOUNCEMENT)

        self._refresh_parent_status(parent.task_id)
        with self._lock:
            return copy.deepcopy(self._tasks[parent.task_id])

    def _create_cooperative_task(self, request: TaskCreate) -> Task:
        """Decompose into subtasks; each reuses Phase 4B decentralized negotiation."""
        payload = request.model_dump(exclude={"cooperative"})
        if payload.get("task_type") == "delivery":
            payload["task_type"] = "cooperative_delivery"
        metadata = dict(payload.get("metadata") or {})
        metadata["cooperative"] = True
        payload["metadata"] = metadata
        parent = Task(**payload, is_parent=True)
        subtasks = decompose_task(parent, request)
        parent.subtask_ids = [subtask.task_id for subtask in subtasks]
        parent.status = TaskStatus.ANNOUNCED
        parent.negotiation_status = NegotiationStatus.NOT_STARTED

        with self._lock:
            self._tasks[parent.task_id] = parent
            for subtask in subtasks:
                self._tasks[subtask.task_id] = subtask
        audit_log.record("mission.created", f"Created cooperative mission {parent.task_id}", task_id=parent.task_id, details={"subtask_count": len(subtasks)})

        logger.info(
            "Parent task %s decomposed into %s subtasks: %s",
            parent.task_id,
            len(subtasks),
            parent.subtask_ids,
        )

        for subtask in subtasks:
            self._announce_and_allocate(subtask, announcement_event=EventType.SUBTASK_ANNOUNCEMENT)

        self._refresh_parent_status(parent.task_id)
        with self._lock:
            return copy.deepcopy(self._tasks[parent.task_id])

    def _announce_and_allocate(
        self,
        task: Task,
        announcement_event: EventType = EventType.TASK_ANNOUNCEMENT,
        excluded_agent_ids: Optional[Set[str]] = None,
    ) -> None:
        with self._lock:
            task.proposals = []
            task.rejections = []
            task.negotiation_responses = []
            task.assigned_agent_id = None
            task.status = TaskStatus.ANNOUNCED
            task.negotiation_status = NegotiationStatus.COLLECTING_PROPOSALS
            self._negotiation_responses.pop(task.task_id, None)
            self._negotiation_accepts.pop(task.task_id, None)
            if excluded_agent_ids:
                self._handoff_excluded[task.task_id] = set(excluded_agent_ids)
            else:
                self._handoff_excluded.pop(task.task_id, None)

        announcement = TaskAnnouncementPayload(task=task)
        topic = "logistics/broadcast/tasks"
        if announcement_event == EventType.SUBTASK_ANNOUNCEMENT:
            topic = "logistics/broadcast/subtasks"
        if not self._publish(announcement_event, announcement.model_dump(), topic):
            with self._lock:
                task.status = TaskStatus.FAILED
            logger.error("Could not publish %s for %s", announcement_event.value, task.task_id)
            return
        # Also mirror on the classic broadcast topic so existing agent subscriptions see it.
        if announcement_event == EventType.SUBTASK_ANNOUNCEMENT:
            self._publish(EventType.SUBTASK_ANNOUNCEMENT, announcement.model_dump(), "logistics/broadcast/tasks")

        logger.info("%s %s announced over MQTT", announcement_event.value, task.task_id)

        deadline = time.monotonic() + self.proposal_window_seconds
        with self._responses:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._responses.wait(remaining)
            self._negotiate(task, assignment_event=(
                EventType.SUBTASK_ASSIGNMENT
                if task.is_subtask
                else EventType.TASK_ASSIGNMENT
            ))

    def list_tasks(self) -> List[Task]:
        with self._lock:
            return copy.deepcopy(list(self._tasks.values()))

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._lock:
            task = self._tasks.get(task_id)
            return copy.deepcopy(task) if task else None

    def get_subtasks(self, parent_task_id: str) -> List[Task]:
        with self._lock:
            parent = self._tasks.get(parent_task_id)
            if not parent:
                return []
            return copy.deepcopy(
                [self._tasks[sid] for sid in parent.subtask_ids if sid in self._tasks]
            )

    def _negotiate(
        self,
        task: Task,
        assignment_event: EventType = EventType.TASK_ASSIGNMENT,
    ) -> None:
        excluded = self._handoff_excluded.get(task.task_id, set())
        safety_rejected = []
        eligible_proposals = []
        for proposal in task.proposals:
            reason = self.safety_validator.rejection_reason(task, proposal, excluded)
            if reason is None:
                eligible_proposals.append(proposal)
            else:
                safety_rejected.append(
                    TaskRejectPayload(
                        task_id=task.task_id,
                        agent_id=proposal.agent_id,
                        reason=f"SAFETY_REVALIDATION:{reason}",
                    )
                )
                logger.info(
                    "Safety revalidation dropped proposal from %s for %s: %s",
                    proposal.agent_id,
                    task.task_id,
                    reason,
                )
        # Record safety-rejected proposals in task.rejections so they are visible via API.
        for rej in safety_rejected:
            if all(item.agent_id != rej.agent_id for item in task.rejections):
                task.rejections.append(rej)
        # Keep task.proposals intact (all received proposals) for observability;
        # negotiation proceeds only with the safety-eligible subset.
        if not eligible_proposals:
            task.negotiation_status = NegotiationStatus.NO_AGREEMENT
            return

        task.status = TaskStatus.NEGOTIATING
        task.negotiation_status = NegotiationStatus.EVALUATING
        request = NegotiationRequestPayload(
            task_id=task.task_id,
            task=task,
            proposals=eligible_proposals,
        )
        if not self._publish(
            EventType.NEGOTIATION_REQUEST,
            request.model_dump(),
            f"logistics/broadcast/negotiation/requests/{task.task_id}",
        ):
            task.negotiation_status = NegotiationStatus.NO_AGREEMENT
            return

        expected_agent_ids = {proposal.agent_id for proposal in eligible_proposals}
        deadline = time.monotonic() + self.negotiation_window_seconds
        with self._responses:
            while True:
                responses = self._negotiation_responses.get(task.task_id, {})
                accepts = self._negotiation_accepts.get(task.task_id, set())
                if expected_agent_ids.issubset(responses) and accepts:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._responses.wait(remaining)
            responses = self._negotiation_responses.get(task.task_id, {})
            accepts = self._negotiation_accepts.get(task.task_id, set())

        response_set = [responses[agent_id] for agent_id in expected_agent_ids if agent_id in responses]
        selected_agent_ids = {response.selected_agent_id for response in response_set}
        expected_proposal_ids = sorted(expected_agent_ids)
        unanimous = (
            len(response_set) == len(expected_agent_ids)
            and len(selected_agent_ids) == 1
            and all(response.compared_agent_ids == expected_proposal_ids for response in response_set)
        )
        if not unanimous:
            task.negotiation_status = NegotiationStatus.NO_AGREEMENT
            logger.info("Task %s negotiation ended without unanimous agent agreement", task.task_id)
            return

        selected_agent_id = next(iter(selected_agent_ids))
        selected_proposal = next((item for item in eligible_proposals if item.agent_id == selected_agent_id), None)
        winner_response = responses.get(selected_agent_id)
        if (
            selected_proposal is None
            or winner_response is None
            or not winner_response.accepted
            or selected_agent_id not in accepts
            or self.safety_validator.rejection_reason(task, selected_proposal, excluded) is not None
        ):
            task.negotiation_status = NegotiationStatus.NO_AGREEMENT
            logger.info("Task %s negotiation failed final safety/agreement validation", task.task_id)
            return

        task.negotiation_responses = response_set
        task.negotiation_status = NegotiationStatus.AGREED
        agreement = NegotiationAgreementPayload(
            task_id=task.task_id,
            selected_agent_id=selected_agent_id,
            agreed_agent_ids=sorted(response.agent_id for response in response_set),
            utility=selected_proposal.utility,
        )
        if not self._publish(
            EventType.NEGOTIATION_ACCEPT,
            agreement.model_dump(),
            f"logistics/broadcast/negotiation/agreements/{task.task_id}",
        ):
            task.negotiation_status = NegotiationStatus.NO_AGREEMENT
            task.status = TaskStatus.PROPOSED
            return

        assignment_task = task.model_copy(deep=True)
        assignment_task.status = TaskStatus.ASSIGNED
        assignment_task.assigned_agent_id = selected_agent_id
        assignment = TaskAssignmentPayload(task=assignment_task, assigned_agent_id=selected_agent_id)
        task.status = TaskStatus.PENDING
        task.assigned_agent_id = None
        self._pending_assignments[task.task_id] = selected_agent_id
        logger.info("Task %s unanimously negotiated to %s", task.task_id, selected_agent_id)

        published = self._publish(
            EventType.TASK_ASSIGNMENT,
            assignment.model_dump(),
            f"logistics/agents/{selected_agent_id}/events",
        )
        if assignment_event == EventType.SUBTASK_ASSIGNMENT:
            self._publish(
                EventType.SUBTASK_ASSIGNMENT,
                assignment.model_dump(),
                f"logistics/agents/{selected_agent_id}/events",
            )
            self._publish(
                EventType.SUBTASK_ASSIGNMENT,
                assignment.model_dump(),
                f"logistics/broadcast/subtasks/{task.task_id}",
            )
        if not published:
            task.status = TaskStatus.PROPOSED
            task.assigned_agent_id = None
            task.negotiation_status = NegotiationStatus.NO_AGREEMENT
            self._pending_assignments.pop(task.task_id, None)
        else:
            assignment_deadline = time.monotonic() + 2.0
            with self._responses:
                while self._pending_assignments.get(task.task_id) == selected_agent_id:
                    remaining = assignment_deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._responses.wait(remaining)
            if self._pending_assignments.get(task.task_id) == selected_agent_id:
                self._pending_assignments.pop(task.task_id, None)
                task.status = TaskStatus.PROPOSED
                task.assigned_agent_id = None
                task.negotiation_status = NegotiationStatus.NO_AGREEMENT
                if task.handoff_state in (HandoffState.REQUESTED, HandoffState.NEGOTIATING):
                    task.handoff_state = HandoffState.REJECTED
                logger.warning("Agent %s did not acknowledge assignment for %s", selected_agent_id, task.task_id)
            elif task.handoff_state in (HandoffState.REQUESTED, HandoffState.NEGOTIATING):
                task.handoff_state = HandoffState.REPLACED
                decision = TaskHandoffDecisionPayload(
                    task_id=task.task_id,
                    parent_task_id=task.parent_task_id,
                    from_agent_id=task.handoff_from_agent_id or "",
                    to_agent_id=selected_agent_id,
                    accepted=True,
                    reason="replacement_assignment_acknowledged_via_decentralized_negotiation",
                )
                self._publish(
                    EventType.TASK_HANDOFF_ACCEPT,
                    decision.model_dump(),
                    f"logistics/broadcast/handoff/{task.task_id}",
                )

        if task.parent_task_id:
            self._refresh_parent_status(task.parent_task_id)

    def _refresh_parent_status(self, parent_task_id: str) -> None:
        with self._lock:
            parent = self._tasks.get(parent_task_id)
            if not parent or not parent.is_parent:
                return
            children = [self._tasks[sid] for sid in parent.subtask_ids if sid in self._tasks]
            if not children:
                return

            statuses = {child.status for child in children}
            if all(child.status == TaskStatus.COMPLETED for child in children):
                newly_completed = parent.status != TaskStatus.COMPLETED
                parent.status = TaskStatus.COMPLETED
                parent.assigned_agent_id = None
                if newly_completed:
                    audit_log.record(
                        "mission.completed",
                        f"Cooperative mission {parent_task_id} completed",
                        task_id=parent_task_id,
                    )
            elif any(child.status == TaskStatus.FAILED for child in children):
                parent.status = TaskStatus.FAILED
            elif any(
                child.status in (
                    TaskStatus.ASSIGNED,
                    TaskStatus.IN_PROGRESS,
                    TaskStatus.NEGOTIATING,
                    TaskStatus.PROPOSED,
                    TaskStatus.ANNOUNCED,
                )
                for child in children
            ):
                parent.status = TaskStatus.IN_PROGRESS
            elif TaskStatus.CANCELLED in statuses and len(statuses) == 1:
                parent.status = TaskStatus.CANCELLED
            logger.info(
                "Parent %s status -> %s (subtasks=%s)",
                parent.task_id,
                parent.status.value,
                {c.task_id: c.status.value for c in children},
            )

    def _begin_handoff(self, request: TaskHandoffRequestPayload) -> None:
        with self._lock:
            task = self._tasks.get(request.task_id)
            if not task:
                logger.warning("Handoff requested for unknown task %s", request.task_id)
                return
            if task.assigned_agent_id != request.from_agent_id:
                logger.warning(
                    "Ignoring handoff for %s from %s (assigned=%s)",
                    request.task_id,
                    request.from_agent_id,
                    task.assigned_agent_id,
                )
                return
            if task.status not in (TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS, TaskStatus.FAILED):
                logger.warning("Ignoring handoff for %s in status %s", request.task_id, task.status)
                return

            task.handoff_state = HandoffState.REQUESTED
            task.handoff_from_agent_id = request.from_agent_id
            task.handoff_reason = request.reason
            task.status = TaskStatus.PENDING
            previous_agent = task.assigned_agent_id
            task.assigned_agent_id = None
            logger.info(
                "Handoff requested for %s by %s reason=%s",
                task.task_id,
                previous_agent,
                request.reason,
            )

        def _renegotiate() -> None:
            try:
                with self._lock:
                    task_ref = self._tasks.get(request.task_id)
                    if not task_ref:
                        return
                    task_ref.handoff_state = HandoffState.NEGOTIATING
                    excluded = {request.from_agent_id}
                self._announce_and_allocate(
                    task_ref,
                    announcement_event=(
                        EventType.SUBTASK_ANNOUNCEMENT
                        if task_ref.is_subtask
                        else EventType.TASK_ANNOUNCEMENT
                    ),
                    excluded_agent_ids=excluded,
                )
                with self._lock:
                    latest = self._tasks.get(request.task_id)
                    if latest is None:
                        return
                    if latest.assigned_agent_id is None:
                        latest.handoff_state = HandoffState.REJECTED
                        decision = TaskHandoffDecisionPayload(
                            task_id=latest.task_id,
                            parent_task_id=latest.parent_task_id,
                            from_agent_id=request.from_agent_id,
                            to_agent_id=None,
                            accepted=False,
                            reason="no_eligible_replacement",
                        )
                        self._publish(
                            EventType.TASK_HANDOFF_REJECT,
                            decision.model_dump(),
                            f"logistics/broadcast/handoff/{latest.task_id}",
                        )
                    if latest.parent_task_id:
                        parent_id = latest.parent_task_id
                    else:
                        parent_id = None
                if parent_id:
                    self._refresh_parent_status(parent_id)
            except Exception:
                logger.exception("Handoff renegotiation failed for %s", request.task_id)

        threading.Thread(
            target=_renegotiate,
            name=f"Handoff-{request.task_id}",
            daemon=True,
        ).start()

    def _publish(self, event_type: EventType, event_data: dict, topic: str) -> bool:
        message = MQTTMessagePayload(
            event=AgentEvent(
                event_type=event_type,
                source_agent_id="platform-coordinator",
                payload=event_data,
            ),
            sender_identity=AgentIdentity(
                agent_id="platform-coordinator",
                agent_type="platform",
            ),
            sender_state=AgentState(status=AgentStatus.IDLE),
        )
        result = self._client.publish(topic, message.to_json(), qos=1)
        if event_type in (
            EventType.TASK_ANNOUNCEMENT,
            EventType.TASK_ASSIGNMENT,
            EventType.TASK_PROPOSAL,
            EventType.TASK_REJECT,
            EventType.TASK_STATUS_UPDATE,
            EventType.NEGOTIATION_REQUEST,
            EventType.NEGOTIATION_RESPONSE,
            EventType.NEGOTIATION_ACCEPT,
            EventType.NEGOTIATION_REJECT,
            EventType.SUBTASK_ANNOUNCEMENT,
            EventType.SUBTASK_ASSIGNMENT,
            EventType.SUBTASK_STATUS_UPDATE,
            EventType.SUBTASK_COMPLETED,
            EventType.TASK_HANDOFF_REQUEST,
            EventType.TASK_HANDOFF_ACCEPT,
            EventType.TASK_HANDOFF_REJECT,
        ):
            logger.info("Published %s to %s (rc=%s)", event_type.value, topic, result.rc)
        succeeded = result.rc == mqtt.MQTT_ERR_SUCCESS
        audit_types = {
            EventType.TASK_ANNOUNCEMENT: "mission.announced",
            EventType.SUBTASK_ANNOUNCEMENT: "mission.subtask_announced",
            EventType.NEGOTIATION_REQUEST: "negotiation.started",
            EventType.NEGOTIATION_ACCEPT: "negotiation.agreed",
            EventType.TASK_ASSIGNMENT: "assignment.created",
            EventType.SUBTASK_ASSIGNMENT: "assignment.created",
            EventType.TASK_HANDOFF_REQUEST: "handoff.requested",
            EventType.TASK_HANDOFF_ACCEPT: "handoff.accepted",
            EventType.TASK_HANDOFF_REJECT: "handoff.rejected",
        }
        audit_type = audit_types.get(event_type)
        if audit_type:
            task_payload = event_data.get("task") or {}
            audit_log.record(
                audit_type,
                f"{event_type.value.replace('_', ' ').title()} {'published' if succeeded else 'publish failed'}",
                task_id=event_data.get("task_id") or task_payload.get("task_id"),
                agent_id=event_data.get("assigned_agent_id") or event_data.get("selected_agent_id") or event_data.get("to_agent_id"),
                result="published" if succeeded else "publish_failed",
            )
        return succeeded

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        code = reason_code.value if hasattr(reason_code, "value") else reason_code
        if code == 0:
            client.subscribe("logistics/tasks/responses", qos=1)
            client.subscribe("logistics/agents/+/responses", qos=1)
            client.subscribe("logistics/agents/+/proposals/#", qos=1)
            client.subscribe("logistics/agents/+/negotiation/responses/#", qos=1)
            client.subscribe("logistics/agents/+/handoff/#", qos=1)
            client.subscribe("logistics/broadcast/negotiation/proposals/#", qos=1)
            client.subscribe("logistics/broadcast/negotiation/responses/#", qos=1)
            client.subscribe("logistics/broadcast/handoff/#", qos=1)
            client.subscribe("logistics/broadcast/subtasks/#", qos=1)

    def _on_message(self, client, userdata, message) -> None:
        try:
            envelope = MQTTMessagePayload.from_dict(json.loads(message.payload.decode("utf-8")))
            event = envelope.event
            if event.source_agent_id == "platform-coordinator":
                return
            topic_parts = message.topic.split("/")
            scoped_agent_id = topic_parts[2] if len(topic_parts) >= 4 and topic_parts[:2] == ["logistics", "agents"] else None
            if scoped_agent_id and scoped_agent_id != envelope.sender_identity.agent_id:
                audit_log.record(
                    "security.agent_topic_identity_mismatch",
                    "Rejected MQTT event because topic identity did not match sender identity",
                    actor=envelope.sender_identity.agent_id,
                    agent_id=scoped_agent_id,
                    result="denied",
                )
                return
            if event.event_type == EventType.TASK_PROPOSAL:
                response = TaskProposalPayload.model_validate(event.payload)
                if response.agent_id != envelope.sender_identity.agent_id:
                    return
                with self._responses:
                    task = self._tasks.get(response.task_id)
                    excluded = self._handoff_excluded.get(response.task_id, set())
                    if response.agent_id in excluded:
                        logger.info(
                            "Ignoring proposal from excluded handoff requester %s for %s",
                            response.agent_id,
                            response.task_id,
                        )
                        return
                    if task and all(item.agent_id != response.agent_id for item in task.proposals):
                        task.proposals.append(response)
                        audit_log.record(
                            "negotiation.proposal",
                            f"Agent proposal received for {response.task_id}",
                            actor=response.agent_id,
                            agent_id=response.agent_id,
                            task_id=response.task_id,
                            details={"utility": response.utility, "capability_match": response.capability_match},
                        )
                        if task.status == TaskStatus.ANNOUNCED:
                            task.status = TaskStatus.PROPOSED
                        logger.info("Received TASK_PROPOSAL for %s from %s", response.task_id, response.agent_id)
                        self._responses.notify_all()
            elif event.event_type == EventType.TASK_REJECT:
                response = TaskRejectPayload.model_validate(event.payload)
                if response.agent_id != envelope.sender_identity.agent_id:
                    return
                with self._lock:
                    task = self._tasks.get(response.task_id)
                    if task and all(item.agent_id != response.agent_id for item in task.rejections):
                        task.rejections.append(response)
                        audit_log.record(
                            "negotiation.rejection",
                            f"Agent rejected {response.task_id}: {response.reason}",
                            actor=response.agent_id,
                            agent_id=response.agent_id,
                            task_id=response.task_id,
                            result="rejected",
                        )
                        logger.info(
                            "Received TASK_REJECT for %s from %s reason=%s",
                            response.task_id,
                            response.agent_id,
                            response.reason,
                        )
            elif event.event_type == EventType.NEGOTIATION_RESPONSE:
                response = NegotiationResponsePayload.model_validate(event.payload)
                if response.agent_id != envelope.sender_identity.agent_id:
                    return
                with self._responses:
                    task = self._tasks.get(response.task_id)
                    if task and response.agent_id in {item.agent_id for item in task.proposals}:
                        self._negotiation_responses.setdefault(response.task_id, {})[response.agent_id] = response
                        task.negotiation_responses = list(self._negotiation_responses[response.task_id].values())
                        audit_log.record(
                            "negotiation.response",
                            f"Agent ranked {response.selected_agent_id} for {response.task_id}",
                            actor=response.agent_id,
                            agent_id=response.agent_id,
                            task_id=response.task_id,
                            details={"selected_agent_id": response.selected_agent_id, "accepted": response.accepted},
                        )
                        logger.info(
                            "Received negotiation comparison for %s from %s: selected=%s",
                            response.task_id,
                            response.agent_id,
                            response.selected_agent_id,
                        )
                        self._responses.notify_all()
            elif event.event_type == EventType.NEGOTIATION_ACCEPT:
                response = NegotiationResponsePayload.model_validate(event.payload)
                if response.agent_id != envelope.sender_identity.agent_id:
                    return
                with self._responses:
                    task = self._tasks.get(response.task_id)
                    if task and response.agent_id in {item.agent_id for item in task.proposals} and response.accepted:
                        self._negotiation_accepts.setdefault(response.task_id, set()).add(response.agent_id)
                        logger.info("Received NEGOTIATION_ACCEPT for %s from %s", response.task_id, response.agent_id)
                        self._responses.notify_all()
            elif event.event_type == EventType.NEGOTIATION_REJECT:
                response = NegotiationResponsePayload.model_validate(event.payload)
                if response.agent_id != envelope.sender_identity.agent_id:
                    return
                logger.info(
                    "Received NEGOTIATION_REJECT for %s from %s: %s",
                    response.task_id,
                    response.agent_id,
                    response.reason,
                )
            elif event.event_type in (EventType.TASK_STATUS_UPDATE, EventType.SUBTASK_STATUS_UPDATE):
                if event.event_type == EventType.SUBTASK_STATUS_UPDATE:
                    update = SubtaskStatusUpdatePayload.model_validate(event.payload)
                    task_id = update.subtask_id
                    agent_id = update.agent_id
                    new_status = update.status
                else:
                    update = TaskStatusUpdatePayload.model_validate(event.payload)
                    task_id = update.task_id
                    agent_id = update.agent_id
                    new_status = update.status
                if agent_id != envelope.sender_identity.agent_id:
                    return
                with self._lock:
                    task = self._tasks.get(task_id)
                    pending_agent_id = self._pending_assignments.get(task_id)
                    if task and pending_agent_id == agent_id and new_status == TaskStatus.ASSIGNED:
                        task.assigned_agent_id = agent_id
                        task.status = TaskStatus.ASSIGNED
                        self._pending_assignments.pop(task_id, None)
                        parent_id = task.parent_task_id
                        audit_log.record(
                            "assignment.confirmed",
                            f"Agent {agent_id} acknowledged assignment for {task_id}",
                            actor=agent_id,
                            agent_id=agent_id,
                            task_id=task.parent_task_id or task_id,
                            details={"assigned_task_id": task_id},
                        )
                        self._responses.notify_all()
                    elif task and task.assigned_agent_id == agent_id:
                        task.status = new_status
                        parent_id = task.parent_task_id
                    else:
                        parent_id = None
                if parent_id:
                    self._refresh_parent_status(parent_id)
                if new_status == TaskStatus.FAILED:
                    audit_log.record("mission.failed", f"Task {task_id} reported FAILED", actor=agent_id, agent_id=agent_id, task_id=task_id, result="failed")
            elif event.event_type == EventType.SUBTASK_COMPLETED:
                completed = SubtaskCompletedPayload.model_validate(event.payload)
                if completed.agent_id != envelope.sender_identity.agent_id:
                    return
                with self._lock:
                    task = self._tasks.get(completed.subtask_id)
                    if task and task.assigned_agent_id == completed.agent_id:
                        task.status = TaskStatus.COMPLETED
                        parent_id = task.parent_task_id
                    else:
                        parent_id = None
                if parent_id:
                    self._refresh_parent_status(parent_id)
                audit_log.record("mission.subtask_completed", f"Subtask {completed.subtask_id} completed", actor=completed.agent_id, agent_id=completed.agent_id, task_id=completed.parent_task_id)
            elif event.event_type == EventType.TASK_HANDOFF_REQUEST:
                handoff = TaskHandoffRequestPayload.model_validate(event.payload)
                if handoff.from_agent_id != envelope.sender_identity.agent_id:
                    return
                self._begin_handoff(handoff)
        except Exception as exc:
            logger.debug("Ignored task response on %s: %s", message.topic, exc)


task_coordination_service = TaskCoordinationService()
