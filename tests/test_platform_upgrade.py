import os
import sys
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from agents.core.registry import AgentRegistry
from agents.runtime import AgentRuntime
from app.core.config import settings
from app.main import app
from app.services.agent_manager import DynamicAgentManager, DynamicAgentRequest
from app.services.agent_manager import ManagedAgentRecord
from app.services.analytics import PlatformAnalytics
from app.services.audit_log import AuditLog, audit_log
from app.services.decision_engine import DecisionEngine
from app.services.health_monitor import AgentHealthMonitor
from app.services.risk_engine import RiskEngine
from app.services.route_planner import RoutePlanRequest, RoutePlanner
from app.services.security import require_admin, require_role
from app.services.self_healing import SelfHealingEngine
from app.services.platform_registry import platform_registry_service
from app.services.task_coordination import task_coordination_service
from app.services.task_coordination import ProposalSafetyValidator
from protocols.messages import (
    AgentRegistrationPayload,
    AgentState,
    AgentStatus,
    Location,
    Task,
    TaskCreate,
    TaskStatus,
    TaskProposalPayload,
)


class RegistryService:
    def __init__(self):
        self.registry = AgentRegistry(offline_timeout_seconds=15)


class CoordinationService:
    def __init__(self, tasks=None):
        self.tasks = list(tasks or [])

    def list_tasks(self):
        return list(self.tasks)

    def get_task(self, task_id):
        return next((task for task in self.tasks if task.task_id == task_id), None)

    def get_subtasks(self, parent_task_id):
        return [task for task in self.tasks if task.parent_task_id == parent_task_id]


def register(registry, agent_id, capabilities, battery=100, capacity=50, status=AgentStatus.IDLE, available=True):
    return registry.registry.register_agent(
        AgentRegistrationPayload(
            agent_id=agent_id,
            agent_type="agv",
            capabilities=capabilities,
            payload_capacity_kg=capacity,
            status=status,
            initial_state=AgentState(battery_pct=battery, status=status, is_available=available),
        )
    )


def test_route_planner_uses_only_explicit_local_coordinates_or_distance():
    planner = RoutePlanner()
    route = planner.plan(RoutePlanRequest(
        origin="A",
        destination="B",
        origin_location=Location(x=0, y=0),
        waypoints=[Location(x=3, y=0)],
        destination_location=Location(x=3, y=4),
        average_speed_kph=10,
    ))
    assert route.distance_km == pytest.approx(0.007)
    assert route.distance_source == "explicit_local_coordinates_m"
    assert route.estimated_travel_time_minutes > 0
    assert "no traffic" in route.explanation
    with pytest.raises(HTTPException) as exc:
        planner.plan(RoutePlanRequest(origin="A", destination="B"))
    assert exc.value.status_code == 422


def test_decision_engine_explains_eligible_agent_factors():
    registry = RegistryService()
    coordination = CoordinationService()
    register(registry, "LOW-BATTERY", ["ground_transport"], battery=24)
    register(registry, "READY-AGV", ["ground_transport"], battery=90)
    engine = DecisionEngine(registry=registry, coordination=coordination)

    decision = engine.evaluate(TaskCreate(
        task_type="transport",
        origin="A",
        destination="B",
        required_capabilities=["ground_transport"],
        estimated_distance_km=5,
        payload_weight=10,
    ))

    assert decision.selected_agent_id == "READY-AGV"
    assert decision.route is not None and decision.route.distance_km == 5
    assert "capability match" in decision.factors
    assert next(item for item in decision.candidates if item.agent_id == "READY-AGV").eligible


def test_risk_engine_detects_low_battery_failed_task_and_deadline_risk():
    registry = RegistryService()
    risky_agent = register(registry, "RISK-AGENT", ["haul"], battery=12)
    failed_task = Task(
        task_id="RISK-TASK",
        task_type="delivery",
        assigned_agent_id=risky_agent.agent_id,
        estimated_distance_km=100,
        deadline="2020-01-01T00:00:00",
        status=TaskStatus.FAILED,
    )
    deadline_task = Task(
        task_id="DEADLINE-TASK",
        estimated_distance_km=100,
        deadline="2020-01-01T00:00:00",
        status=TaskStatus.IN_PROGRESS,
    )
    risks = RiskEngine(registry, CoordinationService([failed_task, deadline_task])).evaluate()
    conditions = {risk.condition for risk in risks}
    assert {"LOW_BATTERY", "MISSION_FAILED", "DEADLINE_RISK"}.issubset(conditions)


