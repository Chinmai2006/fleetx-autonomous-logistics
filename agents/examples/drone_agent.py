import argparse
import logging
import time
from agents.runtime import AgentRuntime
from protocols.messages import EventType, MQTTMessagePayload

logger = logging.getLogger("DroneAgent")


def main():
    parser = argparse.ArgumentParser(description="Autonomous Drone Agent Executable")
    parser.add_argument("--id", type=str, default="DRONE-01", help="Unique Agent ID")
    parser.add_argument("--host", type=str, default="localhost", help="MQTT Broker Host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker Port")
    args = parser.parse_args()

    agent = AgentRuntime(
        agent_id=args.id,
        agent_type="drone",
        capabilities=["aerial_delivery", "rapid_reconnaissance", "vertical_takeoff"],
        payload_capacity_kg=2.5,
        supported_operations=["inspect_zone", "deliver_package"],
        metadata={"max_altitude_m": 120.0, "rotor_count": 4},
        mqtt_host=args.host,
        mqtt_port=args.port,
        heartbeat_interval_sec=4.0
    )

    # Register custom event handler for broadcast messages
    def on_custom_event(payload: MQTTMessagePayload):
        sender = payload.sender_identity.agent_id
        evt_type = payload.event.event_type.value
        msg_data = payload.event.payload
        logger.info(f"[{args.id}] Received event '{evt_type}' from {sender}: {msg_data}")

    agent.event_handler.register_handler(EventType.CUSTOM, on_custom_event)

    if not agent.start():
        logger.error(f"Failed to start Drone Agent {args.id}")
        return

    logger.info(f"=== Drone Agent {args.id} active. Press Ctrl+C to stop. ===")
    
    # Broadcast initial online announcement
    agent.send_event(
        event_type=EventType.CUSTOM,
        payload={"message": f"Drone Agent {args.id} is online and operational."}
    )

    try:
        step = 0
        while True:
            time.sleep(3.0)
            step += 1
            # Simulate altitude flight telemetry and slight battery consumption
            curr_battery = max(10.0, 100.0 - (step * 0.5))
            agent.state.update_battery(curr_battery)
            agent.state.update_location(x=10.0 + step, y=20.0 + step, z=15.0)

            # Send telemetry update every 3 steps
            if step % 3 == 0:
                agent.send_event(
                    event_type=EventType.TELEMETRY,
                    payload={
                        "altitude_m": 15.0,
                        "speed_m_s": 8.5,
                        "battery_pct": curr_battery
                    }
                )
    except KeyboardInterrupt:
        logger.info(f"Stopping Drone Agent {args.id}...")
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
