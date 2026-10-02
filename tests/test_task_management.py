import os
import sys
import time
import logging

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from agents.runtime import AgentRuntime
from app.main import app
from app.services.platform_registry import platform_registry_service
from app.services.task_coordination import task_coordination_service
from protocols.messages import (
    AgentEvent,
    AgentIdentity,
    AgentRegistrationPayload,
    AgentState,
    AgentStatus,
    EventType,
    MQTTMessagePayload,
    NegotiationRequestPayload,
    NegotiationStatus,
    Task,
    TaskAssignmentPayload,
    TaskCreate,
    TaskProposalPayload,
    TaskStatus,
)

def test_task_schema_accepts_required_fields_and_legacy_weight_name():
    task = TaskCreate(
        origin="Depot A",
        destination="Dock B",
        payload_weight_kg=2.5,
        required_capabilities=["ground_transport"],
    )
    persisted = Task(**task.model_dump())

    assert persisted.task_id.startswith("TASK-")
    assert persisted.payload_weight == 2.5
    assert persisted.payload_weight_kg == 2.5
    assert persisted.status == TaskStatus.CREATED
    assert persisted.created_at is not None


@pytest.mark.parametrize(
    ("runtime_kwargs", "task_kwargs", "expected_reason"),
    [
        ({"capabilities": ["ground_transport"]}, {"required_capabilities": ["aerial_delivery"]}, "MISSING_CAPABILITIES:aerial_delivery"),
        ({"capabilities": ["ground_transport"], "payload_capacity_kg": 5}, {"payload_weight": 20}, "PAYLOAD_CAPACITY_EXCEEDED"),
    ],
)
def test_agent_rejects_ineligible_task(runtime_kwargs, task_kwargs, expected_reason):
    runtime = AgentRuntime(agent_id="EVALUATOR", agent_type="test", **runtime_kwargs)
    task = Task(origin="A", destination="B", **task_kwargs)

    assert runtime.evaluate_task(task) == expected_reason


def test_agent_rejects_unavailable_or_low_battery_task():
    runtime = AgentRuntime(agent_id="RESOURCE-CHECK", agent_type="test")
    task = Task(origin="A", destination="B")

    runtime.state.update_battery(10)
    assert runtime.evaluate_task(task) == "INSUFFICIENT_BATTERY"

    runtime.state.update_battery(100)
    runtime.state.set_status(AgentStatus.BUSY)
    assert runtime.evaluate_task(task) == "AGENT_UNAVAILABLE"


def test_agent_utility_is_deterministic_and_explains_metrics():
    runtime = AgentRuntime(
        agent_id="SCORING-AGENT",
        agent_type="vehicle",
        capabilities=["ground_transport"],
        payload_capacity_kg=100,
    )
    runtime.state.update_battery(90)
    task = Task(
        task_id="TASK-SCORING",
        origin="Depot A",
        destination="Dock B",
        payload_weight=20,
        priority=5,
        estimated_distance_km=20,
        required_capabilities=["ground_transport"],
    )

    first = runtime.calculate_task_proposal(task)
    second = runtime.calculate_task_proposal(task)

    assert first.utility == second.utility
    assert first.estimated_cost == second.estimated_cost
    assert first.capability_match
    assert first.battery_score == pytest.approx(0.9)
    assert first.capacity_score == pytest.approx(0.8)
    assert first.distance_score == pytest.approx(1 / 3)
    assert first.priority_score == 1.0
    assert first.utility > 0.0
    assert first.estimated_cost == pytest.approx(25.5)
    assert "battery=90%" in first.reason
    assert "payload_headroom=80.0kg" in first.reason


