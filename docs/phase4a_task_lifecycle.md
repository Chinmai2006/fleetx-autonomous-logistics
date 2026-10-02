# Phase 4A Task Lifecycle

The operator creates tasks through `POST /api/v1/tasks`. The backend publishes a typed `TASK_ANNOUNCEMENT` on `logistics/broadcast/tasks`; independent agents evaluate their own capability, availability, battery, and payload constraints and publish a typed `TASK_PROPOSAL` or `TASK_REJECT` on `logistics/tasks/responses`.

The backend collects responses for a one-second proposal window. The deterministic allocator rechecks each proposer against current registry state, including online status, availability, battery (at least 20%), required capabilities, and payload capacity. If multiple agents remain eligible, the lexicographically smallest `agent_id` wins. The backend publishes `TASK_ASSIGNMENT` to `logistics/agents/{agent_id}/events`; only that agent retains the task and publishes `TASK_STATUS_UPDATE`.

This coordinator is intentionally a replaceable allocation boundary. Negotiation, auctions, optimization, and coalition behavior are outside Phase 4A.