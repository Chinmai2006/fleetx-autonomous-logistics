# Decentralized Multi-Agent Coordination Platform

An autonomous, resilient logistics & multi-agent coordination platform built for decentralized fleet optimization, agent negotiation, dynamic routing, and real-time infrastructure monitoring.

---

## 🏗️ Architecture (Phase 1 — Foundation)

Phase 1 establishes core project layout, environment management, container configuration, and infrastructure health monitoring across:
- **Backend API**: FastAPI (Python 3.11) with async health checks.
- **Frontend Dashboard**: React + TypeScript + Vite + Tailwind CSS live telemetry UI.
- **Databases & Messaging**:
  - PostgreSQL 16 (Primary relational storage)
  - Redis 7 (Caching, pub/sub, agent lock coordination)
  - Eclipse Mosquitto 2.0 (MQTT telemetry broker)

---

## 🚀 Quick Start

### 1. Using Docker Compose (Recommended)

Run all services (Database, Redis, MQTT Broker, Backend API, Frontend Dashboard):

```bash
docker-compose up -d --build
```

Access services:
- **Frontend Dashboard**: `http://localhost:3000`
- **Backend API Docs**: `http://localhost:8000/docs`
- **Health Check Endpoint**: `http://localhost:8000/api/v1/health`

---

### 2. Manual Local Development

#### Backend Setup
```bash
cd backend
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

#### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

---

## 🧪 Testing

Run backend integration tests:
```bash
cd backend
pytest
```

Build frontend TypeScript bundle:
```bash
cd frontend
npm run build
```

---

## Autonomous Logistics Control Tower

The dashboard supports a dynamic fleet, independent managed `AgentRuntime` processes, cooperative missions, optional Agentic AI, local-coordinate routing, deterministic dispatch decisions, operational risk/health, self-healing, audit events, and live analytics. Dynamic agents publish registration, capabilities, state, and heartbeats through MQTT; they are not inserted into the registry as simulated rows.

### Run on Windows PowerShell

```powershell
Copy-Item .env.example .env
```

Set unique operator/admin tokens in `.env` before enabling agent management:

```text
API_OPERATOR_TOKEN=<long-random-operator-token>
API_ADMIN_TOKEN=<different-long-random-admin-token>
```

Start the stack and run tests:

```powershell
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://localhost:8000/api/v1/health
& ./.venv-win/Scripts/python.exe -m pytest tests/ -v
npm --prefix frontend run build
```

The control tower is at `http://localhost:3000`; Swagger is at `http://localhost:8000/docs`.

### Register a Real Agent

Agent creation requires the admin token. The agent runs as an independent process and becomes visible only after its MQTT registration is received.

```powershell
$agent = @{
  agent_id = "ROBOT-WEST-02"
  agent_type = "ROBOT"
  capabilities = @("bin_picking", "barcode_scanning")
  payload_capacity_kg = 30
  battery_pct = 92
  location = @{ x = 12; y = 8; z = 0 }
  available = $true
  operational_constraints = @{ minimum_battery_pct = 25; maximum_distance_km = 40 }
  metadata = @{ site = "west-warehouse" }
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Uri http://localhost:8000/api/v1/agents `
  -Method Post -ContentType "application/json" `
  -Headers @{ Authorization = "Bearer $env:API_ADMIN_TOKEN" } -Body $agent
```

The same API supports listing managed processes, activation, deactivation, and archival. Operators can read fleet/task telemetry; agent process management and audit/decision history require configured bearer tokens. The frontend keeps the entered token in page memory only.

### Operational APIs

- `GET /api/v1/agents`, `POST /api/v1/agents`, and `/api/v1/agents/{id}/activate|deactivate` manage live fleet identity and process state.
- `POST /api/v1/routes/plan` calculates a route from explicit local coordinates or a caller-supplied distance. No road graph or traffic provider is implied.
- `POST /api/v1/routes/optimize` and `POST /api/v1/decisions/evaluate` return scored candidates and concise decision factors; final task allocation remains with decentralized MQTT negotiation.
- `GET /api/v1/risks`, `/api/v1/agents/health`, `/api/v1/self-healing`, `/api/v1/audit`, and `/api/v1/analytics/fleet` expose current live state and bounded in-memory records.
- `GET /api/v1/analytics/missions/{task_id}` reports timing and mission lifecycle metrics where audit timestamps exist.

### Broker Security

`mosquitto.conf` allows anonymous access for local development only. Do not expose that configuration to untrusted networks. `mosquitto.tls.conf.example` and `mosquitto.acl.example` show a TLS/password/ACL starting point; provision password hashes with `mosquitto_passwd`, use per-agent identities, create least-privilege ACL entries for every agent, mount real certificates, and set `MOSQUITTO_CONFIG`, `MOSQUITTO_PASSWORD_FILE`, `MOSQUITTO_ACL_FILE`, `MOSQUITTO_CERTS_DIR`, `MQTT_BROKER_PORT`, and backend MQTT TLS settings before deployment. The examples are not a production security certification.

### Prototype Limits

- Registry/task state, audit events, decisions, and self-healing records are in memory and reset when their owning process restarts.
- Coordinates are local `x/y/z` values; the Leaflet view does not geocode or represent streets. Unknown routes require an explicit distance or coordinates.
- Route estimates use an explicitly supplied distance or local Euclidean distance and configured average speed. No real-time traffic, road-network routing, or predictive maintenance ML is integrated.
- MQTT anonymous mode remains the local-development default; configure broker credentials, ACLs, and TLS before exposing the broker.

---

## 📂 Repository Structure

```
autonomous-logistics-platform/
├── adapters/          # Hardware & external interface adapters (stubs)
├── agents/            # Autonomous agent logic & state machines (stubs)
├── algorithms/        # Pathfinding & task negotiation algorithms (stubs)
├── backend/           # FastAPI backend service
│   ├── app/
│   │   ├── api/       # API routers & endpoints
│   │   ├── core/      # Application settings & configuration
│   │   └── main.py    # Application entry point
│   ├── Dockerfile
│   └── requirements.txt
├── docs/              # Architectural documentation
├── frontend/          # Vite + React + TypeScript + Tailwind CSS UI
│   ├── src/
│   │   ├── components/# Health dashboard & UI widgets
│   │   ├── App.tsx
│   │   └── main.tsx
│   └── Dockerfile
├── protocols/         # P2P and MQTT message schemas (stubs)
├── tests/             # Backend & integration test suite
├── docker-compose.yml # Container orchestration
├── mosquitto.conf     # MQTT configuration
└── README.md
```