def test_negotiation_cannot_choose_ineligible_high_utility_proposal(monkeypatch):
    runtime = AgentRuntime(
        agent_id="SAFE-AGENT",
        agent_type="vehicle",
        capabilities=["ground_transport"],
        payload_capacity_kg=100,
    )
    task = Task(
        task_id="TASK-SAFE-NEGOTIATION",
        origin="A",
        destination="B",
        payload_weight=20,
        required_capabilities=["ground_transport"],
    )
    own_proposal = runtime.calculate_task_proposal(task)
    ineligible_proposal = TaskProposalPayload(
        task_id=task.task_id,
        agent_id="INELIGIBLE-DRONE",
        capabilities=["aerial_delivery"],
        payload_capacity_kg=100,
        battery_pct=100,
        available=True,
        capability_match=False,
        utility=100.0,
        estimated_cost=0.0,
    )
    sent = []
    monkeypatch.setattr(runtime, "send_event", lambda event_type, *args, **kwargs: sent.append(event_type) or True)
    envelope = MQTTMessagePayload(
        event=AgentEvent(
            event_type=EventType.NEGOTIATION_REQUEST,
            source_agent_id="platform-coordinator",
            payload=NegotiationRequestPayload(
                task_id=task.task_id,
                task=task,
                proposals=[own_proposal, ineligible_proposal],
            ).model_dump(),
        ),
        sender_identity=AgentIdentity(agent_id="platform-coordinator", agent_type="platform"),
        sender_state=AgentState(status=AgentStatus.IDLE),
    )

    runtime._handle_negotiation_request(envelope)

    assert EventType.NEGOTIATION_RESPONSE in sent
    assert EventType.NEGOTIATION_ACCEPT in sent
    assert EventType.NEGOTIATION_REJECT not in sent


def test_agent_revalidates_availability_when_assignment_arrives(monkeypatch):
    runtime = AgentRuntime(
        agent_id="ASSIGNMENT-RESOURCE-CHECK",
        agent_type="vehicle",
        capabilities=["ground_transport"],
    )
    task = Task(
        task_id="TASK-ASSIGNMENT-CHECK",
        origin="A",
        destination="B",
        required_capabilities=["ground_transport"],
    )
    runtime.state.set_status(AgentStatus.BUSY)
    sent = []
    monkeypatch.setattr(runtime, "send_event", lambda *args, **kwargs: sent.append(args[0]) or True)
    envelope = MQTTMessagePayload(
        event=AgentEvent(
            event_type=EventType.TASK_ASSIGNMENT,
            source_agent_id="platform-coordinator",
            payload=TaskAssignmentPayload(task=task, assigned_agent_id=runtime.agent_id).model_dump(),
        ),
        sender_identity=AgentIdentity(agent_id="platform-coordinator", agent_type="platform"),
        sender_state=AgentState(status=AgentStatus.IDLE),
    )

    runtime._handle_task_assignment(envelope)

    assert runtime.task_manager.current_task is None
    assert EventType.TASK_REJECT in sent


def test_task_api_schema_validation_and_unknown_retrieval():
    with TestClient(app) as client:
        invalid = client.post(
            "/api/v1/tasks",
            json={"origin": "A", "destination": "B", "payload_weight": -1},
        )
        missing = client.get("/api/v1/tasks/DOES-NOT-EXIST")

    assert invalid.status_code == 422
    assert missing.status_code == 404


def test_handle_task_announcement_pydantic_compat(monkeypatch):
    """Regression: _handle_task_announcement must parse via _parse_model (v1/v2 compat)."""
    from agents.runtime import _parse_model
    from protocols.messages import TaskAnnouncementPayload, Task

    task = Task(
        task_id="TASK-PARSETEST",
        origin="A",
        destination="B",
        required_capabilities=["ground_transport"],
    )
    payload_dict = TaskAnnouncementPayload(task=task).model_dump() if hasattr(TaskAnnouncementPayload, "model_dump") else TaskAnnouncementPayload(task=task).dict()

    # _parse_model must succeed regardless of pydantic version
    result = _parse_model(TaskAnnouncementPayload, payload_dict)
    assert result.task.task_id == "TASK-PARSETEST"

    # simulate what the handler receives: plain dict (no model_validate on class)
    runtime = AgentRuntime(
        agent_id="COMPAT-AGENT",
        agent_type="vehicle",
        capabilities=["ground_transport"],
        payload_capacity_kg=100,
    )
    sent = []
    monkeypatch.setattr(runtime, "send_event", lambda *args, **kwargs: sent.append(args[0]) or True)

    envelope = MQTTMessagePayload(
        event=AgentEvent(
            event_type=EventType.TASK_ANNOUNCEMENT,
            source_agent_id="platform-coordinator",
            payload=payload_dict,
        ),
        sender_identity=AgentIdentity(agent_id="platform-coordinator", agent_type="platform"),
        sender_state=AgentState(status=AgentStatus.IDLE),
    )

    runtime._handle_task_announcement(envelope)
    # Should have sent a proposal (not silently swallowed by an AttributeError)
    assert EventType.TASK_PROPOSAL in sent