def test_health_monitor_reports_state_workload_and_maintenance():
    registry = RegistryService()
    agent = register(registry, "HEALTH-AGENT", ["haul"], battery=25)
    task = Task(task_id="HEALTH-TASK", assigned_agent_id=agent.agent_id, status=TaskStatus.IN_PROGRESS)
    report = AgentHealthMonitor(registry, CoordinationService([task])).inspect_all()[0]
    assert report.health == "WARNING"
    assert report.workload == 1
    assert report.task_history == 1
    assert "Recharge before another long mission" in report.recommendations


def test_self_healing_selects_only_safe_replacement_candidates():
    registry = RegistryService()
    register(registry, "FAILED-AGENT", ["bin_picking"])
    register(registry, "READY-REPLACEMENT", ["bin_picking"], battery=80, capacity=25)
    register(registry, "LOW-BATTERY-REPLACEMENT", ["bin_picking"], battery=10, capacity=25)
    register(registry, "WRONG-CAPABILITY", ["transport"], battery=90, capacity=100)
    failed = Task(
        task_id="HEAL-ST1",
        parent_task_id="HEAL-TASK",
        subtask_type="pickup",
        assigned_agent_id="FAILED-AGENT",
        required_capabilities=["bin_picking"],
        payload_weight=10,
        status=TaskStatus.FAILED,
    )

    record = SelfHealingEngine(registry).detect("HEAL-TASK", failed, "agent failed", 10)

    assert record.replacement_candidates == ["READY-REPLACEMENT"]
    assert record.recovery_status == "DETECTED"


def test_audit_log_is_structured_filterable_and_bounded():
    log = AuditLog(max_events=100)
    log.record("agent.registered", "agent added", agent_id="AUDIT-A")
    log.record("mission.completed", "task done", task_id="AUDIT-T")
    assert len(log.list_events(agent_id="AUDIT-A")) == 1
    assert log.list_events(task_id="AUDIT-T")[0].event_type == "mission.completed"


def test_analytics_uses_registry_and_task_state():
    registry = RegistryService()
    register(registry, "ANALYTICS-A", ["haul"], battery=75)
    register(registry, "ANALYTICS-B", ["haul"], battery=50, status=AgentStatus.OFFLINE, available=False)
    task = Task(task_id="ANALYTICS-T", status=TaskStatus.COMPLETED)
    analytics = PlatformAnalytics(registry, CoordinationService([task])).fleet()
    assert analytics.total_agents == 2
    assert analytics.active_agents == 1
    assert analytics.missions_completed == 1
    assert analytics.average_battery_pct == pytest.approx(62.5)


def test_dynamic_manager_supports_multiple_same_type_agents_and_archive():
    registry = RegistryService()
    manager = DynamicAgentManager(registry=registry, process_limit=3)
    process_ids = iter((1001, 1002))

    class FakeProcess:
        def __init__(self):
            self.pid = next(process_ids)
            self.returncode = None
            self.stdin = self

        def write(self, value):
            self.spec = value

        def close(self):
            return None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    with patch("app.services.agent_manager.subprocess.Popen", side_effect=lambda *args, **kwargs: FakeProcess()) as popen:
        first = manager.create(DynamicAgentRequest(
            agent_id="ROBOT-X1",
            agent_type="ROBOT",
            capabilities=["bin_picking"],
            payload_capacity_kg=30,
            battery_pct=80,
            location=Location(x=10, y=20),
        ))
        second = manager.create(DynamicAgentRequest(
            agent_id="ROBOT-X2",
            agent_type="ROBOT",
            capabilities=["bin_picking", "scanning"],
            payload_capacity_kg=40,
        ))
    assert first.agent_type == "warehouse_robot"
    assert second.process_state == "RUNNING"
    assert len(manager.list_managed()) == 2
    assert popen.call_count == 2
    assert manager.deactivate("ROBOT-X1", archive=True).archived


