# Testing

## Decentralized Multi-Agent Coordination for Autonomous Logistics

## 1. Purpose

Testing ensures that the platform's coordination, communication, safety, agentic workflow, and self-healing behavior work as intended.

The testing strategy covers:

- Unit testing
- Integration testing
- Protocol testing
- Agent communication
- Task allocation
- Negotiation
- Cooperative execution
- Agentic workflows
- Failure recovery
- API behavior
- Frontend build validation

---

## 2. Testing Principles

The project follows these principles:

- Test behavior rather than implementation details.
- Test safety-critical logic deterministically.
- Add regression tests when bugs are fixed.
- Keep unit tests independent from external services where possible.
- Use integration tests for real communication paths.
- Verify that autonomous coordination is based on real runtime state.
- Do not replace real communication with fake UI behavior.

---

## 3. Test Structure

Tests are maintained under:

```text
tests/

The test suite covers multiple layers of the platform.

Conceptually:

Unit Tests
    |
    v
Service / Protocol Tests
    |
    v
Agent Communication Tests
    |
    v
Workflow Tests
    |
    v
End-to-End Validation
4. Unit Tests

Unit tests verify individual components in isolation.

Examples include:

Protocol models
Agent registry logic
Capability validation
Task validation
Proposal validation
Safety validation
Planner behavior
Task decomposition
Handoff eligibility
Agentic state transitions

Unit tests should avoid unnecessary dependencies on running infrastructure.

5. Protocol Testing

Protocol tests verify that messages can be:

Created
Serialized
Published
Received
Parsed
Validated

Important protocol categories include:

HEARTBEAT
AGENT_REGISTRATION
TASK_ANNOUNCEMENT
PROPOSAL
ASSIGNMENT
SUBTASK_ANNOUNCEMENT
SUBTASK_ASSIGNMENT
SUBTASK_STATUS_UPDATE
SUBTASK_COMPLETED
TASK_HANDOFF_REQUEST
TASK_HANDOFF_ACCEPT
TASK_HANDOFF_REJECT

Changes to protocol schemas should include regression tests.

6. Agent Communication Tests

Agent communication tests verify that independent agent processes can communicate through MQTT.

The test should verify:

Agent A
   |
   v
MQTT
   |
   v
Agent B

The communication path should use the same protocol mechanism as the actual runtime.

7. Heartbeat Testing

Agents periodically publish heartbeat information.

The test suite should verify:

Heartbeats are published.
Agent state is updated.
Missing heartbeats are detected.
Stale agents become unavailable/offline according to the configured rules.

Heartbeat behavior is important for failure detection and self-healing.

8. Agent Registration Testing

Registration tests verify:

New agents can be registered.
Agent IDs are handled correctly.
Capabilities are recorded.
Agent properties are validated.
Invalid registration requests are rejected.
Registered agents become available to coordination.

Dynamic registration should also be tested.

9. Task Testing

Task tests verify the complete task lifecycle.

Example:

ANNOUNCED
    ↓
PROPOSALS
    ↓
NEGOTIATION
    ↓
ASSIGNED
    ↓
IN_PROGRESS
    ↓
COMPLETED

Failure paths should also be tested.

10. Proposal Testing

Proposal tests verify that agents calculate and publish proposals using relevant operational factors.

These can include:

Capability match
Battery
Payload
Workload
Distance
Estimated cost
Priority
Deadline

The proposal should be validated before being used in negotiation.

11. Negotiation Testing

Negotiation tests verify:

Multiple proposals can be received.
Invalid proposals are rejected.
Eligible proposals are preserved.
Negotiation produces an assignment when valid candidates exist.
The backend does not silently discard valid proposals.
Assignment remains subject to deterministic validation.

Regression tests should be added for previously identified proposal-validation issues.

12. Cooperative Mission Testing

Cooperative mission tests verify that a parent mission can be decomposed into subtasks.

Example:

Parent Mission
 |
 +-- Pickup
 |
 +-- Transport
 |
 +-- Delivery

The test should verify that different agents can be assigned to the appropriate subtasks.

The complete parent mission should reach completion only when the required subtasks are completed.

13. Handoff Testing

Handoff tests verify recovery when an assigned agent becomes unavailable.

Example:

AGV-01
  |
  X
Failure
  |
  v
AGV-02
  |
  v
Handoff
  |
  v
Mission Resumes

The replacement agent must satisfy the relevant task requirements.

14. Agentic Workflow Testing

The agentic workflow follows:

OBSERVE
   ↓
PLAN
   ↓
VALIDATE
   ↓
DELEGATE
   ↓
OBSERVE_RESULT

Tests should verify each state transition and the conditions that cause the workflow to move between states.

15. Agentic Failure Testing

The agentic workflow must be tested against:

Unavailable agents
Invalid plans
Failed assignments
Failed subtasks
Missing replacement agents
Replanning limits
Invalid AI output

The system should fail safely when a plan cannot be validated.

16. Self-Healing Testing

Self-healing tests verify:

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

Tests should verify both successful and unsuccessful recovery.

17. Dynamic Registration Regression Test

A specific regression test verifies that a dynamically registered replacement agent has enough time to appear in the runtime registry before the recovery workflow permanently fails.

The recovery mechanism waits for an eligible replacement within a bounded period.

This prevents a timing race between:

Agent Registration

and:

Self-Healing Replacement Discovery
18. Single-Agent Task Failure Testing

Single-agent tasks must also be monitored for failure.

The system must not rely only on cooperative subtasks to detect task failure.

Tests should verify:

Single Task
    ↓
Assigned Agent
    ↓
Agent Failure
    ↓
Failure Detection
    ↓
Recovery / Rejection
19. API Testing

API tests verify:

Valid requests
Invalid requests
Authentication
Authorization
Validation errors
Resource-not-found cases
Successful responses
Error response formats

API failures should return structured JSON responses where appropriate.

20. Authentication Testing

Security tests should verify:

Protected endpoints reject unauthenticated requests.
Operator access works for permitted operations.
Admin-only operations reject operator-level access.
Invalid tokens are rejected.
Public endpoints remain accessible only where intentionally designed.
21. Safety Testing

Safety validation must be tested independently from AI behavior.

Examples:

Invalid Capability
      ↓
Rejected

Insufficient Battery
      ↓
Rejected

Payload Exceeds Limit
      ↓
Rejected

Unavailable Agent
      ↓
Rejected

AI-generated recommendations must not bypass these checks.

22. LLM Planner Testing

When an LLM planner is enabled, tests should verify:

Valid model output is accepted.
Invalid model output is rejected.
Malformed output does not crash the API.
Safety validation still executes.
Deterministic fallback works when the LLM is unavailable.
LLM output cannot directly control hardware.

LLM tests should use mocked model responses rather than depending on an external API for every test run.

23. Frontend Testing

Frontend validation should verify:

Application builds successfully.
Main views render correctly.
API errors are handled.
Agent states are displayed correctly.
Mission states are displayed correctly.
Self-healing progress is visible.
Live map functionality loads correctly.
Protected controls behave according to authorization state.
24. Build Testing

Before committing frontend changes:

npm run build

A successful production build confirms that the frontend compiles and bundles successfully.

25. Integration Testing

Integration tests verify interactions between multiple platform components.

Examples:

Agent
  ↓
MQTT Broker
  ↓
Backend
  ↓
Task / Registry
  ↓
Frontend

Integration tests should be used where component interaction is more important than isolated behavior.

26. End-to-End Demo Validation

Before a major demonstration, verify the complete operational path.

Recommended sequence:

Start Infrastructure
        ↓
Start Backend
        ↓
Start Agents
        ↓
Verify Fleet
        ↓
Create Mission
        ↓
Proposal
        ↓
Negotiation
        ↓
Assignment
        ↓
Execution
        ↓
Completion

For cooperative missions:

Mission
   ↓
Decomposition
   ↓
Pickup
   ↓
Transport
   ↓
Delivery
   ↓
Mission Complete

For self-healing:

Mission
   ↓
Agent Failure
   ↓
Failure Detection
   ↓
Replan
   ↓
Replacement
   ↓
Handoff
   ↓
Resume
27. Regression Testing

Every bug that affects system behavior should ideally receive a regression test.

Examples of previously covered regression areas include:

Pydantic version compatibility
Agent registration timing
Proposal validation
Proposal preservation during negotiation
Agentic task API error handling
Single-task failure detection
Dynamic replacement discovery
Self-healing workflow
28. Current Test Baseline

The current project test baseline is:

81 tests passed
2 warnings

This baseline should be treated as the known validated state at the time of documentation.

Future changes should maintain or intentionally update this baseline.

29. Test Completion Criteria

A feature is considered ready when:

Core functionality works.
Relevant unit tests pass.
Integration behavior is verified where required.
Failure paths are tested.
Safety validation is tested.
No known regression is introduced.
Frontend production build succeeds where frontend changes are involved.
Documentation is updated when architecture or behavior changes.
30. Testing Philosophy

The project should follow:

BUILD
  ↓
TEST
  ↓
EXPLAIN
  ↓
REVIEW
  ↓
LOCK
  ↓
NEXT PHASE

The objective is not simply to achieve a passing test count.

The objective is to demonstrate that autonomous coordination is:

Real
Deterministic where safety matters
Testable
Observable
Recoverable
Explainable