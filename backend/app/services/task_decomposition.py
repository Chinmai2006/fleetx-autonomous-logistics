"""
Deterministic, explainable task decomposition for Phase 4C.

No LLM / AI planning — fixed rules only.
Simple Phase 4A/4B tasks are left undecomposed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from protocols.messages import Task, TaskCreate, TaskStatus


@dataclass(frozen=True)
class DecompositionStep:
    """One explainable subtask template produced by the decomposer."""

    subtask_type: str
    origin: str
    destination: str
    required_capabilities: Sequence[str]
    estimated_distance_km: float
    description: str


# Fixed logistics pipeline for cooperative warehouse → DC deliveries.
COOPERATIVE_DELIVERY_STEPS = (
    DecompositionStep(
        subtask_type="pickup",
        origin="",  # filled from parent
        destination="",
        required_capabilities=("bin_picking",),
        estimated_distance_km=1.0,
        description="Pick payload at origin staging area",
    ),
    DecompositionStep(
        subtask_type="transport",
        origin="",
        destination="",
        required_capabilities=("ground_transport",),
        estimated_distance_km=0.0,  # uses parent distance
        description="Ground transport from origin toward destination",
    ),
    DecompositionStep(
        subtask_type="delivery",
        origin="",
        destination="",
        required_capabilities=("aerial_delivery",),
        estimated_distance_km=2.0,
        description="Final-mile aerial delivery at destination",
    ),
)


def should_decompose(request: TaskCreate) -> bool:
    """Return True only for explicitly cooperative / multi-stage tasks."""
    if request.cooperative:
        return True
    if request.task_type == "cooperative_delivery":
        return True
    if bool(request.metadata.get("cooperative")):
        return True
    return False


def decomposition_plan(request: TaskCreate) -> List[DecompositionStep]:
    """
    Build the ordered, deterministic subtask plan for a cooperative request.

    Rules (explainable):
    1. Only cooperative requests are decomposed.
    2. Delivery pipeline is always pickup → transport → delivery.
    3. Capabilities are fixed per stage so different agent types can win each stage.
    """
    if not should_decompose(request):
        return []

    parent_distance = request.estimated_distance_km if request.estimated_distance_km is not None else 10.0
    steps: List[DecompositionStep] = []
    for template in COOPERATIVE_DELIVERY_STEPS:
        if template.subtask_type == "pickup":
            steps.append(
                DecompositionStep(
                    subtask_type=template.subtask_type,
                    origin=request.origin,
                    destination=f"{request.origin} Staging",
                    required_capabilities=template.required_capabilities,
                    estimated_distance_km=template.estimated_distance_km,
                    description=template.description,
                )
            )
        elif template.subtask_type == "transport":
            steps.append(
                DecompositionStep(
                    subtask_type=template.subtask_type,
                    origin=request.origin,
                    destination=request.destination,
                    required_capabilities=template.required_capabilities,
                    estimated_distance_km=parent_distance,
                    description=template.description,
                )
            )
        else:  # delivery
            steps.append(
                DecompositionStep(
                    subtask_type=template.subtask_type,
                    origin=f"{request.destination} Apron",
                    destination=request.destination,
                    required_capabilities=template.required_capabilities,
                    estimated_distance_km=template.estimated_distance_km,
                    description=template.description,
                )
            )
    return steps


def decompose_task(parent: Task, request: TaskCreate) -> List[Task]:
    """
    Create child Task records for each decomposition step.

    Subtask IDs are deterministic given the parent task_id and step index:
    ``{parent_task_id}-ST{n}``.
    """
    plan = decomposition_plan(request)
    subtasks: List[Task] = []
    for index, step in enumerate(plan, start=1):
        subtask_id = f"{parent.task_id}-ST{index}"
        subtasks.append(
            Task(
                task_id=subtask_id,
                task_type=step.subtask_type,
                name=f"{parent.name or parent.task_type}:{step.subtask_type}",
                description=step.description,
                origin=step.origin,
                destination=step.destination,
                payload_weight=parent.payload_weight,
                priority=parent.priority,
                deadline=parent.deadline,
                estimated_distance_km=step.estimated_distance_km,
                required_capabilities=list(step.required_capabilities),
                status=TaskStatus.CREATED,
                parent_task_id=parent.task_id,
                is_parent=False,
                subtask_type=step.subtask_type,
                metadata={
                    **dict(parent.metadata),
                    "decomposition_rule": "cooperative_delivery_v1",
                    "step_index": index,
                    "step_count": len(plan),
                },
            )
        )
    return subtasks