def test_handle_subtask_announcement_pydantic_compat(monkeypatch):
    """Regression: SUBTASK_ANNOUNCEMENT path uses the same handler — must also parse correctly."""
    from protocols.messages import TaskAnnouncementPayload, Task

    task = Task(
        task_id="TASK-PARENT-01-ST1",
        origin="A",
        destination="B",
        required_capabilities=["ground_transport"],
        parent_task_id="TASK-PARENT-01",
        subtask_type="transport",
    )
    payload_dict = (
        TaskAnnouncementPayload(task=task).model_dump()
        if hasattr(TaskAnnouncementPayload, "model_dump")
        else TaskAnnouncementPayload(task=task).dict()
    )

    runtime = AgentRuntime(
        agent_id="COMPAT-AGENT-SUB",
        agent_type="vehicle",
        capabilities=["ground_transport"],
        payload_capacity_kg=100,
    )
    sent = []
    monkeypatch.setattr(runtime, "send_event", lambda *args, **kwargs: sent.append(args[0]) or True)

    envelope = MQTTMessagePayload(
        event=AgentEvent(
            event_type=EventType.SUBTASK_ANNOUNCEMENT,
            source_agent_id="platform-coordinator",
            payload=payload_dict,
        ),
        sender_identity=AgentIdentity(agent_id="platform-coordinator", agent_type="platform"),
        sender_state=AgentState(status=AgentStatus.IDLE),
    )

    runtime._handle_task_announcement(envelope)
    assert EventType.TASK_PROPOSAL in sent


def test_real_mqtt_task_proposal_rejection_allocation_and_assignment(caplog):
    caplog.set_level(logging.INFO)
    agents = [
        AgentRuntime(
            agent_id="TASK-ALLOC-A",
            agent_type="vehicle",
            capabilities=["ground_transport"],
            payload_capacity_kg=100,
            heartbeat_interval_sec=0.5,
        ),
        AgentRuntime(
            agent_id="TASK-ALLOC-B",
            agent_type="vehicle",
            capabilities=["ground_transport"],
            payload_capacity_kg=100,
            heartbeat_interval_sec=0.5,
        ),
        AgentRuntime(
            agent_id="TASK-ALLOC-C",
            agent_type="drone",
            capabilities=["aerial_delivery"],
            payload_capacity_kg=5,
            heartbeat_interval_sec=0.5,
        ),
    ]
    started = []
    try:
        with TestClient(app) as client:
            task_coordination_service._tasks.clear()
            for agent in agents:
                assert agent.start()
                started.append(agent)
            for agent in agents:
                platform_registry_service.registry.register_agent(
                    AgentRegistrationPayload(
                        agent_id=agent.agent_id,
                        agent_type=agent.agent_type,
                        capabilities=agent.capability.capabilities,
                        payload_capacity_kg=agent.capability.payload_capacity_kg,
                        supported_operations=agent.capability.supported_operations,
                        status=agent.state.status,
                        initial_state=agent.state.to_model(),
                        metadata=agent.identity.metadata,
                    )
                )

            response = client.post(
                "/api/v1/tasks",
                json={
                    "task_type": "delivery",
                    "origin": "Depot A",
                    "destination": "Dock B",
                    "payload_weight": 20,
                    "priority": 2,
                    "estimated_distance_km": 10,
                    "required_capabilities": ["ground_transport"],
                },
            )
            assert response.status_code == 201, response.text
            created = response.json()
            task_id = created["task_id"]

            assert created["status"] == TaskStatus.ASSIGNED.value, {
                "proposals": created["proposals"],
                "rejections": created["rejections"],
            }
            assert created["payload_weight"] == 20
            assert created["assigned_agent_id"] == "TASK-ALLOC-A"
            assert created["negotiation_status"] == NegotiationStatus.AGREED.value
            # Use subset check: live demo agents on the shared broker may also propose;
            # what matters is that both test agents proposed and the right one won.
            proposal_agent_ids = {item["agent_id"] for item in created["proposals"]}
            assert {"TASK-ALLOC-A", "TASK-ALLOC-B"}.issubset(proposal_agent_ids)
            rejections = {item["agent_id"]: item["reason"] for item in created["rejections"]}
            assert rejections["TASK-ALLOC-C"] == "MISSING_CAPABILITIES:ground_transport"
            assert all(proposal["utility"] > 0 and proposal["estimated_cost"] >= 0 for proposal in created["proposals"])
            # Negotiation responses come from eligible proposers only (safety-rejected live
            # agents are excluded); check that both test agents participated.
            negotiation_agent_ids = {r["agent_id"] for r in created["negotiation_responses"]}
            assert {"TASK-ALLOC-A", "TASK-ALLOC-B"}.issubset(negotiation_agent_ids)
            assert {response["selected_agent_id"] for response in created["negotiation_responses"]} == {"TASK-ALLOC-A"}
            assert "[TASK-ALLOC-A] Received TASK_ANNOUNCEMENT" in caplog.text
            assert "[TASK-ALLOC-A] TASK_PROPOSAL" in caplog.text
            assert "[TASK-ALLOC-C] TASK_REJECT" in caplog.text
            assert "[TASK-ALLOC-A] Comparing proposals" in caplog.text
            assert "Received negotiation comparison" in caplog.text
            assert f"Task {task_id} unanimously negotiated to TASK-ALLOC-A" in caplog.text
            assert f"Published NEGOTIATION_REQUEST to logistics/broadcast/negotiation/requests/{task_id}" in caplog.text
            assert "Published TASK_ASSIGNMENT to logistics/agents/TASK-ALLOC-A/events" in caplog.text

            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if agents[0].task_manager.current_task and agents[0].task_manager.current_task.task_id == task_id:
                    break
                time.sleep(0.05)
            assert agents[0].task_manager.current_task.task_id == task_id
            assert agents[0].task_manager.current_task.status == TaskStatus.ASSIGNED
            assert f"[TASK-ALLOC-A] Received NEGOTIATION_ACCEPT for {task_id}" in caplog.text
            assert f"[TASK-ALLOC-A] Received TASK_ASSIGNMENT: {task_id}" in caplog.text
            assert f"[TASK-ALLOC-A] Task {task_id} status -> ASSIGNED" in caplog.text
            assert all(agent.task_manager.current_task is None for agent in agents[1:])

            listed = client.get("/api/v1/tasks")
            retrieved = client.get(f"/api/v1/tasks/{task_id}")
            assert listed.status_code == 200
            assert any(task["task_id"] == task_id for task in listed.json())
            assert retrieved.status_code == 200
            assert retrieved.json()["assigned_agent_id"] == "TASK-ALLOC-A"
    finally:
        for agent in reversed(started):
            agent.stop()


