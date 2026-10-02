import logging
from typing import Callable, Dict, List
from protocols.messages import EventType, MQTTMessagePayload

logger = logging.getLogger("EventHandler")

EventHandlerCallback = Callable[[MQTTMessagePayload], None]


class EventHandler:
    """
    Event router registering callbacks by EventType and dispatching incoming MQTT messages.
    """

    def __init__(self):
        self._handlers: Dict[str, List[EventHandlerCallback]] = {}

    def register_handler(self, event_type: EventType, callback: EventHandlerCallback) -> None:
        """Register a handler callback for a specific EventType."""
        key = event_type.value
        if key not in self._handlers:
            self._handlers[key] = []
        self._handlers[key].append(callback)
        logger.info(f"Registered event handler for EventType: {key}")

    def register_global_handler(self, callback: EventHandlerCallback) -> None:
        """Register a handler callback for all event types."""
        if "*" not in self._handlers:
            self._handlers["*"] = []
        self._handlers["*"].append(callback)

    def dispatch(self, payload: MQTTMessagePayload) -> None:
        """Route incoming payload to matching EventType callbacks."""
        evt_type = payload.event.event_type.value

        # Global handlers
        if "*" in self._handlers:
            for cb in self._handlers["*"]:
                try:
                    cb(payload)
                except Exception as e:
                    logger.error(f"Error in global event handler: {e}")

        # Specific event type handlers
        if evt_type in self._handlers:
            for cb in self._handlers[evt_type]:
                try:
                    cb(payload)
                except Exception as e:
                    logger.error(f"Error in event handler for {evt_type}: {e}")
