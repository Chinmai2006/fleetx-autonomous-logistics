"""Phase 4C — cooperative multi-agent task execution tests."""

import logging
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from agents.runtime import AgentRuntime
from app.main import app
from app.services.platform_registry import platform_registry_service
from app.services.task_coordination import task_coordination_service
from app.services.task_decomposition import (
    decompose_task,
    decomposition_plan,
    should_decompose,
)
from protocols.messages import (
    AgentRegistrationPayload,
    EventType,
    HandoffState,
    NegotiationStatus,
    Task,
    TaskCreate,
    TaskStatus,
)


def _register(agent: AgentRuntime) -> None:
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


def test_deterministic_task_decomposition_and_parent_relationship():
    request = TaskCreate(
        task_type="cooperative_delivery",
        origin="Warehouse A",
        destination="Distribution Center",
        payload_weight=2.0,
        priority=4,
        cooperative=True,
        estimated_distance_km=12.0,
    )
    assert should_decompose(request) is True
    assert should_decompose(TaskCreate(origin="A", destination="B", required_capabilities=["ground_transport"])) is False

    plan = decomposition_plan(request)
    assert [step.subtask_type for step in plan] == ["pickup", "transport", "delivery"]
    assert list(plan[0].required_capabilities) == ["bin_picking"]
    assert list(plan[1].required_capabilities) == ["ground_transport"]
    assert list(plan[2].required_capabilities) == ["aerial_delivery"]

    parent = Task(
        task_id="TASK-DECOMP01",
        task_type="cooperative_delivery",
        origin=request.origin,
        destination=request.destination,
        payload_weight=request.payload_weight,
        priority=request.priority,
        is_parent=True,
    )
    first = decompose_task(parent, request)
    second = decompose_task(parent, request)
    assert [item.task_id for item in first] == [item.task_id for item in second]
    assert first[0].task_id == "TASK-DECOMP01-ST1"
    assert all(item.parent_task_id == parent.task_id for item in first)
    assert {item.subtask_type for item in first} == {"pickup", "transport", "delivery"}


def test_subtask_capability_validation_matches_stage_requirements():
    robot = AgentRuntime(agent_id="CAP-ROBOT", agent_type="warehouse_robot", capabilities=["bin_picking"], payload_capacity_kg=30)
    agv = AgentRuntime(agent_id="CAP-AGV", agent_type="agv", capabilities=["ground_transport"], payload_capacity_kg=250)
    drone = AgentRuntime(agent_id="CAP-DRONE", agent_type="drone", capabilities=["aerial_delivery"], payload_capacity_kg=5)

    pickup = Task(origin="A", destination="A Staging", required_capabilities=["bin_picking"], parent_task_id="P", subtask_type="pickup")
    transport = Task(origin="A", destination="B", required_capabilities=["ground_transport"], parent_task_id="P", subtask_type="transport")
    delivery = Task(origin="B Apron", destination="B", required_capabilities=["aerial_delivery"], parent_task_id="P", subtask_type="delivery")

    assert robot.evaluate_task(pickup) is None
    assert robot.evaluate_task(transport) == "MISSING_CAPABILITIES:ground_transport"
    assert agv.evaluate_task(transport) is None
    assert agv.evaluate_task(delivery) == "MISSING_CAPABILITIES:aerial_delivery"
    assert drone.evaluate_task(delivery) is None
    assert drone.evaluate_task(pickup) == "MISSING_CAPABILITIES:bin_picking"