# ---------------------------------------------------------------------------
# Regression tests for cooperative subtask proposal persistence and negotiation
# ---------------------------------------------------------------------------

def test_subtask_proposal_is_persisted_and_not_destroyed_by_negotiate():
    """
    Regression: proposals received for a cooperative subtask must survive _negotiate().
    Previously _negotiate() replaced task.proposals with only the eligible subset,
    silently destroying all received proposals when any safety check failed.
    """
    import threading
    from app.services.task_coordination import TaskCoordinationService, ProposalSafetyValidator
    from protocols.messages import (
        NegotiationStatus, TaskProposalPayload, TaskRejectPayload,
    )

    svc = TaskCoordinationService.__new__(TaskCoordinationService)
    svc._lock = threading.RLock()
    svc._responses = threading.Condition(svc._lock)
    svc._tasks = {}
    svc._negotiation_responses = {}
    svc._negotiation_accepts = {}
    svc._handoff_excluded = {}
    svc._pending_assignments = {}
    svc.proposal_window_seconds = 0.1
    svc.negotiation_window_seconds = 0.1

    # Register an agent WITH capabilities in the platform registry
    platform_registry_service.registry.register_agent(AgentRegistrationPayload(
        agent_id="PERSIST-ROBOT",
        agent_type="warehouse_robot",
        capabilities=["bin_picking"],
        payload_capacity_kg=30,
        supported_operations=[],
        status=AgentStatus.IDLE,
        initial_state=AgentState(status=AgentStatus.IDLE, is_available=True, battery_pct=100),
    ))
    svc.safety_validator = ProposalSafetyValidator(platform_registry_service.registry)

    subtask = Task(
        task_id="TASK-PERSISTTEST-ST1",
        task_type="pickup",
        subtask_type="pickup",
        origin="Warehouse",
        destination="Staging",
        parent_task_id="TASK-PERSISTTEST",
        required_capabilities=["bin_picking"],
        payload_weight=2.0,
        status=TaskStatus.ANNOUNCED,
        negotiation_status=NegotiationStatus.COLLECTING_PROPOSALS,
    )
    svc._tasks["TASK-PERSISTTEST-ST1"] = subtask

    proposal = TaskProposalPayload(
        task_id="TASK-PERSISTTEST-ST1",
        agent_id="PERSIST-ROBOT",
        capabilities=["bin_picking"],
        payload_capacity_kg=30.0,
        battery_pct=100.0,
        available=True,
        capability_match=True,
        utility=0.75,
        estimated_cost=5.0,
    )
    subtask.proposals.append(proposal)
    assert len(subtask.proposals) == 1, "Proposal should be stored before _negotiate"

    # Run _negotiate — in the past this would destroy proposals if all were safety-rejected
    # We monkeypatch _publish to prevent real MQTT and force NO_AGREEMENT after proposal check
    published = []
    original_publish = svc.__class__._publish
    def fake_publish(self, event_type, data, topic):
        published.append(event_type)
        return True
    svc._publish = lambda *a, **kw: fake_publish(svc, *a, **kw)

    svc._negotiate(subtask)

    # The proposals list must NOT be empty after _negotiate, regardless of outcome
    assert len(subtask.proposals) >= 1, (
        f"task.proposals was destroyed by _negotiate. Got: {subtask.proposals}"
    )
    assert subtask.proposals[0].agent_id == "PERSIST-ROBOT"


