import json
import logging
import os
import threading
import time
from typing import Optional

import paho.mqtt.client as mqtt

from app.core.config import settings
from app.services.audit_log import audit_log
from agents.core.registry import AgentRegistry
from protocols.messages import (
    AgentRegistrationPayload,
    CapabilityAdvertisementPayload,
    MQTTMessagePayload,
)

logger = logging.getLogger("PlatformRegistryService")


class PlatformRegistryService:
    """
    Backend service listening to MQTT registry channels and maintaining a central platform AgentRegistry.
    """

    def __init__(self):
        self.registry = AgentRegistry(offline_timeout_seconds=15.0)
        self._connected = False
        self._running = False
        self._offline_thread: Optional[threading.Thread] = None

        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"fastapi-platform-registry-{os.getpid()}"
            )
        except AttributeError:
            self._client = mqtt.Client(client_id=f"fastapi-platform-registry-{os.getpid()}")

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        if settings.MQTT_USERNAME:
            self._client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD or None)
        if settings.MQTT_TLS_CA_CERT:
            self._client.tls_set(
                ca_certs=settings.MQTT_TLS_CA_CERT,
                certfile=settings.MQTT_TLS_CERTFILE or None,
                keyfile=settings.MQTT_TLS_KEYFILE or None,
            )

    def start(self):
        if self._running:
            return
        try:
            self._client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, 60)
            self._client.loop_start()
            self._running = True

            # Start offline checker loop
            self._offline_thread = threading.Thread(
                target=self._offline_check_loop,
                name="PlatformRegistryOfflineChecker",
                daemon=True
            )
            self._offline_thread.start()
            logger.info("PlatformRegistryService started and connected to MQTT broker.")
        except Exception as e:
            logger.error(f"Failed to start PlatformRegistryService: {e}")

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("PlatformRegistryService stopped.")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        logger.info("PlatformRegistryService connected to MQTT broker. Subscribing to registry topics...")
        self._client.subscribe("logistics/registry/#")
        self._client.subscribe("logistics/agents/+/heartbeat")
        self._client.subscribe("logistics/agents/+/register")
        self._client.subscribe("logistics/agents/+/capabilities")

    def _on_message(self, client, userdata, message):
        topic = message.topic
        try:
            data = json.loads(message.payload.decode("utf-8"))
            parsed_payload = MQTTMessagePayload.from_dict(data)
            topic_parts = topic.split("/")
            scoped_agent_id = topic_parts[2] if len(topic_parts) >= 4 and topic_parts[:2] == ["logistics", "agents"] else None
            if scoped_agent_id and scoped_agent_id != parsed_payload.sender_identity.agent_id:
                audit_log.record(
                    "security.agent_topic_identity_mismatch",
                    "Rejected registry event because topic identity did not match sender identity",
                    actor=parsed_payload.sender_identity.agent_id,
                    agent_id=scoped_agent_id,
                    result="denied",
                )
                return

            if topic == "logistics/registry/register" or (scoped_agent_id and topic_parts[3] == "register"):
                try:
                    reg_payload = AgentRegistrationPayload.model_validate(parsed_payload.event.payload) if hasattr(AgentRegistrationPayload, "model_validate") else AgentRegistrationPayload.parse_obj(parsed_payload.event.payload)
                    if (
                        reg_payload.agent_id != parsed_payload.sender_identity.agent_id
                        or (scoped_agent_id is not None and scoped_agent_id != parsed_payload.sender_identity.agent_id)
                    ):
                        audit_log.record(
                            "security.agent_identity_mismatch",
                            "Rejected registry identity that did not match MQTT sender",
                            actor=parsed_payload.sender_identity.agent_id,
                            agent_id=reg_payload.agent_id,
                            result="denied",
                        )
                        return
                    self.registry.register_agent(reg_payload)
                    audit_log.record(
                        "agent.registered",
                        f"Agent {reg_payload.agent_id} registered over MQTT",
                        actor=reg_payload.agent_id,
                        agent_id=reg_payload.agent_id,
                        details={"agent_type": reg_payload.agent_type, "capability_count": len(reg_payload.capabilities)},
                    )
                except Exception:
                    self.registry.update_heartbeat(
                        agent_id=parsed_payload.sender_identity.agent_id,
                        state=parsed_payload.sender_state,
                        agent_type=parsed_payload.sender_identity.agent_type
                    )
            elif topic == "logistics/registry/capabilities" or (scoped_agent_id and topic_parts[3] == "capabilities"):
                try:
                    cap_payload = CapabilityAdvertisementPayload.model_validate(parsed_payload.event.payload) if hasattr(CapabilityAdvertisementPayload, "model_validate") else CapabilityAdvertisementPayload.parse_obj(parsed_payload.event.payload)
                    if (
                        cap_payload.agent_id != parsed_payload.sender_identity.agent_id
                        or (scoped_agent_id is not None and scoped_agent_id != parsed_payload.sender_identity.agent_id)
                    ):
                        audit_log.record(
                            "security.agent_identity_mismatch",
                            "Rejected capability advertisement with mismatched MQTT identity",
                            actor=parsed_payload.sender_identity.agent_id,
                            agent_id=cap_payload.agent_id,
                            result="denied",
                        )
                        return
                    self.registry.update_capabilities(cap_payload)
                    audit_log.record(
                        "agent.capabilities_updated",
                        f"Agent {cap_payload.agent_id} advertised capabilities",
                        actor=cap_payload.agent_id,
                        agent_id=cap_payload.agent_id,
                        details={"capability_count": len(cap_payload.capabilities)},
                    )
                except Exception:
                    pass
            elif topic == "logistics/registry/status":
                self.registry.update_heartbeat(
                    agent_id=parsed_payload.sender_identity.agent_id,
                    state=parsed_payload.sender_state,
                    agent_type=parsed_payload.sender_identity.agent_type,
                    timestamp=parsed_payload.event.timestamp
                )
            elif "heartbeat" in topic or parsed_payload.event.event_type.value == "HEARTBEAT":
                prior = self.registry.get_agent(parsed_payload.sender_identity.agent_id)
                self.registry.update_heartbeat(
                    agent_id=parsed_payload.sender_identity.agent_id,
                    state=parsed_payload.sender_state,
                    agent_type=parsed_payload.sender_identity.agent_type,
                    timestamp=parsed_payload.event.timestamp
                )
                if prior and prior.status != parsed_payload.sender_state.status:
                    audit_log.record(
                        "agent.status_changed",
                        f"Agent status changed from {prior.status.value} to {parsed_payload.sender_state.status.value}",
                        actor=parsed_payload.sender_identity.agent_id,
                        agent_id=parsed_payload.sender_identity.agent_id,
                        details={"previous_status": prior.status.value, "status": parsed_payload.sender_state.status.value},
                    )
        except Exception as e:
            logger.debug(f"PlatformRegistryService ignored message on {topic}: {e}")

    def _offline_check_loop(self):
        while self._running:
            try:
                self.registry.check_offline_agents(15.0)
            except Exception as e:
                logger.error(f"Error in platform registry offline checker: {e}")
            time.sleep(5.0)


# Global platform registry singleton
platform_registry_service = PlatformRegistryService()
