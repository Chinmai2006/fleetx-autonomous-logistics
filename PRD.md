# Product Requirements Document

**Project:** Decentralized Multi-Agent Coordination for Autonomous Logistics
**Programme:** KPIT K-Impact 2.0 / KPIT Sparkle Finale
**Theme:** Decentralized Multi-Agent Coordination for Autonomous Logistics

---

## 1. Product Overview

This platform demonstrates how heterogeneous autonomous machines — warehouse robots, autonomous ground vehicles (AGVs), and drones — can organize themselves as a **collective** without requiring a central dispatcher to make every decision.

Each physical machine (or simulated process) is represented as an independent software **agent**. Agents communicate over MQTT, discover each other, advertise their capabilities, and negotiate task assignments using locally computed utility scores. A FastAPI backend provides coordination infrastructure, a React dashboard gives operators live visibility, and an agentic AI layer adds bounded observe/plan/validate/execute reasoning on top of the decentralized negotiation fabric.

The system is fully implemented, tested (81 tests), and demonstrated end-to-end in software. Physical hardware integration is a planned future extension.

---

## 2. Problem Statement

Modern autonomous logistics faces several structural challenges:

| Challenge | Description |
|-----------|-------------|
| **Isolated autonomous systems** | Robots, AGVs, and drones each operate in separate silos with incompatible interfaces. They cannot discover or coordinate with each other. |
| **Heterogeneous machine capabilities** | Different machine types have different payloads, mobility types, and sensors. Static assignment logic cannot account for the full diversity of real fleets. |
| **Static task assignment** | Traditional dispatchers pre-assign tasks based on a fixed model of the fleet. This breaks when agents fail, change state, or new machines join. |
| **Lack of machine-to-machine negotiation** | Machines cannot directly compare their own fitness for a task and reach a decentralized consensus without human or central arbiter involvement. |
| **Failure propagation** | When one agent fails mid-mission, the whole pipeline stalls. There is no automatic detection, replanning, or handoff to a replacement. |
| **Centralized coordination bottlenecks** | A central coordinator becomes a single point of failure. Scaling the fleet requires scaling the coordinator proportionally. |
| **Difficulty integrating new machine types** | Adding a new robot type requires changes to the central system. A plug-in model is needed so new machines join the network without modifying existing agents. |

---

## 3. Product Vision

> **"We are not making autonomous machines smarter individually. We are making heterogeneous autonomous machines capable of organizing themselves as a collective."**

The platform follows a **plug-in collective intelligence** model:

1. Connect an autonomous machine → it joins the agent network.
2. It registers its identity and advertises its capabilities.
3. It can autonomously coordinate with other connected machines.
4. The collective self-organizes task allocation through decentralized negotiation.
5. When something fails, the collective self-heals by finding a replacement and handing off the work.

No agent knows the global state. No central dispatcher controls every decision. Coordination emerges from local reasoning and MQTT-based message exchange.

---

## 4. Goals

| Goal | Description |
|------|-------------|
| **Agent discovery** | Agents register and become visible to the platform as soon as they connect. |
| **Capability advertisement** | Each agent broadcasts what it can do (capabilities, payload capacity, operational constraints). |
| **Decentralized proposals** | Agents independently evaluate task announcements and generate proposals based on their local state. |
| **Negotiation** | Agents collectively rank proposals; the platform validates safety constraints and confirms the winning agent. |
| **Task allocation** | The platform assigns tasks to the winning agent through a structured MQTT message flow. |
| **Cooperative task execution** | Multi-stage missions (pickup → transport → delivery) are decomposed into subtasks, each allocated to the best-fit agent type. |
| **Agentic planning** | An observe/plan/validate/execute orchestrator automates mission lifecycle management. |
| **Failure detection** | The platform continuously monitors agents and tasks; offline agents holding active tasks are flagged immediately. |
| **Self-healing** | A self-healing engine identifies replacement candidates and initiates a re-negotiation handoff automatically. |
| **Replacement and handoff** | The failed agent is excluded from re-negotiation; a replacement is selected through the same decentralized process. |
| **Explainability and auditability** | Every decision, assignment, replan, and security event is recorded with a structured audit trail. |
| **Safety validation** | Deterministic constraints (battery, capability, payload, deadline) are enforced independently of any AI layer. |

---

## 5. Non-Goals

The following are explicitly **not** implemented in the current prototype:

