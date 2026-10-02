# Agents

**Project:** Decentralized Multi-Agent Coordination for Autonomous Logistics

---

## 1. Agent Concept

Every autonomous machine in this platform is represented as an independent software **agent**. An agent is a Python process that runs the `AgentRuntime` class, connects to the MQTT broker, and participates in the platform's coordination protocols autonomously.

The key design principle is that **agents make local decisions**. An agent evaluates its own state (battery, workload, capabilities) to decide whether to propose for a task, and independently scores competing proposals during negotiation. The platform provides coordination infrastructure — announcement, validation, and consensus detection — but the eligibility reasoning stays inside each agent.

> MQTT is the **communication transport**, not the decision-maker. Agents decide; MQTT delivers those decisions to their peers.

---

## 2. Current Agent Types

Three agent types are implemented. All use the same `AgentRuntime` base; they differ in their capability sets, payload limits, and metadata.

### Warehouse Robot (`warehouse_robot`)

Defined in `agents/examples/robot_agent.py`.

| Property | Value |
|----------|-------|
| Default ID | `ROBOT-01` |
| Capabilities | `bin_picking`, `barcode_scanning`, `item_sorting` |
| Payload capacity | 30 kg |
| Supported operations | `pick_item`, `sort_parcel`, `shelf_inventory` |
| Metadata | `arm_reach_m: 1.2`, `gripper_type: vacuum_suction` |
| Heartbeat interval | 5 seconds |

Warehouse robots handle the **pickup** stage of cooperative deliveries.

### Autonomous Ground Vehicle / AGV (`agv`)

Defined in `agents/examples/vehicle_agent.py`.

| Property | Value |
|----------|-------|
| Default ID | `AGV-01` |
| Capabilities | `heavy_freight`, `ground_transport`, `docking` |
| Payload capacity | 25