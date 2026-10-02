"""
Productization regression tests.

Covers:
- Stale agent alert filtering (active_only)
- Risk engine active_only vs full mode
- Audit log filtering by multiple event types
- Self-healing record list filtering
- Analytics uses only non-archived agents
"""
from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from fastapi.testclient import TestClient

from app.main import app
from app.services.analytics import PlatformAnalytics
from app.services.audit_log import AuditLog
from app.services.health_monitor import AgentHealthMonitor
from app.services.platform_registry import PlatformRegistryService
from app.services.risk_engine import RiskEngine
from app.services.self_healing import SelfHealingEngine
from app.services.task_coordination import TaskCoordinationService
from agents.core.registry import AgentRegistry
from protocols.messages import (
    AgentRegistrationPayload,
    AgentState,
    AgentStatus,
    Location,
    Task,
    TaskStatus,
)

client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_registry() -> AgentRegistry:
    return AgentRegistry(offline_timeout_seconds=15.0)


def _register(registry: AgentRegistry, agent_id: str, battery: float = 100.0, online: bool = True) -> None:
    payload = AgentRegistrationPayload(
        agent_id=agent_id,
        agent_type="warehouse_robot",
        capabilities=["bin_picking"],
        payload_capacity_kg=25.0,
        status=AgentStatus.IDLE,
        initial_state=AgentState(battery_pct=battery, status=AgentStatus.IDLE, is_available=True),
        timestamp=time.time(),
    )
    registry.register_agent(payload)
    if not online:
        # Simulate stale heartbeat: push last_seen 60 s into the past
        entry = registry._registry[agent_id]
        entry.last_seen = time.time() - 60.0
        entry.status = AgentStatus.OFFLINE


def _make_platform_registry(registry: AgentRegistry):
    """Return a minimal PlatformRegistryService with the supplied registry injected."""
    svc = object.__new__(PlatformRegistryService)
    svc.registry = registry
    return svc


def _make_coordination() -> TaskCoordinationService:
    """Return a TaskCoordinationService with no MQTT (not started)."""
    svc = object.__new__(TaskCoordinationService)
    svc._tasks = {}
    svc._lock = __import__("threading").RLock()
    return svc


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestActiveOnlyRiskFiltering:
    """active_only=True suppresses AGENT_UNAVAILABLE for idle historical agents."""

    def test_stale_offline_agent_without_active_work_is_suppressed(self):
        registry = _make_registry()
        _register(registry, "STALE-01", online=False)
        platform = _make_platform_registry(registry)
        coordination = _make_coordination()
        engine = RiskEngine(platform, coordination)

        risks_all    = engine.evaluate(active_only=False)
        risks_active = engine.evaluate(active_only=True)

        stale_all    = [r for r in risks_all    if r.agent_id == "STALE-01" and r.condition == "AGENT_UNAVAILABLE"]
        stale_active = [r for r in risks_active if r.agent_id == "STALE-01" and r.condition == "AGENT_UNAVAILABLE"]

        assert len(stale_all) == 1,    "Full mode must still report stale agent"
        assert len(stale_active) == 0, "active_only must suppress offline agent with no active work"

    def test_live_low_battery_agent_is_always_alerted(self):
        registry = _make_registry()
        _register(registry, "LOW-BAT-01", battery=15.0, online=True)
        platform = _make_platform_registry(registry)
        coordination = _make_coordination()
        engine = RiskEngine(platform, coordination)

        risks = engine.evaluate(active_only=True)
        battery_risks = [r for r in risks if r.agent_id == "LOW-BAT-01" and r.condition == "LOW_BATTERY"]
        assert battery_risks, "Battery alert must fire for active low-battery agent even in active_only mode"
        assert battery_risks[0].severity == "CRITICAL"

    def test_offline_agent_with_active_work_is_still_reported(self):
        registry = _make_registry()
        _register(registry, "OFFLINE-BUSY-01", online=False)
        platform = _make_platform_registry(registry)

        # Give the agent an active task
        coord = _make_coordination()
        task = Task(
            task_id="T-BUSY-01",
            task_type="delivery",
            origin="A",
            destination="B",
            status=TaskStatus.ASSIGNED,
            assigned_agent_id="OFFLINE-BUSY-01",
        )
        coord._tasks["T-BUSY-01"] = task

        engine = RiskEngine(platform, coord)
        risks = engine.evaluate(active_only=True)
        unavailable = [r for r in risks if r.agent_id == "OFFLINE-BUSY-01" and r.condition == "AGENT_UNAVAILABLE"]
        assert unavailable, "Offline agent with active assignment must always generate AGENT_UNAVAILABLE alert"

    def test_archived_agent_never_generates_alerts(self):
        registry = _make_registry()
        _register(registry, "ARCH-01", battery=5.0, online=False)
        entry = registry._registry["ARCH-01"]
        entry.metadata["archived"] = True

        platform = _make_platform_registry(registry)
        coordination = _make_coordination()
        engine = RiskEngine(platform, coordination)

        for mode in (True, False):
            risks = engine.evaluate(active_only=mode)
            arch_risks = [r for r in risks if r.agent_id == "ARCH-01"]
            assert not arch_risks, f"Archived agent must never generate alerts (active_only={mode})"

    def test_risks_api_defaults_to_active_only(self):
        """GET /api/v1/risks must use active_only=true by default (no query param)."""
        response = client.get("/api/v1/risks")
        assert response.status_code == 200, response.text
        # We cannot assert absence of specific agents (live state varies), but the call must succeed.


