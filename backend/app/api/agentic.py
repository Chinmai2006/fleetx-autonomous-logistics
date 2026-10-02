from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.services.agentic_orchestrator import AgenticExecutionState, agentic_orchestrator
from app.services.security import require_operator_if_configured
from protocols.messages import Task, TaskCreate

router = APIRouter()


@router.post("/agentic/tasks", response_model=Task, status_code=201)
async def create_agentic_task(task: TaskCreate, role: str = Depends(require_operator_if_configured)):
    if not task.cooperative and task.task_type != "cooperative_delivery":
        raise HTTPException(status_code=422, detail="Agentic workflow requires a cooperative task")
    return agentic_orchestrator.create_task(task)


@router.get("/agentic/tasks", response_model=List[AgenticExecutionState])
async def list_agentic_tasks():
    return agentic_orchestrator.list_states()


@router.get("/agentic/tasks/{task_id}", response_model=AgenticExecutionState)
async def get_agentic_task(task_id: str):
    state = agentic_orchestrator.observe_execution(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Agentic execution '{task_id}' not found")
    return state