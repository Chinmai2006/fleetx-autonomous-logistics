import json
import logging
import uuid
from typing import Callable, Dict, Optional, List
import paho.mqtt.client as mqtt

from protocols.messages import MQTTMessagePayload

logger = logging.getLogger("MQTTCommunicator")


class MQTTCommunicator:
    """
    MQTT client manager handling connections, subscriptions, message routing, and JSON payload serialization.
    """

    def __init__(
        self,
        agent_id: str,
        host: str = "localhost",
        port: int = 1883,
        keepalive: int = 60,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tls_ca_cert: Optional[str] = None,
        tls_certfile: Optional[str] = None,
        tls_keyfile: Optional[str] = None,
    ):
        self.agent_id = agent_id
        self.host = host
        self.port = port
        self.keepalive = keepalive
        self.username = username

        # Compatibility for paho-mqtt v2 and v1
        client_id = f"agent-{agent_id}-{uuid.uuid4().hex}"
        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id
            )
        except AttributeError:
            self._client = mqtt.Client(client_id=client_id)

        if username:
            self._client.username_pw_set(username, password)
        if tls_ca_cert:
            self._client.tls_set(ca_certs=tls_ca_cert, certfile=tls_certfile, keyfile=tls_keyfile)

        self._connected = False
        self._message_callbacks: List[Callable[[str, MQTTMessagePayload], None]] = []

        # Register internal paho callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def register_on_payload_received(self, callback: Callable[[str, MQTTMessagePayload], None]) -> None:
        """Register callback for deserialized MQTTMessagePayload objects."""
        self._message_callbacks.append(callback)

    def connect(self) -> bool:
        """Connect to MQTT broker and start network loop."""
        try:
            self._client.connect(self.host, self.port, self.keepalive)
            self._client.loop_start()
            logger.info(f"Connecting to MQTT broker at {self.host}:{self.port} for agent {self.agent_id}...")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from MQTT broker and stop network loop."""
        if self._connected:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False
            logger.info(f"Agent {self.agent_id} disconnected from MQTT broker.")

    def subscribe(self, topic: str) -> bool:
        """Subscribe to an MQTT topic."""
        result, _ = self._client.subscribe(topic)
        if result == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"Agent {self.agent_id} subscribed to topic: {topic}")
            return True
        logger.error(f"Failed to subscribe to topic {topic}, code: {result}")
        return False

    def publish_payload(self, topic: str, payload: MQTTMessagePayload, qos: int = 1) -> bool:
        """Serialize and publish an MQTTMessagePayload object."""
        try:
            json_str = payload.to_json()
            info = self._client.publish(topic, json_str, qos=qos)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.error(f"Failed to publish payload to {topic}: {e}")
            return False

    def is_connected(self) -> bool:
        return self._connected

    # Callback implementations
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        rc_code = rc.value if hasattr(rc, 'value') else rc
        if rc_code == 0:
            self._connected = True
            logger.info(f"Agent {self.agent_id} successfully connected to MQTT broker.")
        else:
            logger.error(f"Agent {self.agent_id} connection failed with code {rc_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags, rc=None, properties=None):
        self._connected = False
        logger.warning(f"Agent {self.agent_id} disconnected from MQTT broker.")

    def _on_message(self, client, userdata, message):
        topic = message.topic
        try:
            payload_dict = json.loads(message.payload.decode('utf-8'))
            parsed_payload = MQTTMessagePayload.from_dict(payload_dict)
            
            # Dispatch to registered callbacks
            for cb in self._message_callbacks:
                try:
                    cb(topic, parsed_payload)
                except Exception as cb_err:
                    logger.error(f"Error in message callback for topic {topic}: {cb_err}")
        except Exception as e:
            logger.debug(f"Received non-standard or unparseable MQTT payload on {topic}: {e}")
