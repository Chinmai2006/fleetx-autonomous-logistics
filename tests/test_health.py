import os
import sys
import pytest
from fastapi.testclient import TestClient

# Add backend directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.main import app

client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "health" in data


def test_health_endpoint_schema():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    
    assert "status" in data
    assert data["status"] in ["healthy", "degraded", "down"]
    assert "timestamp" in data
    assert "services" in data
    
    services = data["services"]
    assert "backend" in services
    assert "postgres" in services
    assert "redis" in services
    assert "mqtt" in services
    
    for svc_key in ["backend", "postgres", "redis", "mqtt"]:
        assert "status" in services[svc_key]


def test_health_root_alias():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "services" in data