def test_role_authorization_requires_configured_tokens_and_enforces_admin(monkeypatch):
    monkeypatch.setattr(settings, "API_ADMIN_TOKEN", "admin-secret-test")
    monkeypatch.setattr(settings, "API_OPERATOR_TOKEN", "operator-secret-test")
    assert require_role("Bearer operator-secret-test") == "operator"
    assert require_admin("Bearer admin-secret-test") == "admin"
    with pytest.raises(HTTPException) as forbidden:
        require_admin("Bearer operator-secret-test")
    assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as unauthorized:
        require_role("Bearer wrong")
    assert unauthorized.value.status_code == 401


def test_dynamic_agent_process_registers_over_real_mqtt_and_archives():
    agent_id = f"DYNAMIC-TEST-{uuid.uuid4().hex[:8].upper()}"
    manager = DynamicAgentManager(registry=platform_registry_service, process_limit=2)
    try:
        with TestClient(app):
            deadline = time.monotonic() + 5
            while (
                (not task_coordination_service._client.is_connected()
                 or not platform_registry_service._client.is_connected())
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            assert task_coordination_service._client.is_connected()
            assert platform_registry_service._client.is_connected()
            record = manager.create(DynamicAgentRequest(
                agent_id=agent_id,
                agent_type="ROBOT",
                capabilities=["dynamic_pick", "barcode_scanning"],
                payload_capacity_kg=18,
                battery_pct=73,
                location=Location(x=14, y=22, z=0),
            ))
            assert record.process_state == "RUNNING"
            deadline = time.monotonic() + 8
            entry = None
            while time.monotonic() < deadline:
                entry = platform_registry_service.registry.get_agent(agent_id)
                if entry and "dynamic_pick" in entry.capabilities:
                    break
                time.sleep(0.1)
            assert entry is not None
            assert entry.agent_type == "warehouse_robot"
            assert entry.capabilities == ["dynamic_pick", "barcode_scanning"]
            assert entry.payload_capacity_kg == 18
            assert entry.state.battery_pct == 73
            assert entry.state.location.x == 14
            archived = manager.deactivate(agent_id, archive=True)
            assert archived.archived is True
    finally:
        manager.shutdown()


def test_authenticated_agent_uses_identity_scoped_registry_topics():
    agent = AgentRuntime(
        agent_id="AUTHENTICATED-ROBOT",
        agent_type="warehouse_robot",
        capabilities=["bin_picking"],
        payload_capacity_kg=20,
        mqtt_username="AUTHENTICATED-ROBOT",
        mqtt_password="never-log-this-secret",
    )
    sent = []

    def capture_event(event_type, payload, target_agent_id=None, topic_override=None):
        sent.append((event_type, topic_override))
        return True

    agent.send_event = capture_event
    assert agent.register_with_network()
    assert agent.advertise_capabilities()
    assert sent[0][1] == "logistics/agents/AUTHENTICATED-ROBOT/register"
    assert sent[1][1] == "logistics/agents/AUTHENTICATED-ROBOT/capabilities"


def test_runtime_and_platform_validator_enforce_operational_constraints():
    registry = RegistryService()
    entry = registry.registry.register_agent(AgentRegistrationPayload(
        agent_id="CONSTRAINED-AGV",
        agent_type="agv",
        capabilities=["ground_transport"],
        payload_capacity_kg=100,
        status=AgentStatus.IDLE,
        initial_state=AgentState(battery_pct=35, status=AgentStatus.IDLE, is_available=True),
        metadata={"operational_constraints": {"minimum_battery_pct": 40, "maximum_distance_km": 10, "excluded_task_types": ["hazmat"]}},
    ))
    runtime = AgentRuntime(
        agent_id="CONSTRAINED-LOCAL",
        agent_type="agv",
        capabilities=["ground_transport"],
        payload_capacity_kg=100,
        initial_battery_pct=35,
        operational_constraints={"minimum_battery_pct": 40, "maximum_distance_km": 10, "excluded_task_types": ["hazmat"]},
    )
    validator = ProposalSafetyValidator(registry.registry)
    task = Task(task_id="CONSTRAINT-TASK", task_type="transport", required_capabilities=["ground_transport"], estimated_distance_km=12, payload_weight=5)
    proposal = TaskProposalPayload(task_id=task.task_id, agent_id=entry.agent_id, capabilities=["ground_transport"], payload_capacity_kg=100, battery_pct=35)
    assert runtime.evaluate_task(task) == "INSUFFICIENT_BATTERY"
    assert validator.rejection_reason(task, proposal) == "INSUFFICIENT_BATTERY"
    task.task_type = "hazmat"
    proposal.battery_pct = 80
    registry.registry.update_heartbeat(entry.agent_id, AgentState(battery_pct=80, status=AgentStatus.IDLE, is_available=True), "agv")
    assert validator.rejection_reason(task, proposal) == "MAXIMUM_ROUTE_DISTANCE_EXCEEDED"
    task.estimated_distance_km = 5
    assert validator.rejection_reason(task, proposal) == "TASK_TYPE_NOT_ALLOWED"


def test_mission_analytics_uses_audit_timestamps_and_assignments():
    audit_log.clear()
    registry = RegistryService()
    parent_id = "ANALYTICS-MISSION"
    created_at = datetime.now(timezone.utc)
    parent = Task(task_id=parent_id, is_parent=True, status=TaskStatus.COMPLETED, created_at=created_at)
    child = Task(task_id=f"{parent_id}-ST1", parent_task_id=parent_id, assigned_agent_id="ANALYTICS-AGENT", status=TaskStatus.COMPLETED)
    coordination = CoordinationService([parent, child])
    audit_log.record("decision.dispatch", "candidate selected", task_id=parent_id)
    audit_log.record("mission.created", "mission created", task_id=parent_id)
    audit_log.record("assignment.confirmed", "agent acknowledged", task_id=parent_id, agent_id="ANALYTICS-AGENT")
    audit_log.record("mission.replanned", "agent unavailable", task_id=parent_id)
    audit_log.record("self_healing.handoff", "replacement accepted", task_id=parent_id)
    audit_log.record("mission.completed", "mission completed", task_id=parent_id)

    result = PlatformAnalytics(registry, coordination).mission(parent_id)

    assert result is not None
    assert result.completion_state == "COMPLETED"
    assert result.agents_involved == ["ANALYTICS-AGENT"]
    assert result.replans == 1
    assert result.handoffs == 1
    assert result.planning_time_seconds is not None
    assert result.negotiation_time_seconds is not None


def test_operations_api_reads_live_state_and_rejects_unknown_route_data():
    with TestClient(app) as client:
        route = client.post("/api/v1/routes/plan", json={"origin": "A", "destination": "B"})
        assert route.status_code == 422
        analytics = client.get("/api/v1/analytics/fleet")
        health = client.get("/api/v1/agents/health")
        risks = client.get("/api/v1/risks")
        modules = client.get("/api/v1/agentic/intelligence")
        assert analytics.status_code == 200
        assert health.status_code == 200
        assert risks.status_code == 200
        assert modules.status_code == 200
        assert len(modules.json()["modules"]) == 5


def test_agent_creation_api_requires_admin_role(monkeypatch):
    from app.services import agent_manager

    monkeypatch.setattr(settings, "API_ADMIN_TOKEN", "upgrade-admin-test")
    monkeypatch.setattr(settings, "API_OPERATOR_TOKEN", "upgrade-operator-test")
    request_body = {
        "agent_id": "API-ROBOT-NEW",
        "agent_type": "ROBOT",
        "capabilities": ["bin_picking"],
        "payload_capacity_kg": 30,
        "battery_pct": 80,
        "location": {"x": 10, "y": 20, "z": 0},
    }
    with patch.object(agent_manager.dynamic_agent_manager, "create", return_value=ManagedAgentRecord(
        agent_id="API-ROBOT-NEW",
        agent_type="warehouse_robot",
        process_id=4321,
        process_state="RUNNING",
        created_at=datetime.now(timezone.utc),
        archived=False,
    )):
        with TestClient(app) as client:
            denied = client.post("/api/v1/agents", json=request_body, headers={"Authorization": "Bearer upgrade-operator-test"})
            allowed = client.post("/api/v1/agents", json=request_body, headers={"Authorization": "Bearer upgrade-admin-test"})
            denied_mission = client.post("/api/v1/tasks", json={"origin": "A", "destination": "B"})
            denied_agentic = client.post("/api/v1/agentic/tasks", json={"origin": "A", "destination": "B", "cooperative": True})
    assert denied.status_code == 403
    assert allowed.status_code == 201
    assert allowed.json()["agent_id"] == "API-ROBOT-NEW"
    assert denied_mission.status_code == 401
    assert denied_agentic.status_code == 401