def test_safety_validator_skips_registered_capability_mismatch_when_registry_caps_empty():
    """
    Regression: when an agent's registry entry has empty capabilities (e.g. backend
    restarted and capability advertisement hasn't arrived yet), the safety validator
    must NOT reject a proposal that carries capability_match=True.

    Previously the check `not set(required).issubset(agent.capabilities)` would fire
    with agent.capabilities=[] and return REGISTERED_CAPABILITY_MISMATCH, silently
    dropping every valid proposal and leaving the task stuck at NO_AGREEMENT.
    """
    import time
    from app.services.task_coordination import ProposalSafetyValidator
    from agents.core.registry import AgentRegistry
    from protocols.messages import AgentRegistryEntry, AgentState, AgentStatus

    registry = AgentRegistry(offline_timeout_seconds=30)
    # Register agent with EMPTY capabilities (simulates backend restart timing gap)
    registry.register_agent(AgentRegistrationPayload(
        agent_id="RESTART-ROBOT",
        agent_type="warehouse_robot",
        capabilities=[],           # empty — hasn't re-advertised yet
        payload_capacity_kg=30,
        supported_operations=[],
        status=AgentStatus.IDLE,
        initial_state=AgentState(status=AgentStatus.IDLE, is_available=True, battery_pct=100),
    ))

    validator = ProposalSafetyValidator(registry)
    task = Task(
        task_id="TASK-CAPTEST-ST1",
        required_capabilities=["bin_picking"],
        payload_weight=2.0,
        origin="A",
        destination="B",
    )
    proposal = TaskProposalPayload(
        task_id="TASK-CAPTEST-ST1",
        agent_id="RESTART-ROBOT",
        capabilities=["bin_picking"],  # agent self-attests correct capability
        payload_capacity_kg=30.0,
        battery_pct=100.0,
        available=True,
        capability_match=True,         # agent verified locally
        utility=0.75,
        estimated_cost=5.0,
    )

    reason = validator.rejection_reason(task, proposal)
    assert reason is None, (
        f"Should accept proposal when registry caps are empty (backend restart gap). "
        f"Got rejection: {reason}"
    )


def test_safety_validator_still_rejects_when_registry_caps_are_populated_and_wrong():
    """
    Safety regression: when registry DOES have capabilities and they don't match,
    REGISTERED_CAPABILITY_MISMATCH must still fire.
    """
    from app.services.task_coordination import ProposalSafetyValidator
    from agents.core.registry import AgentRegistry

    registry = AgentRegistry(offline_timeout_seconds=30)
    registry.register_agent(AgentRegistrationPayload(
        agent_id="WRONG-ROBOT",
        agent_type="warehouse_robot",
        capabilities=["barcode_scanning"],   # has caps, but wrong ones
        payload_capacity_kg=30,
        supported_operations=[],
        status=AgentStatus.IDLE,
        initial_state=AgentState(status=AgentStatus.IDLE, is_available=True, battery_pct=100),
    ))

    validator = ProposalSafetyValidator(registry)
    task = Task(
        task_id="TASK-WRONGCAP-ST1",
        required_capabilities=["bin_picking"],
        payload_weight=2.0,
        origin="A",
        destination="B",
    )
    proposal = TaskProposalPayload(
        task_id="TASK-WRONGCAP-ST1",
        agent_id="WRONG-ROBOT",
        capabilities=["bin_picking"],  # agent lies about capabilities
        payload_capacity_kg=30.0,
        battery_pct=100.0,
        available=True,
        capability_match=True,
        utility=0.75,
        estimated_cost=5.0,
    )

    reason = validator.rejection_reason(task, proposal)
    assert reason == "REGISTERED_CAPABILITY_MISMATCH", (
        f"Should still reject mismatched capabilities when registry is populated. Got: {reason}"
    )


