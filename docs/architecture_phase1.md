# Phase 1 Architectural Documentation — Foundation

## Overview
Phase 1 establishes the baseline infrastructure, telemetry control plane, container environment, and health verification modules for the **Decentralized Multi-Agent Coordination Platform**.

---

## Component Topology

```
                   +-----------------------------+
                   |  Frontend Dashboard (Vite)  |
                   |  React + TS + Tailwind CSS  |
                   +--------------+--------------+
                                  |
                           HTTP / REST API
                                  |
                                  v
                   +-----------------------------+
                   |  FastAPI Backend Service    |
                   |  (Async Health Controller)  |
                   +-------+------+------+-------+
                           |      |      |
           +---------------+      |      +---------------+
           |                      |                      |
           v                      v                      v
+--------------------+  +-------------------+  +-------------------+
|  PostgreSQL 16 DB  |  |  Redis 7 Cache    |  | Mosquitto MQTT    |
|  (State Storage)   |  |  & Lock Broker    |  | Broker (Port 1883)|
+--------------------+  +-------------------+  +-------------------+
```

---

## Health Checking Mechanism

The `/api/v1/health` endpoint evaluates three critical backend integration points asynchronously using `asyncio.gather`:

1. **PostgreSQL**: Establishes an async connection via `asyncpg` and executes `SELECT 1`.
2. **Redis**: Issues an async `PING` command via `redis.asyncio` client.
3. **MQTT Broker**: Verifies TCP socket reachability on port 1883 (or host configured in environment).

### Response Schema:
```json
{
  "status": "healthy",
  "timestamp": "2026-09-28T04:12:00.000Z",
  "services": {
    "backend": { "status": "connected", "latency_ms": 0.0, "message": "FastAPI engine active" },
    "postgres": { "status": "connected", "latency_ms": 4.12, "message": "Database query succeeded (SELECT 1)" },
    "redis": { "status": "connected", "latency_ms": 1.85, "message": "Redis PING succeeded" },
    "mqtt": { "status": "connected", "latency_ms": 2.05, "message": "MQTT TCP socket port 1883 reachable" }
  }
}
```

---

## Future Phase Integration Points
- **Phase 2**: Autonomous Agent lifecycle (`agents/`), P2P contract net protocol (`protocols/`).
- **Phase 3**: Dynamic pathfinding & collision avoidance algorithms (`algorithms/`).
- **Phase 4**: Hardware adapters for drones/AGVs (`adapters/`).

## Phase 4B — Decentralized Negotiation

Each agent evaluates task feasibility against its local capabilities and state, then computes and broadcasts an explainable proposal over MQTT. Utility is a weighted sum of normalized battery (0.20), payload headroom (0.20), availability (0.15), distance (0.25), priority (0.10), and deadline urgency (0.10). Estimated cost is reported separately and is used only as a tie-breaker.

The platform coordinator does not rank proposals. It rejects proposals that fail registered/live safety checks (availability, freshness, battery, required capabilities, capacity, and deadline), requests comparisons from every remaining proposer, and accepts a result only when every eligible agent reports the same selected agent and that winner accepts. Agents break ties by lowest estimated cost, then lexicographically by agent ID. The coordinator revalidates the winner and publishes the MQTT agreement before sending the existing agent-specific assignment event.

The task dashboard exposes proposal utility, cost, score components, agent comparisons, acceptance, and hard-rejection reasons from the task API. The real-Mosquitto integration test covers proposal exchange through assignment delivery.