- **Direct physical machine control** — no hardware commands are issued. Agents are software processes.
- **Real-world autonomous vehicle control** — no ROS2, MAVLink, or CAN integration exists yet.
- **Production-grade fleet deployment** — the system runs locally or in Docker Compose for demonstration.
- **Unrestricted LLM control of physical actions** — the LLM/agentic layer only proposes plans; deterministic constraints decide what is allowed.
- **Fully persistent operational state** — tasks, agents, audit events, and healing records are held in memory and reset on process restart. PostgreSQL and Redis are configured infrastructure components whose persistent write integration is a future extension.
- **Real road network routing** — route distances are either Euclidean from local warehouse coordinates or explicitly supplied by the caller.
- **Production-grade secret management** — tokens are environment variables; a secrets manager is not yet integrated.
- **Full mTLS between every agent** — TLS configuration is provided as a template; the default local config uses anonymous MQTT.

---

## 6. Users / Actors

| Actor | Role |
|-------|------|
| **Human Operator** | Creates missions via the dashboard or REST API, monitors fleet status, triggers demo failures, and reviews audit records. |
| **Platform (Backend)** | Coordinates task lifecycle, runs safety validation, manages the agent registry, and runs the agentic orchestrator. |
| **Drone Agent** | Handles final-mile aerial delivery tasks (`aerial_delivery` capability); payload up to 2.5 kg. |
| **AGV / Vehicle Agent** | Handles ground transport tasks (`ground_transport`, `heavy_freight`); payload up to 250 kg. |
| **Robot Agent** | Handles warehouse picking tasks (`bin_picking`, `barcode_scanning`); payload up to 30 kg. |
| **Future autonomous machine types** | Any machine that implements the agent runtime protocol and connects over MQTT can join the network. |

---

## 7. Functional Requirements

### 7.1 Agent Registration and Discovery

- FR-01: An agent must publish an `AGENT_REGISTER` event to `logistics/agents/{agent_id}/register` on startup.
- FR-02: The platform registry service must record the agent's identity, type, capabilities, and initial state.
- FR-03: Agents publish `CAPABILITY_ADVERTISEMENT` events to broadcast supported capabilities and payload limits.
- FR-04: Agents send periodic heartbeats; the platform marks agents OFFLINE if no heartbeat is received within 15 seconds.
- FR-05: The `/api/v1/agents` endpoint returns all known agents; `/api/v1/agents/active-fleet` returns only currently online agents.

### 7.2 Task Creation

- FR-06: Operators create tasks via `POST /api/v1/tasks` (coordination path) or `POST /api/v1/agentic/tasks` (orchestrator path).
- FR-07: Tasks marked `cooperative=true` or `task_type=cooperative_delivery` are automatically decomposed into pickup → transport → delivery subtasks.
- FR-08: Each subtask receives a deterministic ID (`{parent_id}-ST{N}`) and is linked to the parent task.

### 7.3 Proposal Generation and Negotiation

- FR-09: The platform announces tasks to all agents via `logistics/broadcast/tasks`.
- FR-10: Eligible agents generate proposals with a locally computed utility score (battery, workload, distance, priority, deadline, execution time, handoff count).
- FR-11: The platform collects proposals for a configurable window (default 1 second), then runs safety re-validation on each.
- FR-12: Validated proposals are shared with all agents for ranking (`logistics/broadcast/negotiation/requests/{task_id}`).
- FR-13: Agents independently select the best proposal and publish their `NegotiationResponsePayload`.
- FR-14: The platform detects unanimous agreement and publishes a `NegotiationAgreementPayload`, then assigns the task to the winning agent.

### 7.4 Task Execution

- FR-15: The assigned agent confirms receipt with a `TASK_STATUS_UPDATE` (status = ASSIGNED).
- FR-16: For cooperative tasks, each subtask is negotiated and executed independently; the parent task completes when all subtasks complete.
- FR-17: The platform monitors task and agent state via a polling loop (default every 0.25 seconds).

### 7.5 Failure Detection and Self-Healing

- FR-18: If an agent holding an active task goes OFFLINE or ERROR, the orchestrator detects this on its next poll cycle.
- FR-19: The self-healing engine identifies eligible replacement candidates (IDLE, battery ≥ 20%, capability match, within heartbeat timeout).
- FR-20: Candidates are ranked by battery percentage descending; a `HealingRecord` is created with the failure, impact, and candidates.
- FR-21: The platform issues a `TASK_HANDOFF_REQUEST`, excluding the failed agent; a new round of negotiation selects the replacement.
- FR-22: The `replan_count` is incremented; if `max_replans` (default 2) is reached, the mission is permanently failed.
- FR-23: A bounded wait of up to 3 seconds is applied before failing if a dynamically launched replacement agent has not yet completed MQTT registration.

### 7.6 Agentic Orchestrator

