import pytest
import time
from agents.runtime import AgentRuntime
from protocols.messages import AgentStatus

@pytest.mark.integration
def test_mqtt_agent_discovery():
    """
    Test that two independent AgentRuntime instances can discover each other
    over a real MQTT broker. Requires Mosquitto running on localhost:1883.
    """
    agent1 = AgentRuntime(
        agent_id="DISC-1",
        agent_type="drone",
        capabilities=["scout"],
        mqtt_host="localhost",
        mqtt_port=1883,
        heartbeat_interval_sec=1.0,
        offline_timeout_sec=3.0,
    )
    
    agent2 = AgentRuntime(
        agent_id="DISC-2",
        agent_type="robot",
        capabilities=["transport"],
        mqtt_host="localhost",
        mqtt_port=1883,
        heartbeat_interval_sec=1.0,
        offline_timeout_sec=3.0,
    )

    try:
        # Start agents
        assert agent1.start() is True
        assert agent2.start() is True
        
        # Give them time to connect and subscribe
        time.sleep(1.0)
        
        # Rebroadcast so late joiners in this test (like agent2) get agent1's info
        agent1.register_with_network()
        agent1.advertise_capabilities()
        agent2.register_with_network()
        agent2.advertise_capabilities()
        
        # Give time for messages to be processed
        time.sleep(1.0)
        
        # Verify mutual discovery
        a1_peers = agent1.registry.get_all_agents()
        a2_peers = agent2.registry.get_all_agents()
        
        # agent1 should know about agent2
        a1_sees_a2 = next((p for p in a1_peers if p.agent_id == "DISC-2"), None)
        assert a1_sees_a2 is not None, "Agent 1 did not discover Agent 2"
        assert a1_sees_a2.agent_type == "robot"
        assert "transport" in a1_sees_a2.capabilities
        assert a1_sees_a2.status == AgentStatus.IDLE
        
        # agent2 should know about agent1
        a2_sees_a1 = next((p for p in a2_peers if p.agent_id == "DISC-1"), None)
        assert a2_sees_a1 is not None, "Agent 2 did not discover Agent 1"
        assert a2_sees_a1.agent_type == "drone"
        assert "scout" in a2_sees_a1.capabilities
        assert a2_sees_a1.status == AgentStatus.IDLE
        
        # Test offline detection
        agent1.stop()
        
        # Wait for timeout to elapse
        time.sleep(3.5)
        
        # Agent2 should mark Agent1 as offline
        a2_peers_updated = agent2.registry.get_all_agents()
        a2_sees_a1_updated = next((p for p in a2_peers_updated if p.agent_id == "DISC-1"), None)
        assert a2_sees_a1_updated is not None
        assert a2_sees_a1_updated.status == AgentStatus.OFFLINE
        
    finally:
        agent1.stop()
        agent2.stop()
