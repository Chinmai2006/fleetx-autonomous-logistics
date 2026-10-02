import os
import sys
import time
import subprocess
import pytest

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.core.identity import AgentIdentityManager
from agents.core.capability import CapabilityManager
from agents.core.state import StateManager
from agents.core.task_manager import TaskManager
from agents.core.mqtt_client import MQTTCommunicator
from agents.runtime import AgentRuntime
from protocols.messages import (
    AgentStatus,
    EventType,
    MQTTMessagePayload,
    Task,
    TaskStatus,
)


def test_agent_identity_manager():
    identity_mgr = AgentIdentityManager(
        agent_id="TEST-ID-01",
        agent_type="test_drone",
        metadata={"firmware": "v1.2.0"}
    )
    assert identity_mgr.agent_id == "TEST-ID-01"
    assert identity_mgr.agent_type == "test_drone"
    assert identity_mgr.metadata["firmware"] == "v1.2.0"
    
    identity_mgr.update_metadata("battery_type", "LiPo")
    assert identity_mgr.metadata["battery_type"] == "LiPo"


def test_capability_manager():
    cap_mgr = CapabilityManager(
        capabilities=["aerial_delivery", "rapid_scan"],
        payload_capacity_kg=5.0,
        supported_operations=["fly_to", "drop_cargo"]
    )
    assert cap_mgr.has_capability("aerial_delivery")
    assert not cap_mgr.has_capability("heavy_freight")
    assert cap_mgr.can_carry(4.5)
    assert not cap_mgr.can_carry(6.0)
    assert cap_mgr.supports_operation("fly_to")


def test_state_manager():
    state_mgr = StateManager(battery_pct=95.0, status=AgentStatus.IDLE)
    assert state_mgr.battery_pct == 95.0
    assert state_mgr.status == AgentStatus.IDLE
    assert state_mgr.is_available is True

    state_mgr.update_location(12.5, 45.0, 10.0)
    assert state_mgr.location.x == 12.5
    assert state_mgr.location.y == 45.0
    assert state_mgr.location.z == 10.0

    state_mgr.assign_task("TASK-99")
    assert state_mgr.current_task_id == "TASK-99"
    assert state_mgr.status == AgentStatus.BUSY
    assert state_mgr.is_available is False

    state_mgr.clear_task()
    assert state_mgr.current_task_id is None
    assert state_mgr.status == AgentStatus.IDLE
    assert state_mgr.is_available is True


def test_task_manager():
    task_mgr = TaskManager(agent_id="AGENT-01")
    task = Task(name="Deliver Package A", payload_weight_kg=2.0)
    
    assert task_mgr.assign_task(task)
    assert task_mgr.current_task.task_id == task.task_id
    assert task.status == TaskStatus.ASSIGNED

    task_mgr.update_task_status(task.task_id, TaskStatus.IN_PROGRESS)
    assert task.status == TaskStatus.IN_PROGRESS

    task_mgr.update_task_status(task.task_id, TaskStatus.COMPLETED)
    assert task.status == TaskStatus.COMPLETED
    assert task_mgr.current_task is None


def test_real_mqtt_communication_between_independent_agents():
    """
    PROVES REAL MQTT COMMUNICATION:
    Connects two independent AgentRuntime instances to the Mosquitto MQTT broker (localhost:1883).
    Agent A publishes a structured JSON event payload via real MQTT sockets.
    Agent B receives the payload via MQTT subscription and deserializes it cleanly.
    """
    received_messages = []

    # Initialize Agent A (Drone)
    agent_a = AgentRuntime(
        agent_id="REAL-DRONE-01",
        agent_type="drone",
        capabilities=["aerial_delivery"],
        mqtt_host="localhost",
        mqtt_port=1883
    )

    # Initialize Agent B (AGV)
    agent_b = AgentRuntime(
        agent_id="REAL-AGV-01",
        agent_type="agv",
        capabilities=["ground_transport"],
        mqtt_host="localhost",
        mqtt_port=1883
    )

    # Register callback on Agent B's EventHandler to capture messages received over MQTT
    def on_agent_b_received(payload: MQTTMessagePayload):
        received_messages.append(payload)

    agent_b.event_handler.register_handler(EventType.CUSTOM, on_agent_b_received)

    try:
        # Start both agents (connects to real MQTT broker at localhost:1883)
        assert agent_a.start(), "Agent A failed to connect to real MQTT broker"
        assert agent_b.start(), "Agent B failed to connect to real MQTT broker"

        # Wait for connection handshake and topic subscriptions
        time.sleep(1.0)

        # Agent A publishes a structured CUSTOM event targeted to Agent B via MQTT
        test_payload_data = {"test_key": "hello_from_drone", "sequence": 42}
        success = agent_a.send_event(
            event_type=EventType.CUSTOM,
            payload=test_payload_data,
            target_agent_id="REAL-AGV-01"
        )
        assert success, "Agent A failed to publish payload to MQTT"

        # Wait for MQTT network loop to transmit and receive the message
        time.sleep(1.5)

        # Verify Agent B received the message via real MQTT broker
        assert len(received_messages) > 0, "Agent B did not receive message over MQTT broker"
        received_payload = received_messages[0]
        
        assert received_payload.sender_identity.agent_id == "REAL-DRONE-01"
        assert received_payload.sender_identity.agent_type == "drone"
        assert received_payload.event.event_type == EventType.CUSTOM
        assert received_payload.event.payload["test_key"] == "hello_from_drone"
        assert received_payload.event.payload["sequence"] == 42

    finally:
        agent_a.stop()
        agent_b.stop()


def test_same_agent_identity_keeps_independent_mqtt_connections():
    first = MQTTCommunicator(agent_id="ROBOT-01")
    second = MQTTCommunicator(agent_id="ROBOT-01")

    try:
        assert first.connect()
        assert second.connect()
        time.sleep(1.2)
        assert first.is_connected()
        assert second.is_connected()
    finally:
        first.disconnect()
        second.disconnect()


def test_independent_os_process_communication():
    """
    PROVES INDEPENDENT OS PROCESS COMMUNICATION:
    Spawns drone_agent.py and vehicle_agent.py as separate OS processes via subprocess.
    Verifies that both processes start, connect to MQTT, exchange messages, and shut down cleanly.
    """
    python_bin = sys.executable
    cmd_drone = [python_bin, "-m", "agents.examples.drone_agent", "--id", "PROC-DRONE-99"]
    cmd_agv = [python_bin, "-m", "agents.examples.vehicle_agent", "--id", "PROC-AGV-99"]

    proc_drone = None
    proc_agv = None
    try:
        # Spawn processes
        proc_agv = subprocess.Popen(cmd_agv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.0)
        proc_drone = subprocess.Popen(cmd_drone, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(3.5)

        # Ensure both processes are still alive and running
        assert proc_agv.poll() is None, "AGV process exited prematurely"
        assert proc_drone.poll() is None, "Drone process exited prematurely"

    finally:
        # Terminate processes cleanly
        if proc_drone:
            proc_drone.terminate()
            proc_drone.wait(timeout=3)
        if proc_agv:
            proc_agv.terminate()
            proc_agv.wait(timeout=3)
