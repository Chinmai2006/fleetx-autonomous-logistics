from typing import Optional
from protocols.messages import AgentState, AgentStatus, Location, copy_model


class StateManager:
    """
    Manages agent state: battery level, 3D location, status, current task ID, and availability.
    """

    def __init__(
        self,
        battery_pct: float = 100.0,
        location: Optional[Location] = None,
        status: AgentStatus = AgentStatus.IDLE,
        is_available: bool = True,
    ):
        self._state = AgentState(
            battery_pct=battery_pct,
            location=location or Location(x=0.0, y=0.0, z=0.0),
            status=status,
            current_task_id=None,
            is_available=is_available,
        )

    @property
    def battery_pct(self) -> float:
        return self._state.battery_pct

    @property
    def location(self) -> Location:
        return self._state.location

    @property
    def status(self) -> AgentStatus:
        return self._state.status

    @property
    def current_task_id(self) -> Optional[str]:
        return self._state.current_task_id

    @property
    def is_available(self) -> bool:
        return self._state.is_available

    def update_battery(self, battery_pct: float) -> None:
        self._state.battery_pct = max(0.0, min(100.0, battery_pct))

    def update_location(self, x: float, y: float, z: float = 0.0) -> None:
        self._state.location = Location(x=x, y=y, z=z)

    def set_status(self, status: AgentStatus) -> None:
        self._state.status = status
        if status in (AgentStatus.BUSY, AgentStatus.ERROR, AgentStatus.CHARGING, AgentStatus.OFFLINE):
            self._state.is_available = False
        elif status == AgentStatus.IDLE and self._state.current_task_id is None:
            self._state.is_available = True

    def assign_task(self, task_id: str) -> None:
        self._state.current_task_id = task_id
        self._state.status = AgentStatus.BUSY
        self._state.is_available = False

    def clear_task(self) -> None:
        self._state.current_task_id = None
        self._state.status = AgentStatus.IDLE
        self._state.is_available = True

    def to_model(self) -> AgentState:
        return copy_model(self._state)