def test_cooperative_subtask_proposal_negotiation_and_assignment_end_to_end(caplog):
    """
    Full regression for the cooperative subtask allocation path:
    - TASK_PROPOSAL for a subtask is persisted into subtask.proposals
    - _negotiate produces an assignment when an eligible proposal exists
    - Rejected agents remain in task.rejections
    - proposals list is not destroyed
    """
    caplog.set_level(logging.INFO)
    agents = [
        AgentRuntime(
            agent_id="COOP-PROP-ROBOT",
            agent_type="warehouse_robot",
            capabilities=["bin_picking"],
            payload_capacity_kg=30,
            heartbeat_interval_sec=0.5,
        ),
        AgentRuntime(
            agent_id="COOP-PROP-AGV",
            agent_type="agv",
            capabilities=["ground_transport"],
            payload_capacity_kg=250,
            heartbeat_interval_sec=0.5,
        ),
        AgentRuntime(
            agent_id="COOP-PROP-DRONE",
            agent_type="drone",
            capabilities=["aerial_delivery"],
            payload_capacity_kg=5,
            heartbeat_interval_sec=0.5,
        ),
    ]
    for agent in agents:
        agent.subtask_execution_seconds = 0.25

    started = []
    try:
        with TestClient(app) as client:
            task_coordination_service._tasks.clear()
            for agent in agents:
                assert agent.start()
                started.append(agent)
                platform_registry_service.registry.register_agent(AgentRegistrationPayload(
                    agent_id=agent.agent_id,
                    agent_type=agent.agent_type,
                    capabilities=agent.capability.capabilities,
                    payload_capacity_kg=agent.capability.payload_capacity_kg,
                    supported_operations=agent.capability.supported_operations,
                    status=agent.state.status,
                    initial_state=agent.state.to_model(),
                    metadata=agent.identity.metadata,
                ))

            response = client.post(
                "/api/v1/tasks",
                json={
                    "task_type": "cooperative_delivery",
                    "origin": "Warehouse A",
                    "destination": "Distribution Center",
                    "payload_weight": 2.0,
                    "priority": 3,
                    "estimated_distance_km": 10.0,
                    "cooperative": True,
                },
            )
            assert response.status_code == 201, response.text
            parent = response.json()
            parent_id = parent["task_id"]
            subtasks = client.get(f"/api/v1/tasks/{parent_id}/subtasks").json()
            assert len(subtasks) == 3

            by_type = {s["subtask_type"]: s for s in subtasks}

            # Core regression assertions:
            # 1. Proposals must NOT be empty — they were received and stored
            for st in subtasks:
                assert len(st["proposals"]) >= 1, (
                    f"Subtask {st['task_id']} ({st['subtask_type']}) has no proposals — "
                    f"proposals were destroyed by _negotiate(). rejections={st['rejections']}"
                )

            # 2. Each subtask must be assigned to the correctly-capable agent
            assert by_type["pickup"]["assigned_agent_id"] == "COOP-PROP-ROBOT"
            assert by_type["transport"]["assigned_agent_id"] == "COOP-PROP-AGV"
            assert by_type["delivery"]["assigned_agent_id"] == "COOP-PROP-DRONE"

            # 3. Negotiation status must be AGREED
            for st in subtasks:
                assert st["negotiation_status"] == "AGREED", (
                    f"{st['subtask_type']} negotiation_status={st['negotiation_status']}"
                )

            # 4. Wrong-capability agents must be in rejections (not proposals)
            pickup_rejections = {r["agent_id"] for r in by_type["pickup"]["rejections"]}
            assert "COOP-PROP-AGV" in pickup_rejections or "COOP-PROP-DRONE" in pickup_rejections

    finally:
        for agent in reversed(started):
            agent.stop()
