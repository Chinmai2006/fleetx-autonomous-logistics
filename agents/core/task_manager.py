import logging
from typing import Dict, Optional, List
from protocols.messages import Task, TaskStatus

logger = logging.getLogger("TaskManager")


class TaskManager:
    """
    Manages task lifecycle, assignment, status tracking, and active/historical task states.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._current_task: Optional[Task] = None
        self._task_history: Dict[str, Task] = {}

    @property
    def current_task(self) -> Optional[Task]:
        return self._current_task

    def assign_task(self, task: Task) -> bool:
        """Assign a task to this agent."""
        if self._current_task is not None and self._current_task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            logger.warning(f"Agent {self.agent_id} cannot accept task {task.task_id} while executing {self._current_task.task_id}")
            return False

        task.assigned_agent_id = self.agent_id
        task.status = TaskStatus.ASSIGNED
        self._current_task = task
        self._task_history[task.task_id] = task
        logger.info(f"Agent {self.agent_id} assigned task: {task.task_id} ({task.name or task.task_type})")
        return True

    def update_task_status(self, task_id: str, new_status: TaskStatus) -> Optional[Task]:
        """Update the status of a task."""
        task = self._task_history.get(task_id)
        if not task:
            logger.error(f"Task {task_id} not found in agent {self.agent_id} manager")
            return None

        task.status = new_status
        logger.info(f"Task {task_id} status updated to: {new_status.value}")

        if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            if self._current_task and self._current_task.task_id == task_id:
                self._current_task = None

        return task

    def unassign_current_task(self) -> Optional[Task]:
        """Unassign and clear the current task."""
        if self._current_task:
            task = self._current_task
            task.assigned_agent_id = None
            task.status = TaskStatus.PENDING
            self._current_task = None
            logger.info(f"Task {task.task_id} unassigned from agent {self.agent_id}")
            return task
        return None

    def get_task_history(self) -> List[Task]:
        return list(self._task_history.values())
