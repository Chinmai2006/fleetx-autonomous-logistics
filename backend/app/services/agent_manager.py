from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, SecretStr

from app.core.config import settings
from app.services.audit_log import audit_log
from app.services.platform_registry import platform_registry_service
from protocols.messages import AgentStatus, Location

AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
AGENT_TYPES = {"ROBOT": "warehouse_robot", "AGV": "agv", "DRONE": "drone"}


class DynamicAgentRequest(BaseModel):
    agent_id: str = Field(min_length=2, max_length=64)
    agent_type: str
    capabilities: List[str] = Field(min_length=1, max_length=40)
    payload_capacity_kg: float = Field(ge=0, le=100000)
    battery_pct: float = Field(default=100.0, ge=0, le=100)
    subtask_execution_seconds: float = Field(default=0.35, gt=0, le=3600)
    location: Location = Field(default_factory=Location)
    available: bool = True
    supported_operations: List[str] = Field(default_factory=list, max_length=40)
    operational_constraints: Dict[str, object] = Field(default_factory=dict)
    metadata: Dict[str, object] = Field(default_factory=dict)
    mqtt_password: Optional[SecretStr] = Field(default=None, repr=False)


class ManagedAgentRecord(BaseModel):
    agent_id: str
    agent_type: str
    process_id: Optional[int] = None
    process_state: str
    created_at: datetime
    archived: bool = False


class _ManagedAgent:
    def __init__(self, request: DynamicAgentRequest):
        self.request = request.model_copy(deep=True)
        self.process: Optional[subprocess.Popen] = None
        self.created_at = datetime.utcnow()
        self.archived = False


class DynamicAgentManager:
    """Launches independent AgentRuntime processes; registration remains MQTT-driven."""

    def __init__(self, registry=platform_registry_service, process_limit: Optional[int] = None):
        self.registry = registry
        self.process_limit = process_limit if process_limit is not None else settings.DYNAMIC_AGENT_PROCESS_LIMIT
        self._agents: Dict[str, _ManagedAgent] = {}
        self._lock = threading.RLock()

    def create(self, request: DynamicAgentRequest) -> ManagedAgentRecord:
        if not AGENT_ID_PATTERN.fullmatch(request.agent_id):
            raise HTTPException(status_code=422, detail="agent_id may contain letters, digits, dot, underscore, and hyphen")
        agent_type = request.agent_type.strip().upper()
        if agent_type not in AGENT_TYPES:
            raise HTTPException(status_code=422, detail="agent_type must be ROBOT, AGV, or DRONE")
        normalized = request.model_copy(update={"agent_type": AGENT_TYPES[agent_type]})

        with self._lock:
            current = self._agents.get(normalized.agent_id)
            if current and current.process and current.process.poll() is None:
                raise HTTPException(status_code=409, detail=f"Agent '{normalized.agent_id}' is already managed")
            registered = self.registry.registry.get_agent(normalized.agent_id)
            if registered and not registered.metadata.get("archived", False):
                raise HTTPException(status_code=409, detail=f"Agent '{normalized.agent_id}' is already registered")
            running = sum(item.process is not None and item.process.poll() is None for item in self._agents.values())
            if running >= self.process_limit:
                raise HTTPException(status_code=503, detail="Managed agent process capacity reached")
            managed = current or _ManagedAgent(normalized)
            managed.request = normalized
            managed.archived = False
            managed.process = self._launch(normalized)
            self._agents[normalized.agent_id] = managed

        audit_log.record(
            event_type="agent.registered",
            actor="admin",
            agent_id=normalized.agent_id,
            summary=f"Started {agent_type} agent through independent runtime process",
            details={"capability_count": len(normalized.capabilities), "payload_capacity_kg": normalized.payload_capacity_kg},
        )
        return self._record(normalized.agent_id, managed)

    def list_managed(self) -> List[ManagedAgentRecord]:
        with self._lock:
            return [self._record(agent_id, agent) for agent_id, agent in self._agents.items()]

    def activate(self, agent_id: str) -> ManagedAgentRecord:
        with self._lock:
            managed = self._agents.get(agent_id)
            if managed is None:
                raise HTTPException(status_code=404, detail=f"Managed agent '{agent_id}' not found")
            if managed.process and managed.process.poll() is None:
                return self._record(agent_id, managed)
            if managed.archived:
                raise HTTPException(status_code=409, detail="Archived agents must be re-created with a new identity")
            managed.process = self._launch(managed.request)
        audit_log.record("agent.activated", f"Activated managed agent {agent_id}", actor="admin", agent_id=agent_id)
        return self._record(agent_id, managed)

    def deactivate(self, agent_id: str, archive: bool = False) -> ManagedAgentRecord:
        with self._lock:
            managed = self._agents.get(agent_id)
            if managed is None:
                raise HTTPException(status_code=404, detail=f"Managed agent '{agent_id}' not found")
            process = managed.process
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            managed.process = process
            managed.archived = managed.archived or archive
        if archive:
            self.registry.registry.archive_agent(agent_id)
        audit_log.record(
            event_type="agent.archived" if archive else "agent.deactivated",
            actor="admin",
            agent_id=agent_id,
            result="completed",
            summary=f"{'Archived' if archive else 'Deactivated'} managed agent {agent_id}",
        )
        return self._record(agent_id, managed)

    def shutdown(self) -> None:
        with self._lock:
            agent_ids = list(self._agents)
        for agent_id in agent_ids:
            try:
                self.deactivate(agent_id)
            except HTTPException:
                continue

    def _launch(self, request: DynamicAgentRequest) -> subprocess.Popen:
        spec = request.model_dump(mode="json", exclude={"mqtt_password"})
        spec["mqtt_host"] = settings.MQTT_BROKER_HOST
        spec["mqtt_port"] = settings.MQTT_BROKER_PORT
        if settings.MQTT_USERNAME and not request.mqtt_password:
            raise HTTPException(status_code=422, detail="A per-agent MQTT password is required when broker authentication is enabled")
        spec["mqtt_username"] = request.agent_id if request.mqtt_password else ""
        spec["mqtt_password"] = request.mqtt_password.get_secret_value() if request.mqtt_password else ""
        spec["mqtt_tls_ca_cert"] = settings.MQTT_TLS_CA_CERT or None
        spec["mqtt_tls_certfile"] = settings.MQTT_TLS_CERTFILE or None
        spec["mqtt_tls_keyfile"] = settings.MQTT_TLS_KEYFILE or None
        root = next(
            parent
            for parent in Path(__file__).resolve().parents
            if (parent / "agents").is_dir() and (parent / "protocols").is_dir()
        )
        environment = os.environ.copy()
        current_path = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = str(root) + (os.pathsep + current_path if current_path else "")
        process = subprocess.Popen(
            [sys.executable, "-m", "agents.dynamic_agent", "--spec-stdin"],
            cwd=root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=None,
            stderr=None,
        )
        if process.stdin:
            process.stdin.write((json.dumps(spec) + "\n").encode("utf-8"))
            process.stdin.close()
        return process

    @staticmethod
    def _record(agent_id: str, managed: _ManagedAgent) -> ManagedAgentRecord:
        process = managed.process
        process_state = "RUNNING" if process and process.poll() is None else "STOPPED"
        return ManagedAgentRecord(
            agent_id=agent_id,
            agent_type=managed.request.agent_type,
            process_id=process.pid if process else None,
            process_state=process_state,
            created_at=managed.created_at,
            archived=managed.archived,
        )


dynamic_agent_manager = DynamicAgentManager()