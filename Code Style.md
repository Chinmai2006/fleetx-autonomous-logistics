# Code Style

## Decentralized Multi-Agent Coordination for Autonomous Logistics

## 1. Purpose

This document defines coding conventions for the project.

The objective is to keep the codebase:

- Readable
- Maintainable
- Testable
- Consistent
- Modular
- Easy for new contributors to understand

---

## 2. General Principles

Follow these principles throughout the project:

- Prefer simple implementations over unnecessary abstraction.
- Keep modules focused on a single responsibility.
- Avoid duplicated business logic.
- Prefer explicit behavior over hidden side effects.
- Keep safety-critical logic deterministic.
- Validate external input at system boundaries.
- Write code that can be independently tested.
- Do not introduce dependencies without a clear reason.

---

## 3. Python Style

The backend and agent runtime are written in Python.

Follow standard Python conventions and PEP 8 where practical.

Use:

- `snake_case` for variables and functions
- `PascalCase` for classes
- `UPPER_SNAKE_CASE` for constants
- Type hints for public functions and important internal interfaces

Example:

```python
class AgentRegistry:
    def register_agent(self, agent_id: str, capabilities: list[str]) -> None:
        ...
4. Type Hints

Use type hints for function parameters and return values.

Preferred:

def get_agent(agent_id: str) -> Agent | None:
    ...

Avoid unnecessarily untyped public functions:

def get_agent(agent_id):
    ...
5. Naming

Names should communicate intent.

Prefer:

agent_id
task_id
assigned_agent_id
required_capabilities
replan_count
replacement_agent

Avoid vague names such as:

data
thing
obj
temp
x
value

unless their meaning is obvious from a very small local scope.

6. Classes

Classes should represent meaningful domain concepts.

Examples:

Agent
AgentRuntime
AgentRegistry
Task
Proposal
Negotiation
PlannerProvider
RuleBasedPlanner
LLMPlanner
AgenticOrchestrator

Keep classes focused on their specific responsibility.

7. Functions

Functions should generally perform one logical operation.

Prefer:

def validate_assignment(...):
    ...

def negotiate_proposals(...):
    ...

def create_handoff_request(...):
    ...

over large functions that perform unrelated operations.

8. Constants

Configuration values and important fixed values should not be scattered throughout the code.

Use constants or configuration where appropriate.

Example:

DEFAULT_HEARTBEAT_INTERVAL = 5

Environment-dependent values should be loaded through configuration/environment variables.

9. Pydantic Models

Pydantic models should be used for structured API and protocol data where appropriate.

Models should clearly represent the expected schema.

Example:

class TaskRequest(BaseModel):
    task_id: str
    required_capabilities: list[str]
    priority: int

Input validation should happen before business logic processes the data.

10. API Design

FastAPI endpoints should remain relatively thin.

Preferred flow:

API Endpoint
     |
     v
Validation
     |
     v
Service / Domain Logic
     |
     v
Result

Business logic should not unnecessarily be embedded directly inside route handlers.

11. Error Handling

Errors should be handled explicitly.

Use appropriate exceptions and HTTP responses.

For API endpoints:

raise HTTPException(
    status_code=422,
    detail="Invalid task configuration",
)

Do not expose internal stack traces or sensitive implementation details to users.

12. Logging

Use structured and meaningful logs.

Logs should help answer:

What happened?
Which agent was involved?
Which task was involved?
What operation was performed?
Why did it fail?

Example:

Task TASK-123 assigned to AGV-01

Avoid logging:

Passwords
API keys
Tokens
Private credentials
Sensitive secrets
13. Agent Runtime Style

Agent runtime code should clearly separate:

Communication
State
Decision Logic
Validation
Execution

Avoid mixing MQTT transport logic with task decision logic when separation is practical.

14. MQTT Code

MQTT communication should use clearly defined protocol messages.

Avoid sending arbitrary unstructured dictionaries when a defined protocol model exists.

Prefer:

Message Type
+
Validated Payload

Each agent should use a unique MQTT client identifier.

15. Protocol Models

Protocol definitions should remain centralized where possible.

Current protocol definitions are maintained under:

protocols/

Changes to protocol schemas should be treated as compatibility-sensitive changes.

When modifying a message:

Update the model.
Update producers.
Update consumers.
Update tests.
Verify existing agents still communicate correctly.
16. Agentic AI Code

Agentic AI code must remain bounded and deterministic where safety is involved.

The intended flow is:

Observe
  ↓
Plan
  ↓
Validate
  ↓
Delegate
  ↓
Observe Result

AI-generated output must pass validation before influencing execution.

Do not create direct AI-to-hardware execution paths.

17. Planner Architecture

Planner implementations should follow the PlannerProvider abstraction.

Examples:

PlannerProvider
├── RuleBasedPlanner
└── LLMPlanner

The deterministic planner should remain available as a fallback.

Planner implementations should not bypass safety or coordination validation.

18. Safety-Critical Logic

Safety logic must remain deterministic.

Examples include:

Capability validation
Battery requirements
Payload limits
Agent availability
Assignment eligibility
Replacement eligibility
Task validation

Do not replace deterministic safety checks with an LLM response.

19. Frontend TypeScript Style

The frontend uses TypeScript.

Prefer:

interface Agent {
  id: string;
  type: string;
  status: string;
  battery: number;
}

Avoid unnecessary use of any.

Prefer explicit types for API responses and component props.

20. React Components

React components should have focused responsibilities.

Examples:

Fleet
AgentCard
TaskDashboard
LiveMap
DecisionIntelligence
Analytics
Audit
System

Avoid creating very large components containing unrelated UI and business logic.

21. React State

Keep state as close as practical to the component or feature that owns it.

Avoid global state unless multiple independent parts of the application genuinely require it.

Important runtime state should ultimately come from backend/platform data rather than hardcoded frontend mock data.

22. API Calls

API communication should be separated from presentation logic where practical.

A component should not contain large amounts of request construction, transformation, error handling, and rendering logic in one block.

Prefer reusable API/service functions.

23. CSS and Styling

Use the project's established styling approach consistently.

Avoid introducing a second styling system for a small feature.

Keep:

Spacing
Typography
Borders
Cards
Status indicators
Buttons
Panels

visually consistent across the dashboard.

24. Comments

Comments should explain intent rather than restating obvious code.

Good:

# Wait briefly for dynamically registered agents to appear in the MQTT registry.

Avoid:

# Loop through agents.
for agent in agents:
    ...

Use comments for non-obvious decisions, safety boundaries, and important implementation constraints.

25. Documentation Strings

Public classes and important functions should have docstrings when their purpose is not immediately obvious.

Example:

def negotiate_proposals(task_id: str) -> NegotiationResult:
    """Evaluate eligible agent proposals for a task."""
26. Tests

New functionality should include appropriate tests.

Tests should cover:

Normal behavior
Invalid input
Failure conditions
Safety constraints
Edge cases
Regression scenarios

Tests should not depend on external services unless they are explicitly integration tests.

27. Test Naming

Test names should describe the behavior being verified.

Preferred:

def test_dynamic_agent_registration_delay_does_not_permanently_fail_replan():
    ...

Avoid vague names:

def test_agent():
    ...
28. Dependency Management

Dependencies should be added only when required.

When adding a dependency:

Add it to the appropriate dependency file.
Verify compatibility.
Test the affected functionality.
Document important configuration requirements.

Avoid unused dependencies.

29. Environment Configuration

Environment-specific configuration should be stored in environment variables.

Use:

.env
.env.example

The .env file should not be committed when it contains secrets or machine-specific configuration.

30. Git Practices

Use focused commits.

Examples:

feat: add decentralized proposal negotiation
fix: handle dynamic agent registration delay
feat: add cooperative task execution
fix: validate agentic task creation errors
docs: add architecture documentation
test: add self-healing regression tests

Avoid committing unrelated changes together.

31. Pull Request / Change Review

Before merging a change, verify:

Existing tests pass.
New functionality is tested.
No secrets are committed.
API changes are intentional.
Protocol changes are compatible.
Safety checks remain intact.
No fake/mock behavior has replaced real functionality.
Documentation is updated where required.
32. Code Quality Rule

The project should prioritize:

Correctness
    ↓
Safety
    ↓
Testability
    ↓
Maintainability
    ↓
Performance
    ↓
Convenience

Complexity should only be introduced when it provides a clear architectural or operational benefit.