def test_cooperative_mqtt_multi_agent_allocation_completion_and_parent_status(caplog):
    caplog.set_level(logging.INFO)
    agents = [
        AgentRuntime(
            agent_id="COOP-ROBOT",
            agent_type="warehouse_robot",
            capabilities=["bin_picking", "barcode_scanning", "item_sorting"],
            payload_capacity_kg=30,
            heartbeat_interval_sec=0.5,
        ),
        AgentRuntime(
            agent_id="COOP-AGV",
            agent_type="agv",
            capabilities=["heavy_freight", "ground_transport", "docking"],
            payload_capacity_kg=250,
            heartbeat_interval_sec=0.5,
        ),
        AgentRuntime(
            agent_id="COOP-DRONE",
            agent_type="drone",
            capabilities=["aerial_delivery", "rapid_reconnaissance", "vertical_takeoff"],
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
                _register(agent)

            response = client.post(
                "/api/v1/tasks",
                json={
                    "task_type": "cooperative_delivery",
                    "origin": "Warehouse A",
                    "destination": "Distribution Center",
                    "payload_weight": 2.0,
                    "priority": 3,
                    "estimated_distance_km": 10,
                    "cooperative": True,
                },
            )
            assert response.status_code == 201, response.text
            parent = response.json()
            parent_id = parent["task_id"]
            assert parent["is_parent"] is True
            assert len(parent["subtask_ids"]) == 3

            subtasks = client.get(f"/api/v1/tasks/{parent_id}/subtasks").json()
            assert len(subtasks) == 3
            by_type = {item["subtask_type"]: item for item in subtasks}

            assert by_type["pickup"]["assigned_agent_id"] == "COOP-ROBOT"
            assert by_type["transport"]["assigned_agent_id"] == "COOP-AGV"
            assert by_type["delivery"]["assigned_agent_id"] == "COOP-DRONE"
            assert all(item["negotiation_status"] == NegotiationStatus.AGREED.value for item in subtasks)
            assert all(item["status"] in (TaskStatus.ASSIGNED.value, TaskStatus.IN_PROGRESS.value, TaskStatus.COMPLETED.value) for item in subtasks)

            assert "SUBTASK_ANNOUNCEMENT" in caplog.text
            assert "[COOP-ROBOT] Received SUBTASK_ANNOUNCEMENT" in caplog.text
            assert "[COOP-AGV] Received SUBTASK_ANNOUNCEMENT" in caplog.text
            assert "[COOP-DRONE] Received SUBTASK_ANNOUNCEMENT" in caplog.text
            assert "TASK_PROPOSAL" in caplog.text
            assert "Comparing proposals" in caplog.text

            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                refreshed = client.get(f"/api/v1/tasks/{parent_id}").json()
                children = client.get(f"/api/v1/tasks/{parent_id}/subtasks").json()
                if refreshed["status"] == TaskStatus.COMPLETED.value and all(
                    child["status"] == TaskStatus.COMPLETED.value for child in children
                ):
                    break
                time.sleep(0.1)

            refreshed = client.get(f"/api/v1/tasks/{parent_id}").json()
            children = client.get(f"/api/v1/tasks/{parent_id}/subtasks").json()
            assert all(child["status"] == TaskStatus.COMPLETED.value for child in children), children
            assert refreshed["status"] == TaskStatus.COMPLETED.value
            assert "SUBTASK_COMPLETED" in caplog.text or any(
                "Completing subtask" in record.message for record in caplog.records
            )
    finally:
        for agent in reversed(started):
            agent.stop()


def test_handoff_request_negotiation_replacement_and_safety(caplog):
    caplog.set_level(logging.INFO)
    agents = [
        AgentRuntime(
            agent_id="HAND-AGV-A",
            agent_type="agv",
            capabilities=["ground_transport", "docking"],
            payload_capacity_kg=250,
            heartbeat_interval_sec=0.5,
        ),
        AgentRuntime(
            agent_id="HAND-AGV-B",
            agent_type="agv",
            capabilities=["ground_transport", "docking"],
            payload_capacity_kg=250,
            heartbeat_interval_sec=0.5,
        ),
        AgentRuntime(
            agent_id="HAND-DRONE",
            agent_type="drone",
            capabilities=["aerial_delivery"],
            payload_capacity_kg=2,
            heartbeat_interval_sec=0.5,
        ),
    ]
    # Keep the assigned agent from auto-completing before handoff.
    for agent in agents:
        agent.subtask_execution_seconds = 30.0

    started = []
    try:
        with TestClient(app) as client:
            task_coordination_service._tasks.clear()
            for agent in agents:
                assert agent.start()
                started.append(agent)
                _register(agent)

            created = client.post(
                "/api/v1/tasks",
                json={
                    "task_type": "delivery",
                    "origin": "Yard",
                    "destination": "Gate",
                    "payload_weight": 10,
                    "priority": 2,
                    "estimated_distance_km": 5,
                    "required_capabilities": ["ground_transport"],
                },
            )
            assert created.status_code == 201, created.text
            task = created.json()
            task_id = task["task_id"]
            assert task["assigned_agent_id"] == "HAND-AGV-A"

            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if agents[0].task_manager.current_task and agents[0].task_manager.current_task.task_id == task_id:
                    break
                time.sleep(0.05)
            assert agents[0].task_manager.current_task is not None
            assert agents[0].task_manager.current_task.task_id == task_id

            # Ineligible drone must stay rejected during handoff renegotiation.
            assert agents[0].request_handoff(task_id, reason="battery_thermal_limit")

            deadline = time.monotonic() + 6
            replacement = None
            while time.monotonic() < deadline:
                refreshed = client.get(f"/api/v1/tasks/{task_id}").json()
                if refreshed.get("assigned_agent_id") == "HAND-AGV-B":
                    replacement = refreshed
                    break
                time.sleep(0.1)

            assert replacement is not None, client.get(f"/api/v1/tasks/{task_id}").json()
            assert replacement["assigned_agent_id"] == "HAND-AGV-B"
            assert replacement["handoff_state"] == HandoffState.REPLACED.value
            assert replacement["handoff_from_agent_id"] == "HAND-AGV-A"
            assert agents[1].task_manager.current_task is not None
            assert agents[1].task_manager.current_task.task_id == task_id
            assert agents[0].task_manager.current_task is None
            assert "TASK_HANDOFF_REQUEST" in caplog.text
            rejections = {item["agent_id"]: item["reason"] for item in replacement["rejections"]}
            assert "HAND-DRONE" in rejections
            assert "MISSING_CAPABILITIES" in rejections["HAND-DRONE"]
            assert "HAND-AGV-A" not in {item["agent_id"] for item in replacement["proposals"]}
    finally:
        for agent in reversed(started):
            agent.stop()


def test_phase4b_single_agent_regression_still_assigns_via_mqtt(caplog):
    """Existing Phase 4B path must remain intact for non-cooperative tasks."""
    caplog.set_level(logging.INFO)
    agents = [
        AgentRuntime(
            agent_id="REG-A",
            agent_type="vehicle",
            capabilities=["ground_transport"],
            payload_capacity_kg=100,
            heartbeat_interval_sec=0.5,
        ),
        AgentRuntime(
            agent_id="REG-B",
            agent_type="vehicle",
            capabilities=["ground_transport"],
            payload_capacity_kg=100,
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
                _register(agent)

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
            assert created["is_parent"] is False
            assert created["subtask_ids"] == []
            assert created["status"] == TaskStatus.ASSIGNED.value
            assert created["assigned_agent_id"] == "REG-A"
            assert created["negotiation_status"] == NegotiationStatus.AGREED.value
            assert EventType.TASK_ANNOUNCEMENT.value in caplog.text or "[REG-A] Received TASK_ANNOUNCEMENT" in caplog.text

            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if agents[0].task_manager.current_task and agents[0].task_manager.current_task.task_id == created["task_id"]:
                    break
                time.sleep(0.05)
            assert agents[0].task_manager.current_task is not None
            assert agents[0].task_manager.current_task.task_id == created["task_id"]
    finally:
        for agent in reversed(started):
            agent.stop()
