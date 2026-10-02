import json
import os
import sys

# Add backend directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from fastapi.testclient import TestClient
from app.main import app
from app.services.platform_registry import platform_registry_service
from protocols.messages import (
    AgentEvent,
    AgentIdentity,
    AgentRegistrationPayload,
    AgentRegistryEntry,
    AgentState,
    AgentStatus,
    EventType,
    MQTTMessagePayload,
)

client = TestClient(app)

def test_get_agents_empty():
    # Clear registry for test isolation
    platform_registry_service.registry._registry.clear()
    
    response = client.get("/api/v1/agents")
    assert response.status_code == 200
    assert response.json() == []

def test_get_agents_populated():
    platform_registry_service.registry._registry.clear()
    
    # Inject an agent into the registry
    entry = AgentRegistryEntry(
        agent_id="API-TEST-1",
        agent_type="drone",
        capabilities=["scout"],
        status=AgentStatus.IDLE
    )
    platform_registry_service.registry._registry["API-TEST-1"] = entry
    
    response = client.get("/api/v1/agents")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["agent_id"] == "API-TEST-1"
    assert data[0]["agent_type"] == "drone"

def test_get_agent_by_id():
    response = client.get("/api/v1/agents/API-TEST-1")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "API-TEST-1"
    
def test_get_agent_by_id_not_found():
    response = client.get("/api/v1/agents/UNKNOWN-123")
    assert response.status_code == 404


def test_registry_status_message_marks_agent_offline():
    agent_id = "STATUS-TEST-1"
    platform_registry_service.registry._registry.clear()
    platform_registry_service.registry.register_agent(
        AgentRegistrationPayload(agent_id=agent_id, agent_type="drone", status=AgentStatus.IDLE)
    )
    payload = MQTTMessagePayload(
        event=AgentEvent(
            event_type=EventType.STATUS_CHANGE,
            source_agent_id=agent_id,
            payload={"status": AgentStatus.OFFLINE.value, "reason": "shutdown"},
        ),
        sender_identity=AgentIdentity(agent_id=agent_id, agent_type="drone"),
        sender_state=AgentState(status=AgentStatus.OFFLINE, is_available=False),
    )
    message = type(
        "MQTTMessage",
        (),
        {
            "topic": "logistics/registry/status",
            "payload": json.dumps(payload.model_dump()).encode("utf-8"),
        },
    )()

    platform_registry_service._on_message(None, None, message)

    assert platform_registry_service.registry.get_agent(agent_id).status == AgentStatus.OFFLINE
