import time
import uuid
from enum import Enum
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class AgentStatus(str, Enum):
    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    BUSY = "BUSY"
    CHARGING = "CHARGING"
    ERROR = "ERROR"


class TaskStatus(str, Enum):
    CREATED = "CREATED"
    ANNOUNCED = "ANNOUNCED"
    PROPOSED = "PROPOSED"
    NEGOTIATING = "NEGOTIATING"
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class HandoffState(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    NEGOTIATING = "NEGOTIATING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REPLACED = "REPLACED"


class NegotiationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    COLLECTING_PROPOSALS = "COLLECTING_PROPOSALS"
    EVALUATING = "EVALUATING"
    AGREED = "AGREED"
    NO_AGREEMENT = "NO_AGREEMENT"


class EventType(str, Enum):
    HEARTBEAT = "HEARTBEAT"
    STATUS_CHANGE = "STATUS_CHANGE"
    TASK_UPDATE = "TASK_UPDATE"
    TELEMETRY = "TELEMETRY"
    COMMAND = "COMMAND"
    CUSTOM = "CUSTOM"
    AGENT_REGISTER = "AGENT_REGISTER"
    CAPABILITY_ADVERTISEMENT = "CAPABILITY_ADVERTISEMENT"
    TASK_ANNOUNCEMENT = "TASK_ANNOUNCEMENT"
    TASK_PROPOSAL = "TASK_PROPOSAL"
    TASK_REJECT = "TASK_REJECT"
    TASK_ASSIGNMENT = "TASK_ASSIGNMENT"
    TASK_STATUS_UPDATE = "TASK_STATUS_UPDATE"
    NEGOTIATION_REQUEST = "NEGOTIATION_REQUEST"
    NEGOTIATION_RESPONSE = "NEGOTIATION_RESPONSE"
    NEGOTIATION_ACCEPT = "NEGOTIATION_ACCEPT"
    NEGOTIATION_REJECT = "NEGOTIATION_REJECT"
    # Phase 4C — cooperative multi-agent execution
    SUBTASK_ANNOUNCEMENT = "SUBTASK_ANNOUNCEMENT"
    SUBTASK_ASSIGNMENT = "SUBTASK_ASSIGNMENT"
    SUBTASK_STATUS_UPDATE = "SUBTASK_STATUS_UPDATE"
    SUBTASK_COMPLETED = "SUBTASK_COMPLETED"
    TASK_HANDOFF_REQUEST = "TASK_HANDOFF_REQUEST"
    TASK_HANDOFF_ACCEPT = "TASK_HANDOFF_ACCEPT"
    TASK_HANDOFF_REJECT = "TASK_HANDOFF_REJECT"


class Location(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class AgentIdentity(BaseModel):
    agent_id: str
    agent_type: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Capabilities(BaseModel):
    capabilities: List[str] = Field(default_factory=list)
    payload_capacity_kg: float = 0.0
    supported_operations: List[str] = Field(default_factory=list)

    def can_perform(self, required_capability: str) -> bool:
        return required_capability in self.capabilities

    def can_carry(self, weight_kg: float) -> bool:
        return self.payload_capacity_kg >= weight_kg


class AgentState(BaseModel):
    battery_pct: float = 100.0
    location: Location = Field(default_factory=Location)
    status: AgentStatus = AgentStatus.IDLE
    current_task_id: Optional[str] = None
    is_available: bool = True


class TaskProposalPayload(BaseModel):
    task_id: str
    agent_id: str
    capabilities: List[str] = Field(default_factory=list)
    payload_capacity_kg: float = 0.0
    battery_pct: float = 100.0
    available: bool = True
    capability_match: bool = True
    estimated_distance_km: float = 0.0
    estimated_cost: float = 0.0
    battery_score: float = 1.0
    capacity_score: float = 1.0
    workload_score: float = 1.0
    distance_score: float = 1.0
    priority_score: float = 0.6
    deadline_score: float = 0.5
    utility: float = 0.0
    reason: str = ""
    proposed_at: float = Field(default_factory=time.time)


class TaskRejectPayload(BaseModel):
    task_id: str
    agent_id: str
    reason: str
    rejected_at: float = Field(default_factory=time.time)


class TaskStatusUpdatePayload(BaseModel):
    task_id: str
    agent_id: str
    status: TaskStatus
    reason: Optional[str] = None
    updated_at: float = Field(default_factory=time.time)


class NegotiationResponsePayload(BaseModel):
    task_id: str
    agent_id: str
    selected_agent_id: str
    compared_agent_ids: List[str] = Field(default_factory=list)
    utility: float
    accepted: bool
    reason: str
    responded_at: float = Field(default_factory=time.time)


class NegotiationAgreementPayload(BaseModel):
    task_id: str
    selected_agent_id: str
    agreed_agent_ids: List[str] = Field(default_factory=list)
    utility: float
    agreed_at: float = Field(default_factory=time.time)


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: f"TASK-{uuid.uuid4().hex[:8].upper()}")
    task_type: str = "delivery"
    name: str = ""
    description: str = ""
    origin: str = ""
    destination: str = ""
    origin_location: Optional[Location] = None
    destination_location: Optional[Location] = None
    waypoints: List[Location] = Field(default_factory=list)
    payload_weight: float = Field(
        default=0.0,
        alias="payload_weight_kg",
        serialization_alias="payload_weight",
        ge=0,
    )
    priority: int = Field(default=3, ge=1, le=5)
    deadline: Optional[datetime] = None
    estimated_distance_km: Optional[float] = Field(default=None, ge=0)
    required_capabilities: List[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.CREATED
    assigned_agent_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    proposals: List[TaskProposalPayload] = Field(default_factory=list)
    rejections: List[TaskRejectPayload] = Field(default_factory=list)
    negotiation_status: NegotiationStatus = NegotiationStatus.NOT_STARTED
    negotiation_responses: List[NegotiationResponsePayload] = Field(default_factory=list)
    # Phase 4C — parent/subtask relationship
    parent_task_id: Optional[str] = None
    is_parent: bool = False
    subtask_ids: List[str] = Field(default_factory=list)
    subtask_type: Optional[str] = None
    handoff_state: HandoffState = HandoffState.NONE
    handoff_from_agent_id: Optional[str] = None
    handoff_reason: Optional[str] = None
    
    # Phase 5 — planning results
    plan_id: Optional[str] = None
    reasoning_summary: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    estimated_cost: Optional[float] = None
    confidence: Optional[float] = None
    fallback_status: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)

    @property
    def payload_weight_kg(self) -> float:
        return self.payload_weight

    @property
    def is_subtask(self) -> bool:
        return self.parent_task_id is not None


class NegotiationRequestPayload(BaseModel):
    task_id: str
    task: Task
    round: int = 1
    proposals: List[TaskProposalPayload] = Field(default_factory=list)
    requested_at: float = Field(default_factory=time.time)


class TaskAnnouncementPayload(BaseModel):
    task: Task


class TaskAssignmentPayload(BaseModel):
    task: Task
    assigned_agent_id: str


class SubtaskStatusUpdatePayload(BaseModel):
    subtask_id: str
    parent_task_id: str
    agent_id: str
    status: TaskStatus
    reason: Optional[str] = None
    updated_at: float = Field(default_factory=time.time)


class SubtaskCompletedPayload(BaseModel):
    subtask_id: str
    parent_task_id: str
    agent_id: str
    completed_at: float = Field(default_factory=time.time)


class TaskHandoffRequestPayload(BaseModel):
    task_id: str
    parent_task_id: Optional[str] = None
    from_agent_id: str
    reason: str
    requested_at: float = Field(default_factory=time.time)


class TaskHandoffDecisionPayload(BaseModel):
    task_id: str
    parent_task_id: Optional[str] = None
    from_agent_id: str
    to_agent_id: Optional[str] = None
    accepted: bool
    reason: str
    decided_at: float = Field(default_factory=time.time)


class TaskCreate(BaseModel):
    task_type: str = "delivery"
    name: str = ""
    description: str = ""
    origin: str
    destination: str
    origin_location: Optional[Location] = None
    destination_location: Optional[Location] = None
    waypoints: List[Location] = Field(default_factory=list)
    payload_weight: float = Field(default=0.0, alias="payload_weight_kg", ge=0)
    priority: int = Field(default=3, ge=1, le=5)
    deadline: Optional[datetime] = None
    estimated_distance_km: Optional[float] = Field(default=None, ge=0)
    required_capabilities: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    cooperative: bool = False

    model_config = ConfigDict(populate_by_name=True)


class AgentEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"EVT-{uuid.uuid4().hex[:8].upper()}")
    event_type: EventType
    source_agent_id: str
    target_agent_id: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    payload: Dict[str, Any] = Field(default_factory=dict)


