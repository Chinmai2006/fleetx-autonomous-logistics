from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.services.task_coordination import task_coordination_service
from app.services.security import require_operator_if_configured
from protocols.messages import Task, TaskCreate

router = APIRouter()


@router.post("/tasks", response_model=Task, status_code=201)
async def create_task(task: TaskCreate, role: str = Depends(require_operator_if_configured)):
    return task_coordination_service.create_task(task)


@router.get("/tasks", response_model=List[Task])
async def list_tasks():
    return task_coordination_service.list_tasks()


@router.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str):
    task = task_coordination_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return task


@router.get("/tasks/{task_id}/subtasks", response_model=List[Task])
async def get_subtasks(task_id: str):
    parent = task_coordination_service.get_task(task_id)
    if not parent:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return task_coordination_service.get_subtasks(task_id)
