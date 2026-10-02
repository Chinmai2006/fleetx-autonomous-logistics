import argparse
import logging
import time
from agents.runtime import AgentRuntime
from protocols.messages import EventType, MQTTMessagePayload

logger = logging.getLogger("RobotAgent")


def main():
    parser = argparse.ArgumentParser(description="Warehouse Mobile Robot Agent Executable")
    parser.add_argument("--id", type=str, default="ROBOT-01", help="Unique Agent ID")
    parser.add_argument("--host", type=str, default="localhost", help="MQTT Broker Host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT Broker Port")
    args = parser.parse_args()

    agent = AgentRuntime(
        agent_id=args.id,
        agent_type="warehouse_robot",
        capabilities=["bin_picking", "barcode_scanning", "item_sorting"],
        payload_capacity_kg=30.0,
        supported_operations=["pick_item", "sort_parcel", "shelf_inventory"],
        metadata={"arm_reach_m": 1.2, "gripper_type": "vacuum_suction"},
        mqtt_host=args.host,
        mqtt_port=args.port,
        heartbeat_interval_sec=5.0
    )

    # Register handlers for all incoming events
    def on_network_event(payload: MQTTMessagePayload):
        sender = payload.sender_identity.agent_id
        evt_type = payload.event.event_type.value
        data = payload.event.payload
        logger.info(f"[{args.id}] Received '{evt_type}' notification from [{sender}]: {data}")

    agent.event_handler.register_handler(EventType.CUSTOM, on_network_event)
    agent.event_handler.register_handler(EventType.TELEMETRY, on_network_event)

    if not agent.start():
        logger.error(f"Failed to start Robot Agent {args.id}")
        return

    logger.info(f"=== Warehouse Robot Agent {args.id} active. Press Ctrl+C to stop. ===")

    # Announce presence
    agent.send_event(
        event_type=EventType.CUSTOM,
        payload={"message": f"Warehouse Robot {args.id} ready at Station Alpha."}
    )

    try:
        step = 0
        while True:
            time.sleep(5.0)
            step += 1
            agent.state.update_location(x=0.0, y=0.0, z=0.5)

            if step % 2 == 0:
                agent.send_event(
                    event_type=EventType.TELEMETRY,
                    payload={
                        "items_picked_count": step * 3,
                        "station": "Station Alpha",
                        "status": "active_sorting"
                    }
                )
    except KeyboardInterrupt:
        logger.info(f"Stopping Robot Agent {args.id}...")
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
