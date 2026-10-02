# FLEETX

### Decentralized Multi-Agent Coordination for Autonomous Logistics

> **Connect an autonomous machine → it joins the agent network → it can autonomously coordinate with other connected machines.**

[🚀 Live Demo](YOUR_URL) · [📐 Architecture](Architecture.md) · [🔐 Security](Security.md)

---

## 🚨 The Problem

Modern autonomous machines are becoming increasingly capable, but they typically operate as isolated systems.

A logistics environment may contain:

- 🚁 Drones
- 🚚 Autonomous Ground Vehicles
- 🤖 Warehouse Robots

The problem is not simply making each machine autonomous.

The challenge is enabling **different autonomous machines to coordinate with each other**.

A centralized controller can become a bottleneck, while isolated machines cannot dynamically negotiate tasks, cooperate on missions, or recover intelligently when another machine fails.

### The core problem:

> **How can heterogeneous autonomous machines organize themselves and coordinate logistics tasks without relying on a single centralized decision-maker?**

---

## 💡 Our Solution — FLEETX

**FLEETX** is a decentralized multi-agent coordination platform that enables heterogeneous autonomous machines to operate as a cooperative fleet.

Each machine is represented as an independent software agent.

Agents can:

- Discover logistics tasks
- Advertise their capabilities
- Evaluate their suitability for tasks
- Submit proposals
- Negotiate assignments
- Cooperate with other agents
- Handle multi-stage missions
- Detect failures
- Find replacement agents
- Replan and hand off tasks

This transforms a collection of autonomous machines into a **coordinated autonomous fleet**.

---

## ⚙️ How FLEETX Works

```text
              LOGISTICS TASK
                    │
                    ▼
             TASK ANNOUNCEMENT
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
      DRONE         AGV        ROBOT
        │           │           │
        ▼           ▼           ▼
     PROPOSAL     PROPOSAL    PROPOSAL
        │           │           │
        └───────────┼───────────┘
                    ▼
              NEGOTIATION
                    │
                    ▼
                ASSIGNMENT
                    │
                    ▼
          COOPERATIVE EXECUTION
                    │
                    ▼
              MISSION COMPLETE

Each agent evaluates factors such as:

Capability
Battery
Payload
Workload
Distance
Cost
Priority
Deadline

The resulting proposals are validated before assignment.

🤖 Agentic Intelligence

FLEETX uses a bounded agentic workflow:

OBSERVE
   ↓
PLAN
   ↓
VALIDATE
   ↓
DELEGATE
   ↓
OBSERVE RESULT
   ↓
REPLAN when required

The important design principle is:

AI proposes. Deterministic safety rules validate.

The AI layer cannot directly bypass safety constraints or directly control physical hardware.

🤝 Cooperative Multi-Agent Missions

FLEETX can decompose a complex logistics mission into multiple subtasks.

Example:

                 DELIVERY MISSION
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       PICKUP       TRANSPORT     DELIVERY
          │            │            │
      ROBOT-01       AGV-01      DRONE-01

Different machines can therefore contribute different capabilities to the same mission.

🔄 Self-Healing Fleet

Autonomous fleets must also handle failures.

If an assigned machine becomes unavailable:

FAILURE DETECTED
       ↓
RISK ASSESSMENT
       ↓
REPLAN
       ↓
FIND REPLACEMENT
       ↓
NEGOTIATION
       ↓
HANDOFF
       ↓
MISSION RESUMED

This allows the fleet to adapt instead of requiring the entire mission to be manually restarted.

🏗️ Architecture
                         OPERATOR
                             │
                             ▼
                    ┌─────────────────┐
                    │   FLEETX UI     │
                    │ Control Tower   │
                    └────────┬────────┘
                             │
                       REST / WebSocket
                             │
                             ▼
                    ┌─────────────────┐
                    │ FLEETX BACKEND  │
                    │ Registry        │
                    │ Tasks           │
                    │ Events          │
                    │ Orchestration   │
                    └────────┬────────┘
                             │
                         MQTT NETWORK
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
           DRONE            AGV           ROBOT
           AGENT           AGENT          AGENT
              │              │              │
              └──────────────┼──────────────┘
                             │
                      Agentic Intelligence
                             │
                      Safety Validation
                             │
                       Hardware Adapter
🔗 Communication

FLEETX uses different communication mechanisms for different responsibilities:

Layer	Technology	Purpose
Agent Network	MQTT	Agent-to-agent communication
Platform API	REST	Tasks, agents and system operations
Real-time UI	WebSocket	Live dashboard updates
Infrastructure	Docker	Service deployment
Database	PostgreSQL	Platform data infrastructure
Cache / Infrastructure	Redis	Runtime infrastructure

MQTT acts as the communication layer — not as the decision-maker.

🖥️ Control Tower

The FLEETX dashboard provides:

Fleet monitoring
Mission management
Live geographic map
Decision intelligence
Negotiation visibility
Self-healing monitoring
Analytics
Audit trail
System monitoring

The objective is to make autonomous decisions observable and explainable to the operator.

🚀 Why FLEETX?

Traditional approach:

Machine A ──┐
Machine B ──┼── Central Controller
Machine C ──┘

FLEETX approach:

        ┌─────────┐
        │  DRONE  │
        └────┬────┘
             │
      ┌──────┴──────┐
      │ FLEETX      │
      │ AGENT       │
      │ NETWORK     │
      └──────┬──────┘
             │
       ┌─────┴─────┐
       ▼           ▼
     AGV         ROBOT

The focus shifts from controlling individual machines to coordinating a collective fleet.

🛠️ Technology Stack
React
TypeScript
Vite
Tailwind CSS
Leaflet
FastAPI
Python
MQTT / Mosquitto
PostgreSQL
Redis
Docker
Agentic AI
Rule-based planning
Optional LLM planning
📊 Prototype Capabilities

FLEETX currently demonstrates:

Multi-agent registration
Agent heartbeats
Capability advertisement
Decentralized proposals
Negotiation
Task allocation
Cooperative task decomposition
Multi-agent execution
Agentic planning
Failure detection
Replanning
Replacement discovery
Task handoff
Mission recovery
Real-time dashboard
Geographic visualization
Audit trail
🔮 Future Scope

The architecture can be extended toward:

Physical drone integration
ROS2 integration
MAVLink integration
CAN-based vehicle integration
Large-scale fleet deployment
Persistent distributed agent state
Advanced optimization
Multi-site logistics
Edge deployment
Fleet simulation
Digital twins
📚 Documentation
Product Requirements
Agent Architecture
System Architecture
Design System
Security
Code Style
Testing
👥 Project

FLEETX — Decentralized Multi-Agent Coordination for Autonomous Logistics

Built as a prototype for autonomous mobility and intelligent logistics coordination.


**This is the direction I'd take.** The README becomes something a judge/recruiter can open and understand in **60–90 seconds**, rather than having to install Python, Docker, MQTT, etc. first.

And once you deploy the actual FLEETX control tower, we put the real URL into that **🚀 Live Demo** button.
