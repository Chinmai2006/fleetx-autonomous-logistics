import argparse
import json
import logging
import signal
import sys
import threading

from agents.runtime import AgentRuntime
from protocols.messages import AgentStatus, Location

logger = logging.getLogger("DynamicAgent")


def run(spec: dict) -> None:
    shutdown = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: shutdown.set())

    location = Location.model_validate(spec.get("location") or {})
    initial_available = bool(spec.get("available", True))
    metadata = dict(spec.get("metadata") or {})
    metadata["managed_by_platform"] = True
    metadata["operational_constraints"] = dict(spec.get("operational_constraints") or {})
    runtime = AgentRuntime(
        agent_id=spec["agent_id"],
        agent_type=spec["agent_type"],
        capabilities=spec["capabilities"],
        payload_capacity_kg=spec["payload_capacity_kg"],
        supported_operations=spec.get("supported_operations", []),
        metadata=metadata,
        mqtt_host=spec["mqtt_host"],
        mqtt_port=spec["mqtt_port"],
        heartbeat_interval_sec=spec.get("heartbeat_interval_sec", 2.0),
        initial_battery_pct=spec.get("battery_pct", 100.0),
        initial_location=location,
        initial_available=initial_available,
        operational_constraints=spec.get("operational_constraints"),
        mqtt_username=spec.get("mqtt_username"),
        mqtt_password=spec.get("mqtt_password"),
        mqtt_tls_ca_cert=spec.get("mqtt_tls_ca_cert"),
        mqtt_tls_certfile=spec.get("mqtt_tls_certfile"),
        mqtt_tls_keyfile=spec.get("mqtt_tls_keyfile"),
    )
    runtime.subtask_execution_seconds = spec.get("subtask_execution_seconds", 0.35)
    if not runtime.start():
        raise RuntimeError(f"Agent {spec['agent_id']} failed to connect to MQTT")
    logger.info("Managed agent %s joined MQTT registry", runtime.agent_id)
    try:
        shutdown.wait()
    finally:
        runtime.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec")
    parser.add_argument("--spec-stdin", action="store_true")
    args = parser.parse_args()
    if args.spec_stdin:
        spec_json = sys.stdin.readline()
    elif args.spec:
        spec_json = args.spec
    else:
        parser.error("provide --spec-stdin or --spec")
    run(json.loads(spec_json))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()