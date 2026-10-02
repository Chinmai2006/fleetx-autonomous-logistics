import logging
import os
import signal
import sys
import threading
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from agents.core.capability import CapabilityManager
from agents.core.event_handler import EventHandler
from agents.core.identity import AgentIdentityManager
from agents.core.mqtt_client import MQTTCommunicator
from agents.core.registry import AgentRegistry
from agents.core.state import StateManager
from agents.core.task_manager import TaskManager

from protocols.messages import (
    AgentEvent,
    AgentRegistrationPayload,
    AgentStatus,
    CapabilityAdvertisementPayload,
    EventType,
    MQTTMessagePayload,
    NegotiationAgreementPayload,
    NegotiationRequestPayload,
    NegotiationResponsePayload,
    SubtaskCompletedPayload,
    SubtaskStatusUpdatePayload,
    Task,
    TaskAssignmentPayload,
    TaskAnnouncementPayload,
    TaskHandoffRequestPayload,
    TaskProposalPayload,
    TaskRejectPayload,
    TaskStatus,
    TaskStatusUpdatePayload,
    Location,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(threadName)s): %(message)s"
)
logger = logging.getLogger("AgentRuntime")


def _parse_model(cls, data: dict):
    """Pydantic v1/v2 compatible model parsing."""
    if hasattr(cls, "model_validate"):
        return cls.model_validate(data)
    return cls.parse_obj(data)


class OptimizationWeights(BaseModel):
    distance: float = 0.25
    execution_time: float = 0.10
    battery_usage: float = 0.15
    workload: float = 0.15
    handoffs: float = 0.10
    priority: float = 0.15
    deadline_feasibility: float = 0.10

