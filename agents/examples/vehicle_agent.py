import argparse
import logging
import time
from agents.runtime import AgentRuntime
from protocols.messages import EventType, MQTTMessagePayload

logger = logging.getLogger("VehicleAgent")


def main():
    parser = argparse.ArgumentParser(description="Autonomous Vehicle (AGV) Agent Executable")
    parser.add_argument("--id", type=str, default="AGV-01", help="Unique Agent ID")
    parser.add_argument("--host", type=str, default="localhost", help="MQTT Broker Host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker Port")
    args = parser.parse_args()

    agent = AgentRuntime(
        agent_id=args.id,
        agent_type="agv",
        capabilities=["heavy_freight", "ground_transport", "docking"],
        payload_capacity_kg=250.0,
        supported_operations=["haul_pallet", "transport_cargo"],
        metadata={"max_speed_kmh": 25.0, "wheel_base_m": 1.8},
        mqtt_host=args.host,
        mqtt_port=args.port,
        heartbeat_interval_sec=5.0
    )

    # Register event handler for incoming custom events & telemetries from other agents
    def on_broadcast_event(payload: MQTTMessagePayload):
        sender = payload.sender_identity.agent_id
        evt_type = payload.event.event_type.value
        msg = payload.event.payload
        logger.info(f"[{args.id}] Intercepted broadcast '{evt_type}' from [{sender}]: {msg}")

    agent.event_handler.register_handler(EventType.CUSTOM, on_broadcast_event)
    agent.event_handler.register_handler(EventType.TELEMETRY, on_broadcast_event)

    if not agent.start():
        logger.error(f"Failed to start AGV Agent {args.id}")
        return

    logger.info(f"=== AGV Agent {args.id} active. Press Ctrl+C to stop. ===")

    # Announce presence to network
    agent.send_event(
        event_type=EventType.CUSTOM,
        payload={"message": f"Autonomous Ground Vehicle {args.id} initialized."}
    )

    try:
        step = 0
        while True:
            time.sleep(4.0)
            step += 1
            agent.state.update_location(x=5.0 + (step * 2.0), y=12.0, z=0.0)

            if step % 2 == 0:
                agent.send_event(
                    event_type=EventType.TELEMETRY,
                    payload={
                        "cargo_weight_kg": 75.0,
                        "odometer_m": step * 8.0,
                        "status": "in_transit"
                    }
                )
    except KeyboardInterrupt:
        logger.info(f"Stopping AGV Agent {args.id}...")
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
