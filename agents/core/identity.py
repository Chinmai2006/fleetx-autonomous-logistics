from typing import Any, Dict, Optional
from protocols.messages import AgentIdentity, copy_model


class AgentIdentityManager:
    """
    Manages agent identity metadata, agent ID, and type.
    """

    def __init__(self, agent_id: str, agent_type: str, metadata: Optional[Dict[str, Any]] = None):
        self._identity = AgentIdentity(
            agent_id=agent_id,
            agent_type=agent_type,
            metadata=metadata or {}
        )

    @property
    def agent_id(self) -> str:
        return self._identity.agent_id

    @property
    def agent_type(self) -> str:
        return self._identity.agent_type

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._identity.metadata

    def update_metadata(self, key: str, value: Any) -> None:
        self._identity.metadata[key] = value

    def to_model(self) -> AgentIdentity:
        return copy_model(self._identity)