class AgentRuntime:
    """
    Common Agent Runtime unifying identity, capability, state, registry, MQTT messaging, event routing, and task management.
    Runs as an independent OS process.
    """

    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        capabilities: Optional[List[str]] = None,
        payload_capacity_kg: float = 0.0,
        supported_operations: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        heartbeat_interval_sec: float = 5.0,
        offline_timeout_sec: float = 15.0,
        optimization_weights: Optional[OptimizationWeights] = None,
        initial_battery_pct: float = 100.0,
        initial_location: Optional[Location] = None,
        initial_available: bool = True,
        operational_constraints: Optional[Dict[str, Any]] = None,
        mqtt_username: Optional[str] = None,
        mqtt_password: Optional[str] = None,
        mqtt_tls_ca_cert: Optional[str] = None,
        mqtt_tls_certfile: Optional[str] = None,
        mqtt_tls_keyfile: Optional[str] = None,
    ):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        if mqtt_username is None:
            mqtt_username = os.getenv("MQTT_USERNAME")
        if mqtt_password is None:
            mqtt_password = os.getenv("MQTT_PASSWORD")
        mqtt_tls_ca_cert = mqtt_tls_ca_cert or os.getenv("MQTT_TLS_CA_CERT")
        mqtt_tls_certfile = mqtt_tls_certfile or os.getenv("MQTT_TLS_CERTFILE")
        mqtt_tls_keyfile = mqtt_tls_keyfile or os.getenv("MQTT_TLS_KEYFILE")
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.offline_timeout_sec = offline_timeout_sec
        self.optimization_weights = optimization_weights or OptimizationWeights()
        self.operational_constraints = dict(operational_constraints or {})

        # 1. Identity Manager
        self.identity = AgentIdentityManager(
            agent_id=agent_id,
            agent_type=agent_type,
            metadata=metadata
        )

        # 2. Capability Manager
        self.capability = CapabilityManager(
            capabilities=capabilities,
            payload_capacity_kg=payload_capacity_kg,
            supported_operations=supported_operations
        )

        # 3. State Manager
        self.state = StateManager(
            battery_pct=initial_battery_pct,
            location=initial_location,
            status=AgentStatus.IDLE,
            is_available=initial_available
        )

        # 4. MQTT Communicator
        self.mqtt = MQTTCommunicator(
            agent_id=agent_id,
            host=mqtt_host,
            port=mqtt_port,
            username=mqtt_username,
            password=mqtt_password,
            tls_ca_cert=mqtt_tls_ca_cert,
            tls_certfile=mqtt_tls_certfile,
            tls_keyfile=mqtt_tls_keyfile,
        )

        # 5. Event Handler
        self.event_handler = EventHandler()

        # 6. Task Manager
        self.task_manager = TaskManager(agent_id=agent_id)

        # 7. Agent Registry (Phase 3 Discovery & Peer Tracking)
        self.registry = AgentRegistry(offline_timeout_seconds=offline_timeout_sec)

        # Self registration in local registry
        self.registry.register_agent(
            AgentRegistrationPayload(
                agent_id=agent_id,
                agent_type=agent_type,
                capabilities=self.capability.capabilities,
                payload_capacity_kg=self.capability.payload_capacity_kg,
                supported_operations=self.capability.supported_operations,
                status=self.state.status,
                initial_state=self.state.to_model(),
                metadata=self.identity.metadata,
                timestamp=time.time()
            )
        )

        # Control flags & threading
        self._running = False
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._offline_check_thread: Optional[threading.Thread] = None
        self._proposal_lock = threading.RLock()
        self._peer_proposals: Dict[str, Dict[str, TaskProposalPayload]] = {}
        self._execution_timers: Dict[str, threading.Timer] = {}
        self.subtask_execution_seconds = 0.35

        # Internal registration
        self.mqtt.register_on_payload_received(self._on_mqtt_message_received)
        self.event_handler.register_handler(EventType.HEARTBEAT, self._handle_heartbeat)
        self.event_handler.register_handler(EventType.AGENT_REGISTER, self._handle_peer_registration)
        self.event_handler.register_handler(EventType.CAPABILITY_ADVERTISEMENT, self._handle_peer_capabilities)
        self.event_handler.register_handler(EventType.TASK_ANNOUNCEMENT, self._handle_task_announcement)
        self.event_handler.register_handler(EventType.SUBTASK_ANNOUNCEMENT, self._handle_task_announcement)
        self.event_handler.register_handler(EventType.TASK_PROPOSAL, self._handle_peer_task_proposal)
        self.event_handler.register_handler(EventType.NEGOTIATION_REQUEST, self._handle_negotiation_request)
        self.event_handler.register_handler(EventType.NEGOTIATION_ACCEPT, self._handle_negotiation_accept)
        self.event_handler.register_handler(EventType.NEGOTIATION_REJECT, self._handle_negotiation_reject)
        self.event_handler.register_handler(EventType.TASK_ASSIGNMENT, self._handle_task_assignment)
        self.event_handler.register_handler(EventType.SUBTASK_ASSIGNMENT, self._handle_task_assignment)

    def start(self) -> bool:
        """Start the agent runtime: connect MQTT, subscribe topics, announce registration & capabilities, start loops."""
        if self._running:
            logger.warning(f"AgentRuntime {self.agent_id} is already running.")
            return True

        logger.info(f"Initializing AgentRuntime for {self.agent_id} ({self.agent_type})...")

        # Connect to MQTT broker
        if not self.mqtt.connect():
            logger.error(f"AgentRuntime {self.agent_id} failed to connect to MQTT broker at {self.mqtt_host}:{self.mqtt_port}")
            return False

        # Wait briefly for connection handshake
        time.sleep(0.5)

        # Subscribe to agent-specific, broadcast, and registry topics
        self.mqtt.subscribe(f"logistics/agents/{self.agent_id}/#")
        self.mqtt.subscribe("logistics/broadcast/#")
        if self.mqtt.username == self.agent_id:
            for topic in (
                "logistics/agents/+/register",
                "logistics/agents/+/capabilities",
                "logistics/agents/+/proposals/#",
                "logistics/agents/+/negotiation/responses/#",
            ):
                self.mqtt.subscribe(topic)
        else:
            self.mqtt.subscribe("logistics/registry/#")

        self._running = True

        # Phase 3: Announce registration & advertise capabilities to network
        self.register_with_network()
        self.advertise_capabilities()

        # Start periodic heartbeat thread
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"Heartbeat-{self.agent_id}",
            daemon=True
        )
        self._heartbeat_thread.start()

        # Start periodic offline checker thread
        self._offline_check_thread = threading.Thread(
            target=self._offline_check_loop,
            name=f"OfflineCheck-{self.agent_id}",
            daemon=True
        )
        self._offline_check_thread.start()

        # Register signal handlers for graceful shutdown if running in main thread
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (ValueError, AttributeError):
            pass

        logger.info(f"AgentRuntime {self.agent_id} successfully started and discoverable.")
        return True

    def stop(self) -> None:
        """Gracefully shut down the agent runtime."""
        if not self._running:
            return

        logger.info(f"Shutting down AgentRuntime for {self.agent_id}...")
        self._running = False

        # Update status to OFFLINE and send final state notification
        self.state.set_status(AgentStatus.OFFLINE)
        self.send_event(
            EventType.STATUS_CHANGE,
            {"status": AgentStatus.OFFLINE.value, "reason": "shutdown"}
        )

        # Publish final offline status to registry channel
        self.send_event(
            EventType.STATUS_CHANGE,
            {"status": AgentStatus.OFFLINE.value, "agent_id": self.agent_id},
            topic_override=(
                f"logistics/agents/{self.agent_id}/heartbeat"
                if self.mqtt.username == self.agent_id
                else "logistics/registry/status"
            ),
        )

        # Disconnect MQTT
        self.mqtt.disconnect()
        logger.info(f"AgentRuntime {self.agent_id} shutdown complete.")

    def register_with_network(self) -> bool:
        """Publish AgentRegistrationPayload to logistics/registry/register."""
        payload = AgentRegistrationPayload(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            capabilities=self.capability.capabilities,
            payload_capacity_kg=self.capability.payload_capacity_kg,
            supported_operations=self.capability.supported_operations,
            status=self.state.status,
            initial_state=self.state.to_model(),
            metadata=self.identity.metadata,
            timestamp=time.time()
        )
        registry_topic = (
            f"logistics/agents/{self.agent_id}/register"
            if self.mqtt.username == self.agent_id
            else "logistics/registry/register"
        )
        return self.send_event(
            EventType.AGENT_REGISTER,
            payload.model_dump() if hasattr(payload, "model_dump") else payload.dict(),
            topic_override=registry_topic
        )

    def advertise_capabilities(self) -> bool:
        """Publish CapabilityAdvertisementPayload to logistics/registry/capabilities."""
        payload = CapabilityAdvertisementPayload(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            capabilities=self.capability.capabilities,
            payload_capacity_kg=self.capability.payload_capacity_kg,
            supported_operations=self.capability.supported_operations,
            status=self.state.status,
            timestamp=time.time()
        )
        capability_topic = (
            f"logistics/agents/{self.agent_id}/capabilities"
            if self.mqtt.username == self.agent_id
            else "logistics/registry/capabilities"
        )
        return self.send_event(
            EventType.CAPABILITY_ADVERTISEMENT,
            payload.model_dump() if hasattr(payload, "model_dump") else payload.dict(),
            topic_override=capability_topic
        )

    def send_event(
        self,
        event_type: EventType,
        payload: Optional[Dict[str, Any]] = None,
        target_agent_id: Optional[str] = None,
        topic_override: Optional[str] = None
    ) -> bool:
        """Construct and publish a structured JSON event over MQTT."""
        event = AgentEvent(
            event_type=event_type,
            source_agent_id=self.agent_id,
            target_agent_id=target_agent_id,
            payload=payload or {}
        )

        message_payload = MQTTMessagePayload(
            event=event,
            sender_identity=self.identity.to_model(),
            sender_state=self.state.to_model()
        )

        if topic_override:
            topic = topic_override
        elif target_agent_id:
            topic = f"logistics/agents/{target_agent_id}/events"
        else:
            topic = f"logistics/broadcast/all"

        if self.mqtt.username == self.agent_id and topic.startswith("logistics/"):
            parts = topic.split("/")
            if topic == "logistics/registry/register":
                topic = f"logistics/agents/{self.agent_id}/register"
            elif topic == "logistics/registry/capabilities":
                topic = f"logistics/agents/{self.agent_id}/capabilities"
            elif topic in ("logistics/registry/heartbeat", f"logistics/agents/{self.agent_id}/heartbeat"):
                topic = f"logistics/agents/{self.agent_id}/heartbeat"
            elif topic == "logistics/registry/status":
                topic = f"logistics/agents/{self.agent_id}/heartbeat"
            elif topic == "logistics/tasks/responses":
                topic = f"logistics/agents/{self.agent_id}/responses"
            elif len(parts) == 5 and parts[:3] == ["logistics", "broadcast", "negotiation"] and parts[3] == "proposals":
                topic = f"logistics/agents/{self.agent_id}/proposals/{parts[4]}"
            elif len(parts) == 5 and parts[:3] == ["logistics", "broadcast", "negotiation"] and parts[3] == "responses":
                topic = f"logistics/agents/{self.agent_id}/negotiation/responses/{parts[4]}"
            elif len(parts) == 4 and parts[:3] == ["logistics", "broadcast", "handoff"]:
                topic = f"logistics/agents/{self.agent_id}/handoff/{parts[3]}"
            elif topic.startswith("logistics/broadcast/"):
                topic = f"logistics/agents/{self.agent_id}/events"

        return self.mqtt.publish_payload(topic, message_payload)

    def send_heartbeat(self) -> bool:
        """Publish heartbeat message to logistics/registry/heartbeat and agent heartbeat topic."""
        event = AgentEvent(
            event_type=EventType.HEARTBEAT,
            source_agent_id=self.agent_id,
            payload={"heartbeat_seq": int(time.time()), "timestamp": time.time()}
        )
        message_payload = MQTTMessagePayload(
            event=event,
            sender_identity=self.identity.to_model(),
            sender_state=self.state.to_model()
        )
        
        # Publish to registry heartbeat channel
        if self.mqtt.username == self.agent_id:
            return self.mqtt.publish_payload(f"logistics/agents/{self.agent_id}/heartbeat", message_payload)
        res1 = self.mqtt.publish_payload("logistics/registry/heartbeat", message_payload)
        res2 = self.mqtt.publish_payload(f"logistics/agents/{self.agent_id}/heartbeat", message_payload)
        return res1 or res2

    def assign_task(self, task: Task) -> bool:
        """Assign task to agent and update state & task manager."""
        if self.task_manager.assign_task(task):
            self.state.assign_task(task.task_id)
            self.send_event(EventType.TASK_UPDATE, {"task_id": task.task_id, "status": TaskStatus.ASSIGNED.value})
            return True
        return False

    def update_task_status(self, task_id: str, new_status: TaskStatus) -> None:
        """Update active task status and notify network."""
        updated = self.task_manager.update_task_status(task_id, new_status)
        if updated:
            if new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                self.state.clear_task()
                self._cancel_execution_timer(task_id)
            status_update = TaskStatusUpdatePayload(
                task_id=task_id,
                agent_id=self.agent_id,
                status=new_status,
            )
            self.send_event(
                EventType.TASK_STATUS_UPDATE,
                status_update.model_dump() if hasattr(status_update, "model_dump") else status_update.dict(),
                topic_override="logistics/tasks/responses",
            )
            if updated.is_subtask:
                sub_update = SubtaskStatusUpdatePayload(
                    subtask_id=task_id,
                    parent_task_id=updated.parent_task_id or "",
                    agent_id=self.agent_id,
                    status=new_status,
                )
                self.send_event(
                    EventType.SUBTASK_STATUS_UPDATE,
                    sub_update.model_dump(),
                    topic_override="logistics/tasks/responses",
                )
                self.send_event(
                    EventType.SUBTASK_STATUS_UPDATE,
                    sub_update.model_dump(),
                    topic_override=f"logistics/broadcast/subtasks/{task_id}",
                )
                if new_status == TaskStatus.COMPLETED:
                    completed = SubtaskCompletedPayload(
                        subtask_id=task_id,
                        parent_task_id=updated.parent_task_id or "",
                        agent_id=self.agent_id,
                    )
                    self.send_event(
                        EventType.SUBTASK_COMPLETED,
                        completed.model_dump(),
                        topic_override="logistics/tasks/responses",
                    )
                    self.send_event(
                        EventType.SUBTASK_COMPLETED,
                        completed.model_dump(),
                        topic_override=f"logistics/broadcast/subtasks/{task_id}",
                    )

    def request_handoff(self, task_id: str, reason: str = "unable_to_continue") -> bool:
        """Publish a deterministic handoff request and free local assignment."""
        task = self.task_manager.current_task
        if not task or task.task_id != task_id:
            logger.warning("[%s] Cannot handoff %s — not current task", self.agent_id, task_id)
            return False

        self._cancel_execution_timer(task_id)
        handoff = TaskHandoffRequestPayload(
            task_id=task_id,
            parent_task_id=task.parent_task_id,
            from_agent_id=self.agent_id,
            reason=reason,
        )
        if self.mqtt.username == self.agent_id:
            published = self.send_event(
                EventType.TASK_HANDOFF_REQUEST,
                handoff.model_dump(),
                topic_override=f"logistics/broadcast/handoff/{task_id}",
            )
        else:
            published = self.send_event(
                EventType.TASK_HANDOFF_REQUEST,
                handoff.model_dump(),
                topic_override=f"logistics/broadcast/handoff/{task_id}",
            )
            self.send_event(
                EventType.TASK_HANDOFF_REQUEST,
                handoff.model_dump(),
                topic_override="logistics/tasks/responses",
            )
        self.task_manager.unassign_current_task()
        self.state.clear_task()
        self.state.set_status(AgentStatus.IDLE)
        logger.info("[%s] TASK_HANDOFF_REQUEST for %s reason=%s", self.agent_id, task_id, reason)
        return published

    def _cancel_execution_timer(self, task_id: str) -> None:
        timer = self._execution_timers.pop(task_id, None)
        if timer is not None:
            timer.cancel()

    def _schedule_subtask_completion(self, task: Task) -> None:
        """Deterministic short execution for cooperative subtasks only."""
        if not task.is_subtask:
            return

        self._cancel_execution_timer(task.task_id)

        def _complete() -> None:
            current = self.task_manager.current_task
            if not current or current.task_id != task.task_id:
                return
            logger.info("[%s] Completing subtask %s", self.agent_id, task.task_id)
            self.update_task_status(task.task_id, TaskStatus.COMPLETED)

        timer = threading.Timer(self.subtask_execution_seconds, _complete)
        timer.daemon = True
        self._execution_timers[task.task_id] = timer
        timer.start()

    def evaluate_task(self, task: Task) -> Optional[str]:
        """Return a deterministic rejection reason, or None when this agent can perform the task."""
        if not self.state.is_available or self.state.status != AgentStatus.IDLE:
            return "AGENT_UNAVAILABLE"
        minimum_battery_pct = float(self.operational_constraints.get("minimum_battery_pct", 20.0))
        if self.state.battery_pct < minimum_battery_pct:
            return "INSUFFICIENT_BATTERY"
        maximum_distance_km = self.operational_constraints.get("maximum_distance_km")
        if maximum_distance_km is not None and (task.estimated_distance_km or 0.0) > float(maximum_distance_km):
            return "MAXIMUM_ROUTE_DISTANCE_EXCEEDED"
        excluded_task_types = self.operational_constraints.get("excluded_task_types", [])
        if task.task_type in excluded_task_types:
            return "TASK_TYPE_NOT_ALLOWED"
        if task.deadline and task.deadline.timestamp() <= time.time():
            return "DEADLINE_EXPIRED"
        missing = sorted(set(task.required_capabilities) - set(self.capability.capabilities))
        if missing:
            return "MISSING_CAPABILITIES:" + ",".join(missing)
        if not self.capability.can_carry(task.payload_weight):
            return "PAYLOAD_CAPACITY_EXCEEDED"
        return None

    def calculate_task_proposal(self, task: Task) -> TaskProposalPayload:
        """Calculate a deterministic, explainable utility from this agent's local state."""
        capability_match = set(task.required_capabilities).issubset(self.capability.capabilities)
        capacity_score = max(
            0.0,
            min(
                1.0,
                (self.capability.payload_capacity_kg - task.payload_weight)
                / max(self.capability.payload_capacity_kg, 1.0),
            ),
        )
        battery_score = max(0.0, min(1.0, self.state.battery_pct / 100.0))
        workload_score = 1.0 if self.state.is_available and self.task_manager.current_task is None else 0.0
        distance_km = task.estimated_distance_km or 0.0
        distance_score = 1.0 / (1.0 + distance_km / 10.0)
        
        # execution time depends on distance and operations
        execution_time = distance_km * 2.0 + len(task.required_capabilities)
        execution_time_score = 1.0 / (1.0 + execution_time / 20.0)
        
        handoffs_score = 1.0 if task.handoff_state == "NONE" else 0.5
        priority_score = task.priority / 5.0
        if task.deadline:
            hours_remaining = max(0.0, (task.deadline.timestamp() - time.time()) / 3600.0)
            deadline_score = max(0.0, min(1.0, 1.0 - hours_remaining / 72.0))
        else:
            deadline_score = 0.5

        utility = (
            self.optimization_weights.battery_usage * battery_score
            + self.optimization_weights.workload * workload_score
            + self.optimization_weights.distance * distance_score
            + self.optimization_weights.priority * priority_score
            + self.optimization_weights.deadline_feasibility * deadline_score
            + self.optimization_weights.execution_time * execution_time_score
            + self.optimization_weights.handoffs * handoffs_score
        )
        estimated_cost = (
            distance_km
            + 10.0 * (1.0 - battery_score)
            + 10.0 * (1.0 - capacity_score)
            + 10.0 * (1.0 - workload_score)
            + 5.0 * (1.0 - priority_score)
            + 5.0 * (1.0 - deadline_score)
        )
        reason = (
            f"capabilities=match,battery={self.state.battery_pct:.0f}%,"
            f"payload_headroom={self.capability.payload_capacity_kg - task.payload_weight:.1f}kg,"
            f"distance={distance_km:.1f}km,priority={task.priority}"
        )
        return TaskProposalPayload(
            task_id=task.task_id,
            agent_id=self.agent_id,
            capabilities=list(self.capability.capabilities),
            payload_capacity_kg=self.capability.payload_capacity_kg,
            battery_pct=self.state.battery_pct,
            available=self.state.is_available,
            capability_match=capability_match,
            estimated_distance_km=distance_km,
            estimated_cost=estimated_cost,
            battery_score=battery_score,
            capacity_score=capacity_score,
            workload_score=workload_score,
            distance_score=distance_score,
            priority_score=priority_score,
            deadline_score=deadline_score,
            utility=utility,
            reason=reason,
        )

    def _handle_task_announcement(self, payload: MQTTMessagePayload) -> None:
        try:
            announcement = _parse_model(TaskAnnouncementPayload, payload.event.payload)
            task = announcement.task
        except Exception as exc:
            logger.warning("Agent %s ignored invalid task announcement: %s", self.agent_id, exc)
            return

        logger.info("[%s] Received %s: %s", self.agent_id, payload.event.event_type.value, task.task_id)
        logger.info("[%s] Evaluating task: %s", self.agent_id, task.task_id)
        reason = self.evaluate_task(task)
        if reason:
            rejection = TaskRejectPayload(task_id=task.task_id, agent_id=self.agent_id, reason=reason)
            self.send_event(EventType.TASK_REJECT, rejection.model_dump(), topic_override="logistics/tasks/responses")
            logger.info("[%s] TASK_REJECT: %s reason=%s", self.agent_id, task.task_id, reason)
            return

        proposal = self.calculate_task_proposal(task)
        with self._proposal_lock:
            self._peer_proposals.setdefault(task.task_id, {})[self.agent_id] = proposal
        self.send_event(EventType.TASK_PROPOSAL, proposal.model_dump(), topic_override="logistics/tasks/responses")
        self.send_event(
            EventType.TASK_PROPOSAL,
            proposal.model_dump(),
            topic_override=f"logistics/broadcast/negotiation/proposals/{task.task_id}",
        )
        logger.info(
            "[%s] TASK_PROPOSAL: %s reason=ELIGIBLE utility=%.4f cost=%.2f details=%s",
            self.agent_id,
            task.task_id,
            proposal.utility,
            proposal.estimated_cost,
            proposal.reason,
        )
        logger.info("[%s] Sending TASK_PROPOSAL for %s", self.agent_id, task.task_id)

    def _handle_peer_task_proposal(self, payload: MQTTMessagePayload) -> None:
        try:
            proposal = _parse_model(TaskProposalPayload, payload.event.payload)
            if proposal.agent_id != payload.sender_identity.agent_id:
                return
            with self._proposal_lock:
                self._peer_proposals.setdefault(proposal.task_id, {})[proposal.agent_id] = proposal
            logger.info("[%s] Received negotiation proposal from %s", self.agent_id, proposal.agent_id)
        except Exception as exc:
            logger.warning("[%s] Ignored invalid negotiation proposal: %s", self.agent_id, exc)

    def _handle_negotiation_request(self, payload: MQTTMessagePayload) -> None:
        try:
            request = _parse_model(NegotiationRequestPayload, payload.event.payload)
            if request.task.task_id != request.task_id:
                return
            proposal_ids = sorted(proposal.agent_id for proposal in request.proposals)
            if self.agent_id not in proposal_ids:
                return
            reason = self.evaluate_task(request.task)
            if reason:
                logger.info("[%s] Left negotiation for %s: %s", self.agent_id, request.task_id, reason)
                return

            eligible_proposals = [
                proposal
                for proposal in request.proposals
                if proposal.capability_match
                and proposal.available
                and proposal.battery_pct >= 20.0
                and proposal.payload_capacity_kg >= request.task.payload_weight
                and set(request.task.required_capabilities).issubset(proposal.capabilities)
            ]
            if not eligible_proposals:
                return

            winner = min(
                eligible_proposals,
                key=lambda proposal: (-proposal.utility, proposal.estimated_cost, proposal.agent_id),
            )
            own_proposal = next(proposal for proposal in eligible_proposals if proposal.agent_id == self.agent_id)
            logger.info("[%s] Comparing proposals for %s", self.agent_id, request.task_id)
            accepted = winner.agent_id == self.agent_id
            response = NegotiationResponsePayload(
                task_id=request.task_id,
                agent_id=self.agent_id,
                selected_agent_id=winner.agent_id,
                compared_agent_ids=proposal_ids,
                utility=own_proposal.utility,
                accepted=accepted,
                reason="highest_utility" if accepted else f"{winner.agent_id}_ranked_higher",
            )
            topic = f"logistics/broadcast/negotiation/responses/{request.task_id}"
            self.send_event(EventType.NEGOTIATION_RESPONSE, response.model_dump(), topic_override=topic)
            self.send_event(
                EventType.NEGOTIATION_ACCEPT if accepted else EventType.NEGOTIATION_REJECT,
                response.model_dump(),
                topic_override=topic,
            )
            logger.info(
                "[%s] Negotiation result: selected=%s utility=%.4f cost=%.2f",
                self.agent_id,
                winner.agent_id,
                winner.utility,
                winner.estimated_cost,
            )
        except Exception as exc:
            logger.warning("[%s] Ignored invalid negotiation request: %s", self.agent_id, exc)

    def _handle_negotiation_accept(self, payload: MQTTMessagePayload) -> None:
        try:
            agreement = _parse_model(NegotiationAgreementPayload, payload.event.payload)
            logger.info(
                "[%s] Received NEGOTIATION_ACCEPT for %s; selected=%s",
                self.agent_id,
                agreement.task_id,
                agreement.selected_agent_id,
            )
        except Exception:
            try:
                response = _parse_model(NegotiationResponsePayload, payload.event.payload)
                logger.info("[%s] Received peer acceptance for %s by %s", self.agent_id, response.task_id, response.agent_id)
            except Exception as exc:
                logger.warning("[%s] Ignored invalid negotiation acceptance: %s", self.agent_id, exc)

    def _handle_negotiation_reject(self, payload: MQTTMessagePayload) -> None:
        try:
            response = _parse_model(NegotiationResponsePayload, payload.event.payload)
            logger.info(
                "[%s] Received NEGOTIATION_REJECT from %s for %s: %s",
                self.agent_id,
                response.agent_id,
                response.task_id,
                response.reason,
            )
        except Exception as exc:
            logger.warning("[%s] Ignored invalid negotiation rejection: %s", self.agent_id, exc)

    def _handle_task_assignment(self, payload: MQTTMessagePayload) -> None:
        try:
            assignment = _parse_model(TaskAssignmentPayload, payload.event.payload)
            if assignment.assigned_agent_id != self.agent_id:
                return
            task = assignment.task
            logger.info("[%s] Received TASK_ASSIGNMENT: %s", self.agent_id, task.task_id)
            reason = self.evaluate_task(task)
            if reason:
                rejection = TaskRejectPayload(task_id=task.task_id, agent_id=self.agent_id, reason=reason)
                self.send_event(
                    EventType.TASK_REJECT,
                    rejection.model_dump(),
                    topic_override="logistics/tasks/responses",
                )
                logger.info("[%s] TASK_REJECT: %s reason=%s", self.agent_id, task.task_id, reason)
                return
            task.status = TaskStatus.ASSIGNED
            if not self.assign_task(task):
                logger.info("[%s] TASK_REJECT: %s reason=TASK_MANAGER_REJECTED", self.agent_id, task.task_id)
                return
            logger.info("[%s] Task %s status -> ASSIGNED", self.agent_id, task.task_id)
            status_update = TaskStatusUpdatePayload(
                task_id=task.task_id,
                agent_id=self.agent_id,
                status=TaskStatus.ASSIGNED,
            )
            self.send_event(EventType.TASK_STATUS_UPDATE, status_update.model_dump(), topic_override="logistics/tasks/responses")
            if task.is_subtask:
                logger.info("[%s] Subtask %s status -> IN_PROGRESS", self.agent_id, task.task_id)
                self.update_task_status(task.task_id, TaskStatus.IN_PROGRESS)
                self._schedule_subtask_completion(task)
        except Exception as exc:
            logger.warning("Agent %s ignored invalid task assignment: %s", self.agent_id, exc)

    # Internal Loops & Handlers
    def _heartbeat_loop(self):
        while self._running:
            try:
                self.send_heartbeat()
            except Exception as e:
                logger.error(f"Error sending heartbeat for {self.agent_id}: {e}")
            time.sleep(self.heartbeat_interval_sec)

    def _offline_check_loop(self):
        while self._running:
            try:
                newly_offline = self.registry.check_offline_agents(self.offline_timeout_sec, exclude_agent_id=self.agent_id)
                for off_id in newly_offline:
                    logger.warning(f"Agent {self.agent_id} detected peer {off_id} as OFFLINE")
            except Exception as e:
                logger.error(f"Error checking offline agents for {self.agent_id}: {e}")
            time.sleep(5.0)

    def _on_mqtt_message_received(self, topic: str, payload: MQTTMessagePayload):
        # Ignore self-messages
        if payload.sender_identity.agent_id == self.agent_id:
            return
        
        logger.debug(f"Agent {self.agent_id} received message on {topic} from {payload.sender_identity.agent_id}")
        self.event_handler.dispatch(payload)

    def _handle_heartbeat(self, payload: MQTTMessagePayload):
        sender_id = payload.sender_identity.agent_id
        sender_type = payload.sender_identity.agent_type
        # Update local peer registry
        self.registry.update_heartbeat(
            agent_id=sender_id,
            state=payload.sender_state,
            agent_type=sender_type,
            timestamp=payload.event.timestamp
        )

    def _handle_peer_registration(self, payload: MQTTMessagePayload):
        evt_data = payload.event.payload
        try:
            reg_payload = AgentRegistrationPayload.model_validate(evt_data) if hasattr(AgentRegistrationPayload, "model_validate") else AgentRegistrationPayload.parse_obj(evt_data)
            self.registry.register_agent(reg_payload)
            logger.info(f"Agent {self.agent_id} discovered peer registration: {reg_payload.agent_id} ({reg_payload.agent_type})")
        except Exception as e:
            logger.error(f"Error parsing peer registration: {e}")
            # Fallback to sender identity & state
            self.registry.update_heartbeat(
                agent_id=payload.sender_identity.agent_id,
                state=payload.sender_state,
                agent_type=payload.sender_identity.agent_type
            )

    def _handle_peer_capabilities(self, payload: MQTTMessagePayload):
        evt_data = payload.event.payload
        try:
            cap_payload = CapabilityAdvertisementPayload.model_validate(evt_data) if hasattr(CapabilityAdvertisementPayload, "model_validate") else CapabilityAdvertisementPayload.parse_obj(evt_data)
            self.registry.update_capabilities(cap_payload)
            logger.info(f"Agent {self.agent_id} discovered peer capabilities for: {cap_payload.agent_id}")
        except Exception as e:
            logger.error(f"Could not parse capability payload: {e}")

    def _signal_handler(self, sig, frame):
        logger.info(f"Signal {sig} received. Stopping agent runtime...")
        self.stop()
        sys.exit(0)