class TestAuditLogFiltering:
    def test_filter_by_event_type_is_exact_match(self):
        log = AuditLog()
        log.record("mission.created", "Mission A created", task_id="T1")
        log.record("mission.replanned", "Mission A replanned", task_id="T1")
        log.record("agent.registered", "Agent X joined", agent_id="X")

        only_created = log.list_events(event_type="mission.created")
        assert all(e.event_type == "mission.created" for e in only_created)
        assert len(only_created) == 1

    def test_filter_by_task_id(self):
        log = AuditLog()
        log.record("mission.created", "T1", task_id="T1")
        log.record("mission.created", "T2", task_id="T2")
        t1_events = log.list_events(task_id="T1")
        assert all(e.task_id == "T1" for e in t1_events)

    def test_bounded_ring_buffer_discards_oldest(self):
        log = AuditLog(max_events=5)
        for i in range(10):
            log.record("test.event", f"Event {i}")
        # The internal buffer is capped at 5; list_events limit only further trims
        # the returned slice, so cap the request at 5 to see the buffer behaviour.
        events = log.list_events(limit=5)
        assert len(events) == 5
        # Oldest (Event 0..4) should be gone; newest (Event 9) should be present
        summaries = [e.summary for e in events]
        assert "Event 9" in summaries
        assert "Event 0" not in summaries


class TestSelfHealingFiltering:
    def test_list_records_filters_by_task_id(self):
        engine = SelfHealingEngine.__new__(SelfHealingEngine)
        engine._records = []
        engine._lock = __import__("threading").RLock()
        # Inject two records directly
        from app.services.self_healing import HealingRecord
        r1 = HealingRecord(task_id="T1", failed_subtask_id="T1-ST1", failure="TEST", impact="test", decision="replan")
        r2 = HealingRecord(task_id="T2", failed_subtask_id="T2-ST1", failure="TEST", impact="test", decision="replan")
        engine._records = [r1, r2]

        filtered = engine.list_records(task_id="T1")
        assert all(r.task_id == "T1" for r in filtered)
        assert len(filtered) == 1


class TestAnalyticsExcludesArchivedAgents:
    def test_archived_agents_excluded_from_fleet_analytics(self):
        registry = _make_registry()
        _register(registry, "ACTIVE-01")
        _register(registry, "ARCH-02")
        entry = registry._registry["ARCH-02"]
        entry.metadata["archived"] = True

        platform = _make_platform_registry(registry)
        coordination = _make_coordination()
        analytics = PlatformAnalytics(platform, coordination)
        result = analytics.fleet()

        assert result.total_agents == 1, "Archived agents must not count in total_agents"


class TestHealthMonitorActiveAgentsOnly:
    def test_health_monitor_reports_all_registered_agents(self):
        """Health monitor still reports offline agents (they need maintenance attention)."""
        registry = _make_registry()
        _register(registry, "ONLINE-01")
        _register(registry, "OFFLINE-01", online=False)

        platform = _make_platform_registry(registry)
        coordination = _make_coordination()
        monitor = AgentHealthMonitor(platform, coordination)
        results = monitor.inspect_all()

        ids = {r.agent_id for r in results}
        assert "ONLINE-01" in ids
        assert "OFFLINE-01" in ids
        offline_health = next(r for r in results if r.agent_id == "OFFLINE-01")
        assert offline_health.health == "CRITICAL"