- FR-24: The orchestrator follows an OBSERVE → PLAN → VALIDATE → EXECUTE → OBSERVE_RESULT cycle.
- FR-25: Planning produces a `PlanningResult`; the rule-based planner is always available as a deterministic fallback.
- FR-26: Safety validation is enforced deterministically and cannot be bypassed by the planning layer.
- FR-27: Agentic execution state (phase, observations, assignments, replan_count) is exposed via `/api/v1/agentic/tasks`.

### 7.7 Audit and Observability

- FR-28: Every significant event (agent registration, task creation, negotiation outcome, assignment, replan, self-healing, security event) is written to the audit log.
- FR-29: The audit log is filterable by event_type, task_id, and agent_id; it is bounded to the 2000 most recent records.
- FR-30: The `/api/v1/risks` endpoint returns current operational risks (low battery, offline agent with active task, deadline exceeded, capability mismatch).

---

## 8. Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
| **Scalability** | Independent agent processes and MQTT publish/subscribe allow the fleet to grow without modifying the coordination service. |
| **Modularity** | Agent runtime, task coordination, agentic orchestrator, self-healing, planning, and registry are separate, independently replaceable services. |
| **Reliability** | Agents use local heartbeat timeouts to detect peer failures; the platform's offline checker runs every 5 seconds. |
| **Safety** | Deterministic constraints (capability, battery, payload, deadline) are enforced independently of any AI layer and cannot be bypassed. |
| **Observability** | Structured audit log, risk engine, health monitor, and fleet analytics give operators full visibility. |
| **Explainability** | Every dispatch decision records the factors and rationale; every self-healing event records candidates and the selection logic. |
| **Extensibility** | New agent types join by implementing the `AgentRuntime` interface; no changes to existing agents or the platform are required. |
| **Security** | Bearer-token authorization protects operator and admin operations; MQTT topic-level identity validation rejects spoofed agent events. |

---

## 9. Safety Principle

> **"Agentic AI proposes and reasons; deterministic constraints validate what is allowed."**

This is an architectural invariant of the system:

- The agentic orchestrator (and any optional LLM planner) may generate plans, replan after failures, and recommend handoffs.
- Before any plan or handoff is executed, `validate_plan()` and `ProposalSafetyValidator` enforce hard constraints: capability match, battery threshold, payload capacity, offline timeout, deadline, and task-type exclusions.
- These constraints are implemented in Python and cannot be overridden by a plan, a language model output, or an agent proposal.
- The AI layer never directly controls physical hardware; it only influences which task is announced for decentralized negotiation.

---

## 10. KPIT / Mobility Relevance

This project directly addresses challenges that KPIT and the automotive / mobility industry face as fleets of heterogeneous autonomous machines become commercially viable:

| Relevance Area | How this system addresses it |
|----------------|------------------------------|
| **Autonomous mobility** | Agents simulate the coordination layer that would sit above real autonomous vehicles, drones, and robots in a mixed fleet. |
| **Logistics optimization** | Decentralized negotiation allows the fleet to self-organize optimal task allocation without a central dispatcher bottleneck. |
| **Heterogeneous fleets** | Capability-based eligibility allows robots, AGVs, and drones to coexist in the same mission pipeline and specialize by stage. |
| **Resilience** | The self-healing engine and bounded replan mechanism ensure missions continue despite individual machine failures. |
| **Scalable autonomous systems** | The MQTT publish/subscribe model scales to large fleets; adding a new machine type requires no changes to existing agents. |
| **Explainable AI** | Every decision is recorded with its rationale; operators can audit exactly why each assignment was made. |

---

## 11. Future Scope

The following capabilities are explicitly planned for future phases but are **not** implemented in the current prototype:

| Feature | Description |
|---------|-------------|
| **ROS2 integration** | Hardware adapter layer connecting real robots over ROS2 topics to the agent runtime. |
| **MAVLink integration** | Adapter for real drone control (ArduPilot / PX4 autopilots). |
| **CAN bus integration** | Adapter for automotive / industrial vehicle control. |
| **Real drone hardware** | Physical drones participating in MQTT-driven coordination. |
| **Real AGV hardware** | Physical ground vehicles responding to task assignments. |
| **Richer ML / LLM planning** | A fully implemented LLM planner that generates novel subtask sequences beyond the fixed cooperative delivery pipeline. |
| **Persistent operational storage** | Writing tasks, agents, and audit records to PostgreSQL for durability across restarts. |
| **Redis for caching and coordination** | Using Redis for distributed lock coordination and agent state caching. |
| **Larger fleet simulation** | Hundreds of simulated agents in a warehouse digital twin. |
| **Real road network routing** | Integration with a routing engine (OSRM, Valhalla) for accurate travel time and cost estimation. |

---

*See also: [Architecture.md](Architecture.md) · [Agents.md](Agents.md) · [Security.md](Security.md) · [Testing.md](Testing.md)*
