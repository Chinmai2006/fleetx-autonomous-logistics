from typing import List
from fastapi import APIRouter, Depends, HTTPException

from app.services.agent_manager import DynamicAgentRequest, ManagedAgentRecord, dynamic_agent_manager
from app.services.platform_registry import platform_registry_service
from app.services.security import require_admin, require_role
from app.services.health_monitor import AgentHealth, agent_health_monitor
from protocols.messages import AgentRegistryEntry

router = APIRouter()


@router.post("/agents", response_model=ManagedAgentRecord, status_code=201)
async def create_managed_agent(agent: DynamicAgentRequest, role: str = Depends(require_admin)):
    return dynamic_agent_manager.create(agent)


@router.get("/agents/managed", response_model=List[ManagedAgentRecord])
async def list_managed_agents(role: str = Depends(require_role)):
    return dynamic_agent_manager.list_managed()


@router.post("/agents/{agent_id}/activate", response_model=ManagedAgentRecord)
async def activate_managed_agent(agent_id: str, role: str = Depends(require_admin)):
    return dynamic_agent_manager.activate(agent_id)


@router.post("/agents/{agent_id}/deactivate", response_model=ManagedAgentRecord)
async def deactivate_managed_agent(agent_id: str, role: str = Depends(require_admin)):
    return dynamic_agent_manager.deactivate(agent_id)


@router.delete("/agents/{agent_id}", response_model=ManagedAgentRecord)
async def archive_managed_agent(agent_id: str, role: str = Depends(require_admin)):
    return dynamic_agent_manager.deactivate(agent_id, archive=True)


@router.get("/agents", response_model=List[AgentRegistryEntry])
async def list_agents():
    """
    Get all discovered agents registered in the platform registry (includes historical/offline).
    """
    return platform_registry_service.registry.get_all_agents()


@router.get("/agents/active-fleet", response_model=List[AgentRegistryEntry])
async def list_active_fleet():
    """
    Return only agents that are currently online (heartbeat within timeout, not OFFLINE/ERROR, not archived).
    Use this endpoint for current operational metrics; /agents returns the full historical registry.
    """
    import time as _time
    now = _time.time()
    timeout = platform_registry_service.registry.offline_timeout_seconds
    return [
        a for a in platform_registry_service.registry.get_all_agents()
        if not a.metadata.get("archived")
        and a.status.value not in ("OFFLINE", "ERROR")
        and now - a.last_seen <= timeout
    ]


@router.get("/agents/health", response_model=List[AgentHealth])
async def list_agent_health():
    return agent_health_monitor.inspect_all()


@router.get("/agents/{agent_id}", response_model=AgentRegistryEntry)
async def get_agent_by_id(agent_id: str):
    """
    Get registry details for a specific discovered agent.
    """
    agent = platform_registry_service.registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent with ID '{agent_id}' not found in registry"
        )
    return agent
