import logging
import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from agents.runtime import AgentRuntime, OptimizationWeights
from app.main import app
from app.services.platform_registry import platform_registry_service
from app.services.task_coordination import task_coordination_service
from app.services.planner import PlanningResult, PlannerSubtask
from protocols.messages import (
    AgentRegistrationPayload,
    TaskStatus,
    NegotiationStatus,
    TaskCreate,
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


def test_rule_based_planner_fallback_creates_subtasks():
    with TestClient(app) as client:
        connection_deadline = time.monotonic() + 5
        while (
            not task_coordination_service._client.is_connected()
            and time.monotonic() < connection_deadline
        ):
            time.sleep(0.05)
        assert task_coordination_service._client.is_connected()
        task_coordination_service._tasks.clear()
        
        response = client.post(
            "/api/v1/tasks",
            json={
                "task_type": "cooperative_delivery",
                "origin": "Wh A",
                "destination": "Dist Ctr",
                "payload_weight": 5.0,
                "priority": 3,
                "estimated_distance_km": 15,
                "cooperative": True,
            },
        )
        assert response.status_code == 201
        parent = response.json()
        assert parent["is_parent"] is True
        assert len(parent["subtask_ids"]) == 3
        # Ensure Phase 5 schema fields are populated
        assert parent["plan_id"] is not None
        assert parent["reasoning_summary"] == "Deterministic rule-based planning"
        assert parent["fallback_status"] == "active"


def test_invalid_llm_planner_falls_back():
    with patch("app.services.planner.get_planner") as mock_get_planner:
        class FailingPlanner:
            failure_mode = "none"

            def plan(self, request, task_id):
                if self.failure_mode == "none":
                    return None
                if self.failure_mode == "invalid":
                    return {"invalid": "planner output"}
                raise RuntimeError("LLM planner unavailable")

        planner = FailingPlanner()
        mock_get_planner.return_value = planner
        
        with TestClient(app) as client:
            connection_deadline = time.monotonic() + 5
            while (
                not task_coordination_service._client.is_connected()
                and time.monotonic() < connection_deadline
            ):
                time.sleep(0.05)
            assert task_coordination_service._client.is_connected()

            for failure_mode in ("none", "invalid", "exception"):
                planner.failure_mode = failure_mode
                task_coordination_service._tasks.clear()
                response = client.post(
                    "/api/v1/tasks",
                    json={
                        "task_type": "cooperative_delivery",
                        "origin": "Wh B",
                        "destination": "Dist Ctr B",
                        "payload_weight": 5.0,
                        "priority": 3,
                        "estimated_distance_km": 15,
                        "cooperative": True,
                    },
                )
                assert response.status_code == 201
                parent = response.json()
                assert parent["is_parent"] is True
                assert parent["plan_id"] is not None
                assert parent["reasoning_summary"] == "Deterministic rule-based planning"
                assert parent["fallback_status"] == "active"


def test_intelligent_planner_schema_validation_and_assignment(caplog):
    caplog.set_level(logging.INFO)
    
    agent = AgentRuntime(
        agent_id="AI-ROBOT",
        agent_type="warehouse_robot",
        capabilities=["custom_picking"],
        payload_capacity_kg=30,
        heartbeat_interval_sec=0.5,
    )
    
    started = []
    try:
        with patch("app.services.planner.get_planner") as mock_get_planner:
            # Mock planner returns valid structured AI output
            class MockPlanner:
                def plan(self, request, task_id):
                    return PlanningResult(
                        plan_id=f"ai-plan-{task_id}",
                        task_id=task_id,
                        reasoning_summary="AI found an optimized path",
                        subtasks=[
                            PlannerSubtask(
                                subtask_type="ai_pickup",
                                origin=request.origin,
                                destination="Custom Staging",
                                required_capabilities=["custom_picking"],
                                estimated_distance_km=2.0,
                                description="AI planned pickup",
                                dependencies=[]
                            )
                        ],
                        estimated_cost=15.5,
                        confidence=0.95,
                        fallback_status="inactive"
                    )
            
            mock_get_planner.return_value = MockPlanner()
            
            with TestClient(app) as client:
                task_coordination_service._tasks.clear()
                assert agent.start()
                started.append(agent)
                _register(agent)

                response = client.post(
                    "/api/v1/tasks",
                    json={
                        "task_type": "delivery",
                        "origin": "Wh C",
                        "destination": "Dist Ctr C",
                        "payload_weight": 5.0,
                        "priority": 5,
                        "estimated_distance_km": 10,
                        "cooperative": True,
                    },
                )
                assert response.status_code == 201
                parent = response.json()
                assert parent["is_parent"] is True
                assert len(parent["subtask_ids"]) == 1
                assert parent["reasoning_summary"] == "AI found an optimized path"
                assert parent["estimated_cost"] == 15.5
                assert parent["confidence"] == 0.95
                assert parent["fallback_status"] == "inactive"
                
                subtasks = client.get(f"/api/v1/tasks/{parent['task_id']}/subtasks").json()
                assert len(subtasks) == 1
                assert subtasks[0]["subtask_type"] == "ai_pickup"
                assert "custom_picking" in subtasks[0]["required_capabilities"]
                assert subtasks[0]["assigned_agent_id"] == "AI-ROBOT"

    finally:
        for a in reversed(started):
            a.stop()


def test_optimization_weights_affect_proposals():
    # Agent with heavy penalty on distance
    weights_dist = OptimizationWeights(distance=0.8, workload=0.0, battery_usage=0.0, priority=0.0, deadline_feasibility=0.0, execution_time=0.0, handoffs=0.0)
    agent_dist = AgentRuntime(
        agent_id="OPT-DIST",
        agent_type="agv",
        capabilities=["transport"],
        payload_capacity_kg=100,
        optimization_weights=weights_dist
    )
    
    # Agent with no penalty on distance
    weights_flat = OptimizationWeights(distance=0.0, workload=0.0, battery_usage=0.0, priority=0.0, deadline_feasibility=0.0, execution_time=0.0, handoffs=0.0)
    agent_flat = AgentRuntime(
        agent_id="OPT-FLAT",
        agent_type="agv",
        capabilities=["transport"],
        payload_capacity_kg=100,
        optimization_weights=weights_flat
    )
    
    from protocols.messages import Task
    task_far = Task(task_id="T1", estimated_distance_km=100.0, required_capabilities=["transport"], payload_weight=10.0)
    
    prop_dist = agent_dist.calculate_task_proposal(task_far)
    prop_flat = agent_flat.calculate_task_proposal(task_far)
    
    # Distance score will be low for 100km. If distance weight is high, utility will be very low (since other weights are 0).
    # If flat, utility will be 0 (since all weights are 0).
    assert prop_dist.utility > prop_flat.utility
    
    # Let's test with a closer task
    task_close = Task(task_id="T2", estimated_distance_km=1.0, required_capabilities=["transport"], payload_weight=10.0)
    prop_dist_close = agent_dist.calculate_task_proposal(task_close)
    
    assert prop_dist_close.utility > prop_dist.utility


def test_phase4b_regression_single_task_works():
    with patch("app.services.planner.get_planner") as mock_get_planner:
        # Mock planner returns None
        from app.services.planner import PlannerProvider
        class NullPlanner(PlannerProvider):
            def plan(self, req, tid): return None
        mock_get_planner.return_value = NullPlanner()
        
        with TestClient(app) as client:
            connection_deadline = time.monotonic() + 5
            while (
                not task_coordination_service._client.is_connected()
                and time.monotonic() < connection_deadline
            ):
                time.sleep(0.05)
            assert task_coordination_service._client.is_connected()
            task_coordination_service._tasks.clear()
            response = client.post(
                "/api/v1/tasks",
                json={
                    "task_type": "delivery",
                    "origin": "A",
                    "destination": "B",
                    "payload_weight": 5.0,
                    "priority": 3,
                    "estimated_distance_km": 15,
                    "required_capabilities": ["ground"],
                    "cooperative": False,
                },
            )
            assert response.status_code == 201
            task = response.json()
            assert task["is_parent"] is False
            assert task["plan_id"] is None
