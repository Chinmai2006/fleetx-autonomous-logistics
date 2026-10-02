import os
import json
import logging
from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel, Field

from app.core.config import settings
from protocols.messages import TaskCreate

logger = logging.getLogger("IntelligentPlanner")


class PlannerSubtask(BaseModel):
    subtask_type: str
    origin: str
    destination: str
    required_capabilities: List[str]
    estimated_distance_km: float
    description: str
    dependencies: List[str] = Field(default_factory=list)


class PlanningResult(BaseModel):
    plan_id: str
    task_id: str
    reasoning_summary: str
    subtasks: List[PlannerSubtask]
    dependencies: List[str] = Field(default_factory=list)
    estimated_cost: float
    confidence: float
    assumptions: str = ""
    fallback_status: str = "none"


class PlannerProvider(ABC):
    @abstractmethod
    def plan(self, request: TaskCreate, task_id: str) -> Optional[PlanningResult]:
        pass


class RuleBasedPlanner(PlannerProvider):
    def plan(self, request: TaskCreate, task_id: str) -> Optional[PlanningResult]:
        # Fallback deterministic decomposition
        from app.services.task_decomposition import decomposition_plan
        steps = decomposition_plan(request)
        if not steps:
            return None
        
        subtasks = []
        for step in steps:
            subtasks.append(PlannerSubtask(
                subtask_type=step.subtask_type,
                origin=step.origin,
                destination=step.destination,
                required_capabilities=list(step.required_capabilities),
                estimated_distance_km=step.estimated_distance_km,
                description=step.description,
                dependencies=[]
            ))
            
        return PlanningResult(
            plan_id=f"plan-{task_id}",
            task_id=task_id,
            reasoning_summary="Deterministic rule-based planning",
            subtasks=subtasks,
            dependencies=[],
            estimated_cost=0.0,
            confidence=1.0,
            fallback_status="active"
        )


class LLMPlanner(PlannerProvider):
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        
    def plan(self, request: TaskCreate, task_id: str) -> Optional[PlanningResult]:
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            logger.warning("No LLM API key, failing to rule-based.")
            return None
            
        # Optional LLM implementation...
        return None


def get_planner() -> PlannerProvider:
    if os.getenv("USE_LLM_PLANNER", "false").lower() == "true":
        return LLMPlanner()
    return RuleBasedPlanner()
