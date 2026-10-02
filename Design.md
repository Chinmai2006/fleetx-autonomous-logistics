# Design System

## Decentralized Multi-Agent Logistics Control Tower

## 1. Purpose

The Design System defines the visual and interaction principles used by the logistics control-tower dashboard.

The interface is designed around an operational mission-control experience where an operator can quickly understand:

- Fleet status
- Active missions
- Agent availability
- Task assignments
- Negotiation decisions
- Failures
- Recovery actions
- System health

The design prioritizes operational clarity, information density, consistency, and explainability.

---

# 2. Design Philosophy

The dashboard follows a control-tower / mission-control visual language.

The interface should make complex multi-agent activity understandable without hiding important system information.

The primary principles are:

### Operational Clarity

Important operational information should be immediately visible.

### State Visibility

Agent and mission states should always be explicit.

### Explainability

The interface should expose why an agent was selected and how the system responded to failures.

### Consistency

Similar objects should use consistent components, labels, status indicators, and interaction patterns.

### Progressive Detail

High-level views provide summaries while detailed views expose proposals, negotiations, events, and reasoning.

### Real-Time Awareness

Fleet and mission information should reflect the current runtime state of the platform.

---

# 3. Application Structure

The control tower is organized into the following major views:

```text
Overview
Fleet
Missions
Live Map
Decision Intelligence
Analytics
Audit
System

Each view represents a different operational aspect of the autonomous logistics network.

# 4. Overview

The Overview provides a high-level operational summary.

It is intended to answer:

How many agents are online?
How many missions are active?
How many missions are completed?
Are negotiations occurring?
Has replanning occurred?
Are there active alerts?
Is the platform healthy?

Typical operational metrics include:

Online agents
Active missions
Completed missions
Negotiations
Replans
Alerts
5. Fleet View

The Fleet view provides visibility into the autonomous machine network.

Each agent is represented with information such as:

Agent ID
Agent type
Current status
Availability
Battery
Capabilities
Payload capacity
Location

Example agent types:

DRONE
AGV / VEHICLE
ROBOT

The Fleet interface also provides agent-management functionality, including adding agents to the runtime fleet.

6. Agent Status Representation

Agent status should be immediately understandable.

Typical states include:

ONLINE
IDLE
BUSY
OFFLINE
FAILED

The interface should distinguish between:

Agent connectivity
Operational state
Failure state

For example, an agent may be online but currently busy executing a task.

7. Missions View

The Missions view provides mission creation and monitoring.

Operators can inspect:

Task ID
Task type
Origin
Destination
Payload
Required capabilities
Assigned agent
Task status
Negotiation status
Proposal information
Subtasks
Completion state
Failure/recovery state
8. Cooperative Mission Visualization

Cooperative missions can contain multiple subtasks.

The interface represents the relationship between a parent mission and its subtasks.

Example:

Parent Mission
│
├── Pickup
│   └── ROBOT-01
│
├── Transport
│   └── AGV-01
│
└── Delivery
    └── DRONE-01

This makes multi-agent cooperation visible to the operator.

9. Self-Healing Interface

Self-healing is represented as an explicit operational sequence.

FAILURE DETECTED
        ↓
RISK ASSESSMENT
        ↓
REPLAN
        ↓
REPLACEMENT
        ↓
NEGOTIATION
        ↓
HANDOFF
        ↓
RESUMED

The interface should make the current recovery stage visible.

Important recovery information includes:

Failed agent
Affected task
Failure reason
Replan count
Replacement candidate
Handoff status
Final recovery outcome
10. Decision Intelligence

Decision Intelligence exposes information behind task allocation.

The interface can display:

Candidate agents
Capability match
Battery score
Payload score
Workload score
Distance score
Priority score
Deadline score
Estimated cost
Utility
Decision reason

Example:

Candidate Agent
      ↓
Capability Match
      ↓
Operational Factors
      ↓
Utility
      ↓
Negotiation
      ↓
Assignment

The purpose is not only to show which agent was selected, but to provide visibility into the factors involved in the decision.

11. Live Map

The Live Map provides geographic visualization of the logistics environment.

The implementation uses:

Leaflet
OpenStreetMap

The map can represent:

Agent locations
Logistics locations
Warehouses
Routes
Mission locations

The map provides spatial context for fleet operations.

12. Route Visualization

The dashboard supports route visualization for logistics scenarios.

Example route concepts include:

Warehouse → Loading Bay
Receiving → Dispatch
Cold Storage → Staging

Routes provide visual context for the current logistics workflow.

13. Analytics

The Analytics view provides aggregate operational information.

Examples include:

Fleet activity
Mission activity
Agent utilization
Negotiation activity
Replanning activity
Recovery activity

Analytics are derived from the platform's current runtime state.

14. Audit View

The Audit view provides an event-oriented representation of important system activity.

Events can include:

Agent registration
Agent heartbeat
Task announcement
Proposal received
Proposal rejected
Negotiation
Assignment
Subtask assignment
Task failure
Replanning
Handoff
Task completion

The audit view supports traceability of autonomous coordination decisions.

15. System View

The System view provides system-level information and controls.

Role-protected operations are subject to backend authorization.

Administrative functions may require administrator credentials while operational functions can use operator-level authorization.

16. Status and State Design

Operational states should be represented consistently throughout the application.

Important state categories include:

Agent States
ONLINE
IDLE
BUSY
OFFLINE
FAILED
Task States
ANNOUNCED
IN_PROGRESS
ASSIGNED
COMPLETED
FAILED
Agentic States
OBSERVE
PLAN
VALIDATE
DELEGATE
OBSERVE_RESULT
Self-Healing States
FAILURE DETECTED
RISK ASSESSMENT
REPLAN
REPLACEMENT
NEGOTIATION
HANDOFF
RESUMED

The UI should avoid ambiguous status terminology.

17. Forms and Controls

Forms should clearly communicate:

Required fields
Optional fields
Validation errors
Current values
Allowed values
Submission state

Agent registration forms should capture the operational information required by the backend.

Mission creation forms should capture the information required to create a valid task.

18. Tables and Data Panels

Tables and data panels should prioritize operational information.

Important information should appear before secondary metadata.

Examples:

Agent ID
Status
Battery
Capabilities
Task

Detailed metadata can be exposed through expandable or secondary sections where appropriate.

19. Notifications and Alerts

Alerts should communicate actionable operational information.

Examples:

Agent unavailable
Task failure
Replacement required
Mission completed
System service issue

Alerts should clearly distinguish between:

Informational events
Warnings
Failures
Successful recovery
20. Component Principles

The frontend is implemented using React and TypeScript.

Reusable components should be preferred for:

Navigation
Cards
Panels
Tables
Forms
Status indicators
Mission displays
Agent displays
Analytics
Maps
Audit information

Components should avoid unnecessary duplication.

21. Interaction Principles
Immediate Feedback

Actions such as creating a mission or registering an agent should provide clear feedback.

State Preservation

Refreshing or navigating between views should not unnecessarily hide the current operational state.

Error Visibility

Backend or validation errors should be communicated clearly.

Operator Awareness

The interface should never silently change an important operational state without making the change visible.

22. Accessibility and Usability

The dashboard should maintain:

Clear labels
Readable text
Distinguishable states
Consistent controls
Predictable navigation
Clear error messages

Operationally important information should not rely solely on color.

23. Design Principle for Autonomous Decisions

The UI should distinguish between:

Agent Proposal
        ↓
Deterministic Validation
        ↓
Accepted / Rejected

This distinction is important because an agentic recommendation is not equivalent to an authorized action.

24. Future Design Extensions

Potential future UI capabilities include:

3D fleet visualization
Real-time telemetry dashboards
Physical machine camera feeds
ROS2 telemetry visualization
Advanced mission simulation
Historical mission replay
Large-fleet visualization
Advanced operator workflows

Once you've created **`Design System.md`**, just say **“next”** and I'll give you **`Architecture.md` only**.