class MQTTMessagePayload(BaseModel):
    event: AgentEvent
    sender_identity: AgentIdentity
    sender_state: AgentState

    def to_json(self) -> str:
        if hasattr(self, "model_dump_json"):
            return self.model_dump_json()
        return self.json()

    @classmethod
    def from_dict(cls, data: dict):
        if hasattr(cls, "model_validate"):
            return cls.model_validate(data)
        return cls.parse_obj(data)


# Phase 3: Discovery & Registration Schemas

class AgentRegistrationPayload(BaseModel):
    agent_id: str
    agent_type: str
    capabilities: List[str] = Field(default_factory=list)
    payload_capacity_kg: float = 0.0
    supported_operations: List[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    initial_state: AgentState = Field(default_factory=AgentState)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class CapabilityAdvertisementPayload(BaseModel):
    agent_id: str
    agent_type: str
    capabilities: List[str] = Field(default_factory=list)
    payload_capacity_kg: float = 0.0
    supported_operations: List[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    timestamp: float = Field(default_factory=time.time)


class AgentRegistryEntry(BaseModel):
    agent_id: str
    agent_type: str
    capabilities: List[str] = Field(default_factory=list)
    payload_capacity_kg: float = 0.0
    supported_operations: List[str] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    state: AgentState = Field(default_factory=AgentState)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    last_seen: float = Field(default_factory=time.time)
    registered_at: float = Field(default_factory=time.time)


def copy_model(model_obj):
    if hasattr(model_obj, "model_copy"):
        return model_obj.model_copy()
    return model_obj.copy()
