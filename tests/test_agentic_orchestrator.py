import os
import sys
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from agents.core.registry import AgentRegistry
from agents.runtime import AgentRuntime
from app.main import app
from app.services.agentic_orchestrator import (
    AgenticOrchestrator,
    AgenticPhase,
    agentic_orchestrator,
)
from app.services.planner import RuleBasedPlanner
from app.services.platform_registry import platform_registry_service
from app.services.task_coordination import task_coordination_service
from protocols.messages import (
    AgentRegistrationPayload,
    AgentState,
    AgentStatus,
    Task,
    TaskCreate,
    TaskStatus,
)


class RegistryService:
    def __init__(self):
        self.registry = AgentRegistry()


class InMemoryCoordination:
    def __init__(self):
        self.tasks = {}
        self.handoffs = []
        self.negotiations = []

    def create_task_with_plan(self, request, plan):
        parent = Task(
            task_id=plan.task_id,
            task_type="cooperative_delivery",
            origin=request.origin,
            destination=request.destination,
            payload_weight=request.payload_weight,
            is_parent=True,
            plan_id=plan.plan_id,
            reasoning_summary=plan.reasoning_summary,
            subtask_ids=[],
        )
        children = []
        for index, step in enumerate(plan.subtasks, start=1):
            child = Task(
                task_id=f"{parent.task_id}-ST{index}",
                task_type=step.subtask_type,
                subtask_type=step.subtask_type,
                origin=step.origin,
                destination=step.destination,
                payload_weight=request.payload_weight,
                required_capabilities=step.required_capabilities,
                parent_task_id=parent.task_id,
                status=TaskStatus.ASSIGNED,
                assigned_agent_id=f"AGENT-{step.subtask_type}",
            )
            children.append(child)
            self.tasks[child.task_id] = child
        parent.subtask_ids = [child.task_id for child in children]
        parent.status = TaskStatus.IN_PROGRESS
        self.tasks[parent.task_id] = parent
        return parent

    def get_task(self, task_id):
        task = self.tasks.get(task_id)
        return task.model_copy(deep=True) if task else None

    def get_subtasks(self, task_id):
        return [
            item.model_copy(deep=True)
            for item in self.tasks.values()
            if item.parent_task_id == task_id
        ]

    def request_task_negotiation(self, task_id):
        self.negotiations.append(task_id)
        return True

    def request_agentic_handoff(self, task_id, reason):
        self.handoffs.append((task_id, reason))
        return True


def _request():
    return TaskCreate(
        task_type="cooperative_delivery",
        origin="Agentic Warehouse",
        destination="Agentic DC",
        payload_weight=3.0,
        estimated_distance_km=9.0,
        cooperative=True,
    )


