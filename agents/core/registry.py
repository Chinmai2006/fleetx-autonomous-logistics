import logging
import threading
import time
from typing import Dict, List, Optional

from protocols.messages import (
    AgentRegistrationPayload,
    AgentRegistryEntry,
    AgentState,
    AgentStatus,
    CapabilityAdvertisementPayload,
    copy_model,
)

logger = logging.getLogger("AgentRegistry")


class AgentRegistry:
    """
    Maintains active and known agents in the platform.
    Thread-safe storage with automatic offline timeout detection.
    """

    def __init__(self, offline_timeout_seconds: float = 15.0):
        self.offline_timeout_seconds = offline_timeout_seconds
        self._registry: Dict[str, AgentRegistryEntry] = {}
        self._lock = threading.RLock()

    def register_agent(self, payload: AgentRegistrationPayload) -> AgentRegistryEntry:
        """Register or update an agent entry from an AgentRegistrationPayload."""
        with self._lock:
            now = time.time()
            existing = self._registry.get(payload.agent_id)
            registered_at = existing.registered_at if existing else now

            entry = AgentRegistryEntry(
                agent_id=payload.agent_id,
                agent_type=payload.agent_type,
                capabilities=list(payload.capabilities),
                payload_capacity_kg=payload.payload_capacity_kg,
                supported_operations=list(payload.supported_operations),
                status=payload.status,
                state=copy_model(payload.initial_state),
                metadata=dict(payload.metadata),
                last_seen=now,
                registered_at=registered_at,
            )
            self._registry[payload.agent_id] = entry
            logger.info(f"Registry: Registered agent {payload.agent_id} ({payload.agent_type})")
            return copy_model(entry)

    def update_capabilities(self, payload: CapabilityAdvertisementPayload) -> Optional[AgentRegistryEntry]:
        """Update capability advertisement for a registered agent."""
        with self._lock:
            entry = self._registry.get(payload.agent_id)
            if not entry:
                # Auto-create basic entry if not present
                now = time.time()
                entry = AgentRegistryEntry(
                    agent_id=payload.agent_id,
                    agent_type=payload.agent_type,
                    capabilities=list(payload.capabilities),
                    payload_capacity_kg=payload.payload_capacity_kg,
                    supported_operations=list(payload.supported_operations),
                    status=payload.status,
                    last_seen=now,
                    registered_at=now,
                )
                self._registry[payload.agent_id] = entry
            else:
                entry.capabilities = list(payload.capabilities)
                entry.payload_capacity_kg = payload.payload_capacity_kg
                entry.supported_operations = list(payload.supported_operations)
                entry.last_seen = time.time()

            logger.info(f"Registry: Updated capabilities for agent {payload.agent_id}")
            return copy_model(entry)

    def update_heartbeat(
        self,
        agent_id: str,
        state: AgentState,
        agent_type: str = "unknown",
        timestamp: Optional[float] = None,
    ) -> AgentRegistryEntry:
        """Update last_seen timestamp and current state when heartbeat arrives."""
        with self._lock:
            now = timestamp or time.time()
            entry = self._registry.get(agent_id)
            if not entry:
                entry = AgentRegistryEntry(
                    agent_id=agent_id,
                    agent_type=agent_type,
                    status=state.status,
                    state=copy_model(state),
                    last_seen=now,
                    registered_at=now,
                )
                self._registry[agent_id] = entry
            else:
                entry.last_seen = now
                entry.state = copy_model(state)
                entry.status = state.status

            logger.debug(f"Registry: Updated heartbeat for {agent_id} at {now}")
            return copy_model(entry)

    def check_offline_agents(self, timeout_seconds: Optional[float] = None, exclude_agent_id: Optional[str] = None) -> List[str]:
        """Check all registered agents and mark those missing heartbeats as OFFLINE."""
        with self._lock:
            timeout = timeout_seconds if timeout_seconds is not None else self.offline_timeout_seconds
            now = time.time()
            newly_offline: List[str] = []

            for agent_id, entry in self._registry.items():
                if exclude_agent_id and agent_id == exclude_agent_id:
                    continue
                if entry.status != AgentStatus.OFFLINE:
                    if (now - entry.last_seen) > timeout:
                        entry.status = AgentStatus.OFFLINE
                        entry.state.status = AgentStatus.OFFLINE
                        entry.state.is_available = False
                        newly_offline.append(agent_id)
                        logger.warning(f"Registry: Agent {agent_id} marked OFFLINE (last seen {now - entry.last_seen:.1f}s ago)")

            return newly_offline

    def get_agent(self, agent_id: str) -> Optional[AgentRegistryEntry]:
        with self._lock:
            entry = self._registry.get(agent_id)
            return copy_model(entry) if entry else None

    def get_all_agents(self) -> List[AgentRegistryEntry]:
        with self._lock:
            return [copy_model(e) for e in self._registry.values()]

    def archive_agent(self, agent_id: str) -> Optional[AgentRegistryEntry]:
        with self._lock:
            entry = self._registry.get(agent_id)
            if entry is None:
                return None
            entry.status = AgentStatus.OFFLINE
            entry.state.status = AgentStatus.OFFLINE
            entry.state.is_available = False
            entry.metadata["archived"] = True
            return copy_model(entry)

    def get_active_agents(self) -> List[AgentRegistryEntry]:
        with self._lock:
            return [copy_model(e) for e in self._registry.values() if e.status != AgentStatus.OFFLINE]
