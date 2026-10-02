# Architecture

## Decentralized Multi-Agent Coordination for Autonomous Logistics

## 1. System Overview

The platform is a decentralized multi-agent logistics coordination system for heterogeneous autonomous machines.

The system allows different autonomous machines to operate as independent agents while coordinating tasks through a shared communication protocol.

Supported agent types include:

- Drone
- Autonomous Ground Vehicle (AGV)
- Robot

The architecture separates:

1. User interface
2. Platform infrastructure
3. Agent communication
4. Agent intelligence
5. Safety and deterministic validation
6. Physical hardware integration

---

## 2. High-Level Architecture

```text
                         HUMAN / OPERATOR
                                |
                                v
                    +-----------------------+
                    |     WEB DASHBOARD     |
                    |-----------------------|
                    | Fleet Management      |
                    | Mission Management    |
                    | Live Map              |
                    | Decision Intelligence |
                    | Analytics             |
                    | Audit                 |
                    +-----------+-----------+
                                |
                         REST / WebSocket
                                |
                                v
              +--------------------------------------+
              |        PLATFORM INFRASTRUCTURE       |
              |--------------------------------------|
              | Agent Registry                       |
              | Authentication / Authorization       |
              | Task Management                      |
              | Event Management                     |
              | Monitoring / Logging                 |
              +------------------+-------------------+
                                 |
                          Agent Protocol
                                 |
                                 v
                       +----------------+
                       | MQTT NETWORK   |
                       | Communication  |
                       +-------+--------+
                               |
              +----------------+----------------+
              |                |                |
              v                v                v
        +-----------+    +-----------+    +-----------+
        |   DRONE   |    |    AGV    |    |  ROBOT   |
        |   AGENT   |    |   AGENT   |    |   AGENT  |
        +-----+-----+    +-----+-----+    +-----+-----+
              |                |                |
              v                v                v
        Agent Runtime    Agent Runtime    Agent Runtime
              |                |                |
              v                v                v
          Agentic AI       Agentic AI       Agentic AI
              |                |                |
              v                v                v
        Decision /        Decision /        Decision /
        Optimization      Optimization      Optimization
              |                |                |
              v                v                v
        Safety Layer      Safety Layer      Safety Layer
              |                |                |
              v                v                v
        Hardware Adapter  Hardware Adapter  Hardware Adapter
              |                |                |
              v                v                v
           Hardware         Hardware         Hardware
3. Architectural Principles
Decentralized Coordination

Agents independently evaluate tasks and submit proposals.

The backend coordinates protocol-level validation and system state but does not act as the sole decision-maker for task allocation.

Heterogeneous Agents

Different machines can have different:

Capabilities
Payload capacities
Battery levels
Locations
Operating constraints
Hardware interfaces
Agent Independence

Each agent runs as an independent process.

Agents communicate through the defined protocol rather than directly depending on another agent's internal implementation.

Safety First

Agentic AI can propose plans and decisions but cannot bypass deterministic safety validation.

Protocol-Based Communication

MQTT is used for agent-to-agent communication and event exchange.

REST APIs are used for platform interaction.

WebSocket communication supports real-time dashboard updates.

4. Frontend Architecture

The frontend is implemented using:

React
TypeScript
Vite
Tailwind CSS
Leaflet

The frontend provides the operational control tower.

Major areas include:

frontend/
├── Overview
├── Fleet
├── Missions
├── Live Map
├── Decision Intelligence
├── Analytics
├── Audit
└── System

The frontend communicates with backend APIs rather than directly controlling physical machines.

5. Backend Architecture

The backend is implemented using FastAPI.

Major responsibilities include:

Agent registration
Agent discovery
Agent state tracking
Task management
Proposal processing
Negotiation coordination
Mission decomposition
Agentic workflow orchestration
Safety validation
Event management
Monitoring
Authentication and authorization

Backend structure:

backend/
└── app/
    ├── api/
    ├── core/
    ├── services/
    └── main.py
6. Agent Architecture

Each autonomous machine runs an agent runtime.

Agent
 |
 +-- Agent Runtime
 |
 +-- Agent State
 |
 +-- Capability Advertisement
 |
 +-- Task Handling
 |
 +-- Proposal Generation
 |
 +-- Negotiation
 |
 +-- Agentic Planning
 |
 +-- Safety Validation
 |
 +-- MQTT Communication
 |
 +-- Hardware Adapter

The agent runtime is responsible for representing the machine as an autonomous participant in the logistics network.

7. Agent Communication

MQTT is the initial communication transport between agents and the platform.

Conceptually:

Agent
  |
  v
MQTT Publisher / Subscriber
  |
  v
MQTT Broker
  |
  +----> Agent
  +----> Agent
  +----> Platform

MQTT provides message transport and routing.

It does not make operational decisions.

8. REST API

REST is used for platform-level operations.

Typical operations include:

Register agent
Retrieve fleet
Create task
Retrieve task
Retrieve task status
Start agentic workflow
Retrieve workflow status
Access monitoring information

The REST API acts as the interface between the dashboard and platform services.

9. WebSocket Layer

WebSocket communication is used where real-time dashboard updates are required.

Potential real-time information includes:

Agent status
Task state
Mission progress
Events
Negotiation activity
Self-healing activity
10. Task Allocation Architecture

Task allocation follows a proposal and negotiation model.

Task
 |
 v
Task Announcement
 |
 v
Eligible Agents
 |
 +----> Agent Proposal
 |
 +----> Agent Proposal
 |
 +----> Agent Proposal
 |
 v
Safety / Eligibility Validation
 |
 v
Negotiation
 |
 v
Assignment

Agent proposals can consider:

Capability
Battery
Payload
Workload
Distance
Cost
Priority
Deadline

The resulting assignment must pass deterministic validation.

11. Cooperative Task Architecture

A complex mission can be decomposed into multiple subtasks.

Example:

Mission
 |
 +-- Pickup
 |
 +-- Transport
 |
 +-- Delivery

Different agents can be assigned to different subtasks.

Example:

ROBOT-01
   |
   +-- Pickup

AGV-01
   |
   +-- Transport

DRONE-01
   |
   +-- Delivery

This enables heterogeneous machines to cooperate within one logistics workflow.

12. Agentic AI Architecture

The agentic layer follows a bounded state-machine workflow:

OBSERVE
   |
   v
PLAN
   |
   v
VALIDATE
   |
   v
DELEGATE
   |
   v
OBSERVE RESULT
   |
   +------> REPLAN

The agentic system can:

Inspect fleet state
Inspect capabilities
Inspect tasks
Create validated plans
Request negotiation
Request handoff
Observe workflow results
Trigger bounded replanning

The system does not provide a tool that directly commands physical hardware.

13. Planner Architecture

The platform supports a planner abstraction.

PlannerProvider
      |
      +---- RuleBasedPlanner
      |
      +---- LLMPlanner

The deterministic planner provides a fallback when an LLM planner is unavailable.

The LLM planner is therefore an optional intelligence layer rather than a mandatory dependency for core operation.

14. Safety Architecture

Safety validation is deterministic.

The execution flow is:

AI Proposal
     |
     v
Deterministic Validation
     |
     +---- Rejected
     |
     +---- Accepted
             |
             v
        Negotiation
             |
             v
          Execute

The AI layer cannot override safety constraints.

Safety checks can include:

Capability requirements
Battery constraints
Payload constraints
Agent availability
Task validity
Assignment eligibility
Operational constraints
15. Self-Healing Architecture

The platform supports bounded self-healing for agent failures.

Agent Failure
      |
      v
Failure Detection
      |
      v
Risk Assessment
      |
      v
Replanning
      |
      v
Replacement Discovery
      |
      v
Negotiation
      |
      v
Task Handoff
      |
      v
Mission Resumption

Replanning is bounded to prevent uncontrolled recovery loops.

The current configuration limits agentic replanning using:

AGENTIC_MAX_REPLANS
16. Dynamic Agent Registration

Agents can be added dynamically to the fleet.

The registration process is:

New Agent
   |
   v
Agent Registration
   |
   v
Capability Advertisement
   |
   v
Registry
   |
   v
Available for Coordination

The runtime can therefore discover replacement agents without requiring the platform to be rebuilt.

17. Failure and Replacement

When an assigned agent becomes unavailable:

Assigned Agent
      |
      X
   Failure
      |
      v
Detect Failure
      |
      v
Find Eligible Replacement
      |
      v
Negotiation
      |
      v
Handoff
      |
      v
Resume Mission

Replacement eligibility is checked against the task requirements and available agent capabilities.

18. Hardware Abstraction

Physical machines are separated from the coordination layer through hardware adapters.

Conceptually:

Physical Machine
       |
       v
MAVLink / ROS2 / CAN / Other Interface
       |
       v
Hardware Adapter
       |
       v
Agent Runtime
       |
       v
MQTT

This allows the coordination platform to remain independent of a specific physical machine implementation.

19. Infrastructure

The development environment uses containerized infrastructure.

Primary services include:

PostgreSQL
Redis
Mosquitto MQTT
FastAPI Backend
React Frontend

Docker Compose is used to manage the development environment.

PostgreSQL and Redis are infrastructure components available to the platform, while the current agentic execution state is maintained in memory.

20. Data and Runtime State

The architecture distinguishes between persistent infrastructure and runtime coordination state.

Runtime information includes:

Active agents
Agent status
Active missions
Agentic workflow states
Negotiation activity
Recovery state

The current agentic orchestration state is in-memory.

This should be considered when designing future persistence and horizontal scaling.

21. Scalability

The architecture is designed to support future scaling through:

Independent agent processes
MQTT-based communication
Stateless API design where practical
Separate agent runtime from physical hardware
Pluggable planner architecture
Event-driven communication
Containerized services

Future deployments can introduce:

MQTT clustering
Distributed state storage
Persistent event storage
Multiple backend instances
Kubernetes
Distributed task scheduling

without changing the fundamental agent communication model.

22. Technology Stack
Layer	Technology
Frontend	React + TypeScript
Build Tool	Vite
Styling	Tailwind CSS
Maps	Leaflet + OpenStreetMap
Backend	FastAPI
Language	Python
Agent Communication	MQTT
MQTT Broker	Mosquitto
Database Infrastructure	PostgreSQL
Cache / Infrastructure	Redis
Containerization	Docker Compose
Agent Intelligence	Rule-Based Planner + Optional LLM Planner
Agentic Workflow	Bounded State Machine
23. Architectural Safety Boundary

The most important architectural boundary is:

                 AGENTIC AI
                     |
              Propose / Reason
                     |
                     v
        DETERMINISTIC SAFETY LAYER
                     |
              Validate / Reject
                     |
                     v
              COORDINATION LAYER
                     |
                 Assignment
                     |
                     v
              HARDWARE ADAPTER
                     |
                     v
              PHYSICAL MACHINE

Agentic AI is therefore an intelligence and planning layer, not a direct physical-control layer.