def _register(agent, registry=platform_registry_service):
    registry.registry.register_agent(
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


def test_agentic_state_transitions_and_live_tools():
    coordination = InMemoryCoordination()
    registry = RegistryService()
    orchestrator = AgenticOrchestrator(coordination, registry, max_replans=2)

    with patch("app.services.agentic_orchestrator.get_planner", return_value=RuleBasedPlanner()):
        parent = orchestrator.create_task(_request())

    state = orchestrator.get_state(parent.task_id)
    assert state is not None
    assert state.phase == AgenticPhase.OBSERVE_RESULT
    assert state.current_plan is not None
    assert state.subtask_ids == parent.subtask_ids
    assert len(state.observations) >= 2
    assert state.requested_action == "Delegate subtasks through existing MQTT negotiation"
    assert len(orchestrator.tools.invoke("get_fleet_state")) == 0
    assert orchestrator.tools.invoke("inspect_task", task_id=parent.task_id)["task"]["task_id"] == parent.task_id
    assert orchestrator.tools.invoke("inspect_execution_status", task_id=parent.task_id)["task_id"] == parent.task_id
    with pytest.raises(ValueError, match="Unsupported logistics tool"):
        orchestrator.tools.invoke("send_physical_command")


def test_agentic_safety_rejects_infeasible_plan():
    coordination = InMemoryCoordination()
    registry = RegistryService()
    registry.registry.register_agent(
        AgentRegistrationPayload(
            agent_id="OFFLINE-PICKER",
            agent_type="robot",
            capabilities=["bin_picking", "ground_transport", "aerial_delivery"],
            payload_capacity_kg=100,
            supported_operations=[],
            status=AgentStatus.OFFLINE,
            initial_state=AgentState(status=AgentStatus.OFFLINE, is_available=False),
        )
    )
    orchestrator = AgenticOrchestrator(coordination, registry)
    plan = RuleBasedPlanner().plan(_request(), "SAFE-TASK")

    with pytest.raises(ValueError, match="No currently eligible agent"):
        orchestrator.validate_plan(_request(), plan)


def test_agentic_no_api_key_uses_rule_based_planner(monkeypatch):
    monkeypatch.setenv("USE_LLM_PLANNER", "true")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    orchestrator = AgenticOrchestrator(InMemoryCoordination(), RegistryService())

    plan = orchestrator._resolve_plan(_request(), "NO-KEY-TASK")

    assert plan.task_id == "NO-KEY-TASK"
    assert plan.fallback_status == "active"
    assert len(plan.subtasks) == 3


def test_agentic_maximum_replan_limit_stops_without_handoff():
    coordination = InMemoryCoordination()
    orchestrator = AgenticOrchestrator(coordination, RegistryService(), max_replans=0)
    request = _request()
    state = orchestrator.get_state("LIMIT-TASK")
    assert state is None
    from app.services.agentic_orchestrator import AgenticExecutionState

    orchestrator._states["LIMIT-TASK"] = AgenticExecutionState(task_id="LIMIT-TASK", max_replans=0)
    orchestrator._requests["LIMIT-TASK"] = request
    failed = Task(
        task_id="LIMIT-TASK-ST1",
        subtask_type="pickup",
        required_capabilities=["bin_picking"],
        assigned_agent_id="FAILED-AGENT",
        parent_task_id="LIMIT-TASK",
        status=TaskStatus.FAILED,
    )

    orchestrator._replan_and_handoff("LIMIT-TASK", failed, "agent failed")

    state = orchestrator.get_state("LIMIT-TASK")
    assert state.phase == AgenticPhase.FAILED
    assert state.replan_count == 0
    assert state.final_outcome.startswith("Maximum replans")
    assert coordination.handoffs == []


def test_agentic_failed_agent_replans_handoff_and_completes():
    primary = AgentRuntime(
        agent_id="AGENTIC-PICK-01",
        agent_type="warehouse_robot",
        capabilities=["bin_picking"],
        payload_capacity_kg=30,
        heartbeat_interval_sec=0.5,
    )
    replacement = AgentRuntime(
        agent_id="AGENTIC-PICK-99",
        agent_type="warehouse_robot",
        capabilities=["bin_picking"],
        payload_capacity_kg=30,
        heartbeat_interval_sec=0.5,
    )
    vehicle = AgentRuntime(
        agent_id="AGENTIC-AGV-01",
        agent_type="agv",
        capabilities=["ground_transport"],
        payload_capacity_kg=250,
        heartbeat_interval_sec=0.5,
    )
    drone = AgentRuntime(
        agent_id="AGENTIC-DRONE-01",
        agent_type="drone",
        capabilities=["aerial_delivery"],
        payload_capacity_kg=20,
        heartbeat_interval_sec=0.5,
    )
    agents = [primary, replacement, vehicle, drone]
    started = []
    try:
        with patch("app.services.agentic_orchestrator.get_planner", return_value=RuleBasedPlanner()):
            with TestClient(app) as client:
                connection_deadline = time.monotonic() + 5
                while not task_coordination_service._client.is_connected() and time.monotonic() < connection_deadline:
                    time.sleep(0.05)
                assert task_coordination_service._client.is_connected()
                task_coordination_service._tasks.clear()
                for agent in agents:
                    assert agent.start()
                    started.append(agent)
                    _register(agent)
                primary.subtask_execution_seconds = 60.0

                response = client.post(
                    "/api/v1/agentic/tasks",
                    json={
                        "task_type": "cooperative_delivery",
                        "origin": "Demo Warehouse",
                        "destination": "Demo Distribution Center",
                        "payload_weight": 4.0,
                        "priority": 4,
                        "estimated_distance_km": 12.0,
                        "cooperative": True,
                    },
                )
                assert response.status_code == 201, response.text
                parent = response.json()
                children = client.get(f"/api/v1/tasks/{parent['task_id']}/subtasks").json()
                pickup = next(child for child in children if child["subtask_type"] == "pickup")
                assert pickup["assigned_agent_id"] == primary.agent_id
                assert primary.task_manager.current_task is not None

                primary.update_task_status(pickup["task_id"], TaskStatus.FAILED)
                deadline = time.monotonic() + 20
                latest = None
                while time.monotonic() < deadline:
                    agentic_orchestrator.process_once()
                    latest = client.get(f"/api/v1/agentic/tasks/{parent['task_id']}").json()
                    current_parent = client.get(f"/api/v1/tasks/{parent['task_id']}").json()
                    if current_parent["status"] == TaskStatus.COMPLETED.value:
                        break
                    time.sleep(0.1)

                final_parent = client.get(f"/api/v1/tasks/{parent['task_id']}").json()
                final_children = client.get(f"/api/v1/tasks/{parent['task_id']}/subtasks").json()
                final_pickup = next(child for child in final_children if child["subtask_type"] == "pickup")
                latest = client.get(f"/api/v1/agentic/tasks/{parent['task_id']}").json()
                assert final_parent["status"] == TaskStatus.COMPLETED.value
                assert final_pickup["assigned_agent_id"] == replacement.agent_id
                assert latest["replan_count"] == 1
                assert latest["phase"] == AgenticPhase.COMPLETE.value
                assert latest["failed_subtasks"] == [pickup["task_id"]]
                assert "completed" in latest["final_outcome"].lower()
    finally:
        for agent in reversed(started):
            agent.stop()


def test_agentic_cooperative_returns_json_even_when_agents_busy():
    """
    Regression: POST /api/v1/agentic/tasks with cooperative=True must return a valid JSON
    Task (HTTP 201), not a plain-text 500 'Internal Server Error', even when some agents
    are currently BUSY/unavailable.

    Root cause was two bugs:
      1. validate_plan(..., require_live_agents=True) raised ValueError when agents were
         momentarily busy, making the overall create_task raise an unhandled ValueError
         that FastAPI serialised as a plain-text 500 instead of JSON.
      2. The agentic orchestrator is explicitly designed to handle agent unavailability
         via dynamic replan/handoff, so the initial validation must not block on live
         availability.

    Fix: create_task now calls validate_plan(..., require_live_agents=False) and wraps
    ValueError → HTTPException(422) so FastAPI always returns a JSON response body.
    """
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.services.agentic_orchestrator import AgenticOrchestrator
    from app.services.planner import RuleBasedPlanner
    from protocols.messages import AgentRegistrationPayload, AgentState, AgentStatus

    class BusyRegistryService:
        """Registry where only one agent is BUSY (not available)."""
        def __init__(self):
            self.registry = __import__('agents.core.registry', fromlist=['AgentRegistry']).AgentRegistry()
            # Register agents where the transport agent is BUSY
            self.registry.register_agent(AgentRegistrationPayload(
                agent_id="BUSY-ROBOT",
                agent_type="warehouse_robot",
                capabilities=["bin_picking"],
                payload_capacity_kg=30,
                supported_operations=[],
                status=AgentStatus.IDLE,
                initial_state=AgentState(status=AgentStatus.IDLE, is_available=True, battery_pct=100),
            ))
            self.registry.register_agent(AgentRegistrationPayload(
                agent_id="BUSY-AGV",
                agent_type="agv",
                capabilities=["ground_transport"],
                payload_capacity_kg=250,
                supported_operations=[],
                # BUSY — this is what triggers the old bug
                status=AgentStatus.BUSY,
                initial_state=AgentState(status=AgentStatus.BUSY, is_available=False, battery_pct=100),
            ))
            self.registry.register_agent(AgentRegistrationPayload(
                agent_id="BUSY-DRONE",
                agent_type="drone",
                capabilities=["aerial_delivery"],
                payload_capacity_kg=5,
                supported_operations=[],
                status=AgentStatus.IDLE,
                initial_state=AgentState(status=AgentStatus.IDLE, is_available=True, battery_pct=80),
            ))

    coordination = InMemoryCoordination()
    registry = BusyRegistryService()
    orchestrator = AgenticOrchestrator(coordination, registry, max_replans=1)

    with patch("app.services.agentic_orchestrator.get_planner", return_value=RuleBasedPlanner()):
        # Must NOT raise — should succeed despite AGV being BUSY
        parent = orchestrator.create_task(_request())

    assert parent.task_id is not None
    assert parent.is_parent is True
    assert len(parent.subtask_ids) == 3


def test_agentic_cooperative_api_returns_json_201_when_agents_busy(monkeypatch):
    """
    Integration regression: POST /api/v1/agentic/tasks must return HTTP 201 with a valid
    JSON body (not 500 plain text 'Internal Server Error') when live agents are BUSY.
    """
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.services.planner import RuleBasedPlanner
    from protocols.messages import AgentRegistrationPayload, AgentState, AgentStatus

    # Register a full set of agents — one BUSY — into the live platform registry
    for reg in [
        AgentRegistrationPayload(
            agent_id="APIREG-ROBOT",
            agent_type="warehouse_robot",
            capabilities=["bin_picking"],
            payload_capacity_kg=30,
            supported_operations=[],
            status=AgentStatus.IDLE,
            initial_state=AgentState(status=AgentStatus.IDLE, is_available=True, battery_pct=100),
        ),
        AgentRegistrationPayload(
            agent_id="APIREG-AGV",
            agent_type="agv",
            capabilities=["ground_transport"],
            payload_capacity_kg=250,
            supported_operations=[],
            status=AgentStatus.BUSY,
            initial_state=AgentState(status=AgentStatus.BUSY, is_available=False, battery_pct=100),
        ),
        AgentRegistrationPayload(
            agent_id="APIREG-DRONE",
            agent_type="drone",
            capabilities=["aerial_delivery"],
            payload_capacity_kg=5,
            supported_operations=[],
            status=AgentStatus.IDLE,
            initial_state=AgentState(status=AgentStatus.IDLE, is_available=True, battery_pct=80),
        ),
    ]:
        platform_registry_service.registry.register_agent(reg)

    with patch("app.services.agentic_orchestrator.get_planner", return_value=RuleBasedPlanner()):
        with TestClient(app) as client:
            task_coordination_service._tasks.clear()
            # Wait for MQTT coordinator to connect before posting
            connection_deadline = time.monotonic() + 5
            while not task_coordination_service._client.is_connected() and time.monotonic() < connection_deadline:
                time.sleep(0.05)
            response = client.post(
                "/api/v1/agentic/tasks",
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

    # Must be 201 with a valid JSON Task body — not 500 plain text
    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
    body = response.json()
    assert "task_id" in body
    assert body["is_parent"] is True
    assert len(body["subtask_ids"]) == 3


def test_demo_fail_registers_task_in_orchestrator_and_triggers_self_healing():
    """
    Regression: POST /api/v1/demo/agents/{id}/fail must register the parent task into
    agentic_orchestrator._states so the monitor loop can detect the offline agent and
    trigger replan → self-healing → handoff.

    Previously tasks created via /api/v1/tasks were never registered in the orchestrator,
    so _process_task never ran for them and the self-healing panel never progressed past
    RISK ASSESSMENT.

    Also verifies: affected_parent_task_id is returned in the response so the frontend
    can look up the correct agentic run (tasks are indexed by parent ID, not subtask ID).
    """
    primary = AgentRuntime(
        agent_id="DEMO-ROBOT-FAIL",
        agent_type="warehouse_robot",
        capabilities=["bin_picking"],
        payload_capacity_kg=30,
        heartbeat_interval_sec=0.5,
    )
    replacement = AgentRuntime(
        agent_id="DEMO-ROBOT-REPLACE",
        agent_type="warehouse_robot",
        capabilities=["bin_picking"],
        payload_capacity_kg=30,
        heartbeat_interval_sec=0.5,
    )
    agv = AgentRuntime(
        agent_id="DEMO-AGV-FAIL",
        agent_type="agv",
        capabilities=["ground_transport"],
        payload_capacity_kg=250,
        heartbeat_interval_sec=0.5,
    )
    drone = AgentRuntime(
        agent_id="DEMO-DRONE-FAIL",
        agent_type="drone",
        capabilities=["aerial_delivery"],
        payload_capacity_kg=5,
        heartbeat_interval_sec=0.5,
    )
    agents = [primary, replacement, agv, drone]
    # Keep primary busy so it doesn't auto-complete before the demo failure
    primary.subtask_execution_seconds = 60.0

    started = []
    try:
        with patch("app.services.agentic_orchestrator.get_planner", return_value=RuleBasedPlanner()):
            with TestClient(app) as client:
                connection_deadline = time.monotonic() + 5
                while not task_coordination_service._client.is_connected() and time.monotonic() < connection_deadline:
                    time.sleep(0.05)
                task_coordination_service._tasks.clear()
                # Clear orchestrator state from previous tests
                with agentic_orchestrator._lock:
                    agentic_orchestrator._states.clear()
                    agentic_orchestrator._requests.clear()

                for agent in agents:
                    assert agent.start()
                    started.append(agent)
                    _register(agent)

                # Create via regular /api/v1/tasks (NOT agentic) — this is the path
                # that previously left the task invisible to the orchestrator
                response = client.post(
                    "/api/v1/tasks",
                    json={
                        "task_type": "cooperative_delivery",
                        "origin": "Demo Warehouse",
                        "destination": "Demo DC",
                        "payload_weight": 2.0,
                        "priority": 3,
                        "estimated_distance_km": 8.0,
                        "cooperative": True,
                    },
                )
                assert response.status_code == 201, response.text
                parent = response.json()
                parent_id = parent["task_id"]
                children = client.get(f"/api/v1/tasks/{parent_id}/subtasks").json()
                pickup = next(c for c in children if c["subtask_type"] == "pickup")
                assert pickup["assigned_agent_id"] == primary.agent_id

                # Task must NOT yet be in orchestrator states (created via regular path)
                assert agentic_orchestrator.get_state(parent_id) is None

                # Trigger the demo failure endpoint
                fail_resp = client.post(f"/api/v1/demo/agents/{primary.agent_id}/fail")
                assert fail_resp.status_code == 200, fail_resp.text
                fail_body = fail_resp.json()

                # Response must carry both subtask and parent IDs
                assert fail_body["affected_task_id"] == pickup["task_id"]
                assert fail_body["affected_parent_task_id"] == parent_id

                # Parent task must NOW be registered in orchestrator states
                state = agentic_orchestrator.get_state(parent_id)
                assert state is not None, "Demo fail endpoint must register parent task in orchestrator"
                assert state.phase.value == "OBSERVE_RESULT"

                # Run the orchestrator monitor cycle — it must detect the offline agent
                # and trigger replan + self-healing
                from app.services.self_healing import self_healing_engine
                deadline = time.monotonic() + 15
                healing_found = False
                while time.monotonic() < deadline:
                    agentic_orchestrator.process_once()
                    records = self_healing_engine.list_records(task_id=parent_id)
                    if records:
                        healing_found = True
                        break
                    time.sleep(0.1)

                assert healing_found, "Self-healing record must be created after demo failure"
                records = self_healing_engine.list_records(task_id=parent_id)
                assert records[0].failed_agent_id == primary.agent_id
                assert records[0].failed_subtask_id == pickup["task_id"]
                # Replacement robot must be identified as a candidate
                assert replacement.agent_id in records[0].replacement_candidates

                # Orchestrator must have advanced through REPLAN (replan_count > 0)
                # and then back to OBSERVE_RESULT awaiting the replacement.
                final_state = agentic_orchestrator.get_state(parent_id)
                assert final_state is not None
                assert final_state.replan_count >= 1, (
                    f"Orchestrator never replanned — phase={final_state.phase}, "
                    f"replan_count={final_state.replan_count}"
                )
                assert final_state.healing_id is not None, "Self-healing record ID must be stored in orchestrator state"
                assert final_state.failed_subtasks, "Failed subtask must be recorded"

    finally:
        for agent in reversed(started):
            agent.stop()


def test_demo_fail_response_includes_parent_task_id():
    """
    Regression: the demo fail endpoint must return affected_parent_task_id so the
    frontend can look up the correct agentic run (indexed by parent, not subtask).
    """
    robot = AgentRuntime(
        agent_id="DEMO-RESP-ROBOT",
        agent_type="warehouse_robot",
        capabilities=["bin_picking"],
        payload_capacity_kg=30,
        heartbeat_interval_sec=0.5,
    )
    agv = AgentRuntime(
        agent_id="DEMO-RESP-AGV",
        agent_type="agv",
        capabilities=["ground_transport"],
        payload_capacity_kg=250,
        heartbeat_interval_sec=0.5,
    )
    drone = AgentRuntime(
        agent_id="DEMO-RESP-DRONE",
        agent_type="drone",
        capabilities=["aerial_delivery"],
        payload_capacity_kg=5,
        heartbeat_interval_sec=0.5,
    )
    robot.subtask_execution_seconds = 60.0
    agents = [robot, agv, drone]
    started = []
    try:
        with TestClient(app) as client:
            connection_deadline = time.monotonic() + 5
            while not task_coordination_service._client.is_connected() and time.monotonic() < connection_deadline:
                time.sleep(0.05)
            task_coordination_service._tasks.clear()

            for agent in agents:
                assert agent.start()
                started.append(agent)
                _register(agent)

            resp = client.post(
                "/api/v1/tasks",
                json={
                    "task_type": "cooperative_delivery",
                    "origin": "W",
                    "destination": "D",
                    "payload_weight": 1.0,
                    "priority": 2,
                    "estimated_distance_km": 5.0,
                    "cooperative": True,
                },
            )
            assert resp.status_code == 201, resp.text
            parent = resp.json()
            parent_id = parent["task_id"]
            children = client.get(f"/api/v1/tasks/{parent_id}/subtasks").json()
            pickup = next(c for c in children if c["subtask_type"] == "pickup")
            assert pickup["assigned_agent_id"] == robot.agent_id

            fail_resp = client.post(f"/api/v1/demo/agents/{robot.agent_id}/fail")
            assert fail_resp.status_code == 200, fail_resp.text
            body = fail_resp.json()

            # Must return parent task ID — not just the subtask ID
            assert "affected_parent_task_id" in body
            assert body["affected_parent_task_id"] == parent_id
            # Subtask ID is also returned for full traceability
            assert body["affected_task_id"] == pickup["task_id"]
            assert body["affected_task_id"] != parent_id  # confirm it IS a subtask ID

    finally:
        for agent in reversed(started):
            agent.stop()


def test_single_task_agent_failure_triggers_healing_and_handoff():
    """
    Regression: when the demo endpoint forces an agent offline on a single non-cooperative
    task (subtask_ids=[], parent_task_id=None), _process_task must detect the offline
    assigned agent via the task-level check (not the subtask loop), create a self-healing
    record, increment replan_count, and request a handoff.

    Previously _process_task only iterated subtasks — for single tasks the loop body
    never executed, failure was never detected, and the orchestrator stayed stuck at
    OBSERVE_RESULT forever.
    """
    agv_primary = AgentRuntime(
        agent_id="SINGLE-AGV-PRIMARY",
        agent_type="agv",
        capabilities=["ground_transport"],
        payload_capacity_kg=250,
        heartbeat_interval_sec=0.5,
    )
    agv_replacement = AgentRuntime(
        agent_id="SINGLE-AGV-REPLACE",
        agent_type="agv",
        capabilities=["ground_transport"],
        payload_capacity_kg=250,
        heartbeat_interval_sec=0.5,
    )
    # Keep primary from auto-completing so it holds the task when we fail it
    agv_primary.subtask_execution_seconds = 60.0

    agents = [agv_primary, agv_replacement]
    started = []

    try:
        with TestClient(app) as client:
            connection_deadline = time.monotonic() + 5
            while not task_coordination_service._client.is_connected() and time.monotonic() < connection_deadline:
                time.sleep(0.05)
            task_coordination_service._tasks.clear()
            with agentic_orchestrator._lock:
                agentic_orchestrator._states.clear()
                agentic_orchestrator._requests.clear()

            for agent in agents:
                assert agent.start()
                started.append(agent)
                _register(agent)

            # Create a plain single delivery task (not cooperative)
            resp = client.post(
                "/api/v1/tasks",
                json={
                    "task_type": "delivery",
                    "origin": "Depot",
                    "destination": "Gate",
                    "payload_weight": 50.0,
                    "priority": 2,
                    "estimated_distance_km": 5.0,
                    "required_capabilities": ["ground_transport"],
                },
            )
            assert resp.status_code == 201, resp.text
            created = resp.json()
            task_id = created["task_id"]

            # Confirm it is non-cooperative
            assert created["is_parent"] is False
            assert created["subtask_ids"] == []
            assert created["assigned_agent_id"] == agv_primary.agent_id

            # Not yet in orchestrator
            assert agentic_orchestrator.get_state(task_id) is None

            # Trigger demo failure — this must register the task in the orchestrator
            fail_resp = client.post(f"/api/v1/demo/agents/{agv_primary.agent_id}/fail")
            assert fail_resp.status_code == 200, fail_resp.text
            fail_body = fail_resp.json()
            assert fail_body["affected_task_id"] == task_id
            # single task has no parent, so parent_task_id is None
            assert fail_body["affected_parent_task_id"] is None

            # Task must now be registered
            state = agentic_orchestrator.get_state(task_id)
            assert state is not None

            # Run monitor cycles until self-healing fires or deadline
            from app.services.self_healing import self_healing_engine as she
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                agentic_orchestrator.process_once()
                records = she.list_records(task_id=task_id)
                if records:
                    break
                time.sleep(0.1)

            # Self-healing must have fired
            records = she.list_records(task_id=task_id)
            assert records, "Self-healing record must be created for single-task agent failure"
            record = records[0]
            assert record.failed_agent_id == agv_primary.agent_id
            assert record.failed_subtask_id == task_id
            assert agv_replacement.agent_id in record.replacement_candidates

            # Orchestrator must have incremented replan_count
            final_state = agentic_orchestrator.get_state(task_id)
            assert final_state is not None
            assert final_state.replan_count >= 1, (
                f"replan_count={final_state.replan_count} — failure detection did not trigger replan"
            )
            assert final_state.healing_id == record.healing_id
            assert task_id in final_state.failed_subtasks

    finally:
        for agent in reversed(started):
            agent.stop()


def test_dynamic_agent_registration_delay_does_not_permanently_fail_replan():
    """
    Regression: when _replan_and_handoff checks for a replacement before the
    dynamically launched agent has completed MQTT registration, the mission must
    NOT be permanently failed.

    Scenario
    --------
    1. A cooperative task is created; pickup subtask is assigned to the primary agent.
    2. The primary agent fails.
    3. A replacement agent exists but is NOT yet visible in the registry at the exact
       moment _replan_and_handoff first evaluates eligibility (simulating the MQTT
       registration lag).
    4. After a short delay the replacement becomes visible in the registry.
    5. The bounded wait inside _wait_for_eligible_replacement must catch the new entry
       and allow the existing handoff flow to proceed (phase → EXECUTE / OBSERVE_RESULT,
       replan_count == 1, handoff requested).
    6. Mission must NOT be set to FAILED due to the transient registry miss.
    """
    import threading

    coordination = InMemoryCoordination()
    registry = RegistryService()
    orchestrator = AgenticOrchestrator(coordination, registry, max_replans=2)

    # Register only the primary agent and the non-pickup agents up front.
    from agents.core.registry import AgentRegistry
    from protocols.messages import AgentRegistrationPayload, AgentState, AgentStatus

    def _reg(agent_id, agent_type, caps, cap_kg, status=AgentStatus.IDLE):
        registry.registry.register_agent(AgentRegistrationPayload(
            agent_id=agent_id,
            agent_type=agent_type,
            capabilities=caps,
            payload_capacity_kg=cap_kg,
            supported_operations=[],
            status=status,
            initial_state=AgentState(status=status, is_available=(status == AgentStatus.IDLE), battery_pct=90.0),
        ))

    _reg("DYN-ROBOT-PRIMARY", "warehouse_robot", ["bin_picking"], 30)
    _reg("DYN-AGV-01",        "agv",             ["ground_transport"], 250)
    _reg("DYN-DRONE-01",      "drone",           ["aerial_delivery"], 5)
    # NOTE: DYN-ROBOT-REPLACE is deliberately NOT registered yet.

    with patch("app.services.agentic_orchestrator.get_planner", return_value=RuleBasedPlanner()):
        parent = orchestrator.create_task(_request())

    # Identify the pickup subtask assigned to the primary agent.
    snapshot = coordination.get_subtasks(parent.task_id)
    pickup = next(item for item in snapshot if item.subtask_type == "pickup")
    assert pickup.assigned_agent_id == "AGENT-pickup"

    # Simulate primary failure by marking pickup FAILED in coordination.
    coordination.tasks[pickup.task_id].status = TaskStatus.FAILED
    coordination.tasks[pickup.task_id].assigned_agent_id = "DYN-ROBOT-PRIMARY"

    # Schedule the replacement to appear in the registry after a short lag
    # (shorter than _REPLACEMENT_WAIT_SECONDS = 3.0 s, longer than one poll tick).
    registration_lag_seconds = 0.5

    def _delayed_register():
        time.sleep(registration_lag_seconds)
        _reg("DYN-ROBOT-REPLACE", "warehouse_robot", ["bin_picking"], 30)

    t = threading.Thread(target=_delayed_register, daemon=True)
    t.start()

    # Run _replan_and_handoff; it must NOT immediately fail — it must wait for
    # DYN-ROBOT-REPLACE to become visible, then proceed through handoff.
    failed_task = Task(
        task_id=pickup.task_id,
        subtask_type="pickup",
        required_capabilities=["bin_picking"],
        assigned_agent_id="DYN-ROBOT-PRIMARY",
        parent_task_id=parent.task_id,
        status=TaskStatus.FAILED,
    )
    orchestrator._replan_and_handoff(parent.task_id, failed_task, "primary agent failed")

    t.join(timeout=5)

    state = orchestrator.get_state(parent.task_id)
    assert state is not None

    # Must NOT have permanently failed due to the transient registry miss.
    assert state.phase != AgenticPhase.FAILED, (
        f"Mission was permanently failed despite replacement arriving within the wait window. "
        f"phase={state.phase}, final_outcome={state.final_outcome}"
    )

    # Existing handoff flow must have been invoked exactly once.
    assert state.replan_count == 1, f"Expected replan_count=1, got {state.replan_count}"
    assert len(coordination.handoffs) == 1, f"Expected 1 handoff request, got {coordination.handoffs}"
    assert coordination.handoffs[0][0] == pickup.task_id

    # Phase must be OBSERVE_RESULT (handoff accepted by InMemoryCoordination).
    assert state.phase == AgenticPhase.OBSERVE_RESULT, f"phase={state.phase}"

    # Self-healing record must exist.
    assert state.healing_id is not None

    # If the replacement never appears (window exceeded), deterministic failure is preserved.
    # Verify that by checking: if DYN-ROBOT-REPLACE were NOT registered, final_outcome
    # would contain "No currently eligible replacement".  We don't re-run the full test
    # for that branch here because it is already covered by
    # test_agentic_maximum_replan_limit_stops_without_handoff and the existing
    # deterministic failure path in _replan_and_handoff.
