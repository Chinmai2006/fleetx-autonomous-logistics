import pytest
import time
import uuid
from typing import List

from agents.core.registry import AgentRegistry
from agents.runtime import AgentRuntime
from protocols.messages import (
    AgentRegistrationPayload,
    AgentStatus,
    AgentState,
    CapabilityAdvertisementPayload,
)

def test_registry_registration_and_update():
    registry = AgentRegistry(offline_timeout_seconds=2.0)
    agent_id = f"TEST-ROBOT-{uuid.uuid4().hex[:4]}"
    
    # 1. Registration
    reg_payload = AgentRegistrationPayload(
        agent_id=agent_id,
        agent_type="robot",
        capabilities=["transport"],
        payload_capacity_kg=10.0,
        status=AgentStatus.IDLE
    )
    
    registry.register_agent(reg_payload)
    
    agent = registry.get_agent(agent_id)
    assert agent is not None
    assert agent.agent_id == agent_id
    assert agent.agent_type == "robot"
    assert "transport" in agent.capabilities
    assert agent.status == AgentStatus.IDLE
    
    # 2. Capability Advertisement
    cap_payload = CapabilityAdvertisementPayload(
        agent_id=agent_id,
        agent_type="robot",
        capabilities=["transport", "lifting"],
        payload_capacity_kg=15.0,
        status=AgentStatus.IDLE
    )
    registry.update_capabilities(cap_payload)
    
    agent_updated = registry.get_agent(agent_id)
    assert "lifting" in agent_updated.capabilities
    assert agent_updated.payload_capacity_kg == 15.0
    
    # 3. Heartbeat Update
    new_state = AgentState(status=AgentStatus.BUSY, battery_pct=95.0)
    registry.update_heartbeat(agent_id, new_state, agent_type="robot")
    
    agent_heartbeat = registry.get_agent(agent_id)
    assert agent_heartbeat.state.battery_pct == 95.0
    assert agent_heartbeat.status == AgentStatus.BUSY
    
    # 4. Offline Detection
    time.sleep(2.1)
    newly_offline = registry.check_offline_agents()
    assert agent_id in newly_offline
    
    agent_offline = registry.get_agent(agent_id)
    assert agent_offline.status == AgentStatus.OFFLINE

def test_local_agent_offline_exclusion():
    registry = AgentRegistry(offline_timeout_seconds=0.5)
    local_id = "LOCAL-AGENT"
    peer_id = "PEER-AGENT"
    
    # Register local and peer
    registry.register_agent(AgentRegistrationPayload(agent_id=local_id, agent_type="drone", status=AgentStatus.IDLE))
    registry.register_agent(AgentRegistrationPayload(agent_id=peer_id, agent_type="drone", status=AgentStatus.IDLE))
    
    # Wait for timeout
    time.sleep(0.6)
    
    # Check offline agents, excluding the local agent
    newly_offline = registry.check_offline_agents(exclude_agent_id=local_id)
    
    assert peer_id in newly_offline, "Peer should be marked OFFLINE"
    assert local_id not in newly_offline, "Local agent should NOT be marked OFFLINE"
    
    # Verify states
    assert registry.get_agent(peer_id).status == AgentStatus.OFFLINE
    assert registry.get_agent(local_id).status == AgentStatus.IDLE


def test_runtime_offline_checker_keeps_self_online(monkeypatch):
    runtime = AgentRuntime(agent_id="LOCAL-RUNTIME", agent_type="drone")
    peer_id = "REMOTE-PEER"
    runtime.registry.register_agent(
        AgentRegistrationPayload(agent_id=peer_id, agent_type="robot", status=AgentStatus.IDLE)
    )
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 20)

    def stop_loop(_interval):
        runtime._running = False

    monkeypatch.setattr("agents.runtime.time.sleep", stop_loop)
    runtime._running = True
    runtime._offline_check_loop()

    assert runtime.registry.get_agent(runtime.agent_id).status == AgentStatus.IDLE
    assert runtime.registry.get_agent(peer_id).status == AgentStatus.OFFLINE
