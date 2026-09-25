# Job System

A distributed system for running Jobs on remote Agents.

A user submits a Job via HTTP. The system routes it to a specific Agent inside a Datacenter it cannot reach directly. The Agent runs the Job as a Docker container and streams logs and results back. The system guarantees that Jobs are never lost, never duplicated, and never stuck — even across network drops, Agent restarts, and Server restarts.

---

## Table of Contents

- Architecture
- Roadmap
- Phase 1 — MVP
- Phase 2 — Reliability
- Phase 3 — Scale
- Phase 4 — Delivery
- The Job Record as a Durable PCB
- Communication Design
- Design Decisions
- State Machine Details
- Failure Model
- Scheduling Policy
- Tech Stack
- Quick Start
- Evidence

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                          USER                               │
│              (CLI, curl, or any HTTP client)                │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST + WebSocket / SSE
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    CONTROL PLANE (Server)                   │
│                                                             │
│   REST API   │   Live Log Streamer   │   Agent Gateway      │
│                                                             │
│   ─────────────────────────────────────────────────────    │
│                                                             │
│              Job Orchestrator / State Machine               │
│   Routing │ Idempotency │ Timeout │ Ack │ Reconcile         │
│                                                             │
│   ─────────────────────────────────────────────────────    │
│                                                             │
│                     Persistence Layer                       │
│         Jobs │ Agents │ Logs │ Events │ Idempotency         │
└───────────────────────────┬─────────────────────────────────┘
                            │ Outbound WebSocket
                            │ (Agent-initiated only)
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  Datacenter A │   │  Datacenter B │   │  Datacenter C │
│   [Agent 1]   │   │   [Agent 2]   │   │   [Agent 3]   │
│    Docker     │   │    Docker     │   │    Docker     │
└───────────────┘   └───────────────┘   └───────────────┘
```

**Core constraint:** The Server cannot reach the Agents. Each Agent opens an outbound WebSocket to the Server and stays connected. All Job dispatch, logs, and results flow through that connection.

**Boundary:** The Boundary between the Server and the Agents is the WebSocket connection itself. Everything on the Server side of the WebSocket is trusted and under the Server's control. Everything beyond the WebSocket is the Agent's responsibility: Docker, the container, the local filesystem, and the local network. The Server never reaches across the Boundary; it only sends messages and receives messages. This is what makes the system work behind NAT and firewalls.

---

## Roadmap

The project is delivered in four phases. Each phase is a milestone, a PR, and a working demo. Each phase leaves the repository in a submittable state.

| Phase | Focus | Status |
|-------|-------|--------|
| **Phase 1** | MVP — prove the core | ☑ |
| **Phase 2** | Reliability — survive failures | ☑ |
| **Phase 3** | Scale — multi-Agent and scheduling | ☐ |
| **Phase 4** | Delivery — observability and docs | ☐ |

---

## Phase 1 — MVP

### Objective

Prove the hardest part: reliably dispatching a Job from a Server to an Agent that the Server cannot reach, and getting the result back.

### What It Delivers

A working end-to-end system where a user submits a Job over HTTP, the Server routes it to a connected Agent, the Agent runs it as a Docker container, and the user retrieves the result.

### Capabilities

| Capability | Description |
|------------|-------------|
| HTTP API | `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/result` |
| Agent Gateway | WebSocket server accepting outbound Agent connections |
| Job routing | Dispatch a Job to a specific `agentId` |
| Docker execution | Agent runs the Job inside a container |
| Job lifecycle | `PENDING → DISPATCHED → RUNNING → SUCCEEDED / FAILED` |
| Idempotency | Duplicate `idempotencyKey` returns the existing Job |
| Async submission | `POST /jobs` returns immediately with `jobId`; HTTP does not block |
| Race-free transitions | Per-Agent dispatch lock, atomic idempotency, compare-and-swap state transitions |

### Job Submission Fields

Every Job submission must include:

| Field | Required | Purpose |
|-------|----------|---------|
| `agentId` | yes | Which Agent should run the Job |
| `image` | yes | Docker image to use |
| `command` | yes | Command or script to execute |
| `timeoutMs` | yes | Maximum runtime before the Job is `TIMED_OUT` |
| `idempotencyKey` | yes | Prevents duplicate execution of the same request |
| `metadata` | no | Arbitrary user data attached to the Job |

### State Machine

```
       submit
         │
         ▼
     ┌─────────┐   agent online    ┌────────────┐
     │ PENDING │──────────────────▶│ DISPATCHED │
     └─────────┘                   └─────┬──────┘
         ▲                               │ agent started
         │ agent offline                 ▼
         │                          ┌─────────┐
         └──────────────────────────│ RUNNING │
                                    └────┬────┘
                                         │
              ┌──────────────┬───────────┼───────────┬────────────┐
              ▼              ▼           ▼           ▼            ▼
        ┌───────────┐  ┌────────┐  ┌───────────┐ ┌──────────┐ ┌───────────┐
        │ SUCCEEDED │  │ FAILED │  │ TIMED_OUT │ │CANCELLED │ │ (requeue) │
        └───────────┘  └────────┘  └───────────┘ └──────────┘ └───────────┘
```

### Deliverable

A running system that proves the core dispatch loop works end-to-end. 83 tests, 97.84% coverage. Tag `v0.1.0`.

---

## Phase 2 — Reliability

### Objective

Make the system survive failures. Jobs must never be lost, never duplicated, and never stuck — even when the network drops, an Agent crashes, or the Server restarts.

### What It Delivers

A system where every Job is durably tracked, every state transition is enforced, every log is preserved, and every Agent recovers cleanly after a crash or disconnect.

### Capabilities

| Capability | Description |
|------------|-------------|
| Persistence | Jobs, Logs, Events stored in SQLite |
| Durable final logs | Final log persisted as an artifact, independent of live stream |
| Live stream independence | User disconnect never interrupts Job execution |
| Agent reconnect | Exponential backoff (1s → 30s) with jitter |
| Heartbeat | Agent liveness tracked; offline detection after missed beats |
| Ack-based delivery | Agent acknowledges each Job before state advances |
| Timeout enforcement | `timeoutMs` fires `cancel`; Agent kills the container |
| Cancellation | `POST /jobs/{id}/cancel` for user-initiated cancel |
| Live log streaming | SSE endpoint with per-subscriber backpressure |
| Agent reconcile | On restart, Agent scans local containers and reports results |
| Structured logging | JSON logs with `jobId`, `agentId`, `correlationId` |
| Job event history | Append-only audit trail per Job |
| Duplicate suppression | Same `idempotencyKey` returns the same Job, always |

### Explicitly Out of Scope

- Multi-Agent routing and label-based selection
- Priority scheduling, aging, MLFQ
- Dashboards and metrics endpoints

### Failure Handling

| Failure | Behavior |
|---------|----------|
| Agent offline at submit | Job stays `PENDING`, queued until Agent returns |
| Agent disconnects mid-run | State preserved; on reconnect, Agent reconciles container |
| Agent silently drops (network) | Heartbeat watcher marks Agent offline after 30s |
| Agent restarts | Agent scans Docker, reports results for known Jobs |
| Server restarts | Reloads Jobs from DB, re-accepts Agents, reconciles in-flight |
| Duplicate `idempotencyKey` | Returns the existing `jobId`, no new Job |
| No ack from Agent | Requeue, up to 3 attempts, then `FAILED` |
| Live log client disconnects | Job continues; final log still persisted |
| Log storage temporarily down | Buffered in memory with a cap; never blocks execution |
| Orphan container | Detected on Agent startup, reported or resumed |
| Timeout reached | Server sends `cancel`; Agent kills container; state → `TIMED_OUT` |

### Deliverable

A system that a reviewer can break on purpose and watch recover. 165 tests, 87.37% coverage. Tags `v0.2.1` through `v0.2.8` and `v0.3.0`.

---

## Phase 3 — Scale

### Objective

Make the system intelligent. Multiple Agents, correct routing, and scheduling policies that prevent starvation and prioritize short or interactive work.

### What It Delivers

A system that runs several Agents across simulated Datacenters, routes Jobs correctly, and applies MLFQ-inspired scheduling so that no Job starves and interactive work is not blocked by batch work.

### Capabilities

| Capability | Description |
|------------|-------------|
| Multi-Agent | Multiple Agents register independently and stay isolated |
| Explicit routing | Jobs target a specific `agentId`; never cross Agents |
| Label-based routing | Optional: Jobs match Agents by labels (region, purpose) |
| Per-Agent ready queue | Each Agent has its own FIFO queue of pending Jobs |
| Priority levels | Interactive, normal, batch |
| MLFQ feedback | Jobs demote on timeout; all Jobs boost periodically |
| Aging | Pending Jobs gain priority over time to prevent starvation |
| Escalating timeouts | Retries receive progressively longer timeouts |
| Preemption | High-priority Jobs can preempt low-priority ones via cancel |
| Fair dispatch | Round-robin across matching Agents when applicable |

### Scheduling Policy

The scheduler is inspired by Multi-Level Feedback Queue (MLFQ) from OS CPU scheduling, adapted to a distributed, container-based model.

```
Queue 0 (highest):  Interactive jobs, short timeout
Queue 1:            Normal jobs
Queue 2 (lowest):   Batch jobs, long timeout
```

Rules:

- A Job starts in the highest-priority queue.
- If it exceeds its time slice, it is preempted, demoted one level, and its timeout is doubled before requeuing.
- Every 60 seconds, all `PENDING` Jobs are boosted back to the highest queue to prevent starvation.
- Within a queue, dispatch is FIFO.
- Across queues, the highest non-empty queue wins.

This adapts CPU scheduling to distributed execution: preemption is expensive (killing a container), so it is rare; idempotency keys — which have no CPU equivalent — ensure retries are safe.

### Deliverable

A system that demonstrates correct routing and a defensible scheduling policy.

---

## Phase 4 — Delivery

### Objective

Make the system understandable, debuggable, and reproducible by anyone who clones the repository.

### What It Delivers

A professional repository that a reviewer can clone, run, and understand in minutes. Full observability, complete documentation, and a one-command demo.

### Capabilities

| Capability | Description |
|------------|-------------|
| Health endpoints | `/health` and `/ready` |
| Metrics endpoint | `/metrics` in Prometheus format |
| README | Architecture, roadmap, decisions, trade-offs |
| AI_USAGE.md | Honest record of AI assistance and human decisions |
| Documentation | Per-phase notes in `docs/` |
| docker-compose | One command to run Server and two Agents |
| Demo scripts | `scripts/demo.sh` and `scripts/demo.ps1` |
| Failure scenarios | Reproducible scripts for each failure mode |
| `env.example` | Documented environment configuration |

### Deliverable

A repository that a reviewer can run, break, and understand without reading the source.

---

## The Job Record as a Durable PCB

Just as an OS kernel tracks each process with a **Process Control Block (PCB)** — identity, state, execution context, priority, and accounting — the Server tracks each Job with a **Job Record**.

A PCB contains:

- Process ID
- Process state (ready, running, waiting, terminated)
- Program counter and registers
- Memory information
- Open files
- Priority
- Parent / child relationships
- Accounting (CPU time, etc.)

A Job Record contains:

| Job Record field | PCB equivalent |
|------------------|----------------|
| `jobId` | PID |
| `state` | Process state |
| `agentId` | Which "CPU" (Agent) owns it |
| `image`, `command` | What to execute |
| `timeoutMs` | Time slice / quantum |
| `idempotencyKey` | Identity for deduplication |
| `exitCode`, `error` | Termination status |
| `createdAt`, `updatedAt` | Accounting |
| `correlationId` | Traceability |
| `dispatchAttempts` | Retry count |
| Logs | Output / context |
| `priority` (Phase 3) | Scheduling priority |

So the Job Record is the **PCB of a Job** — the single, durable structure that holds everything the Server needs to know about a Job's identity, state, context, and lifecycle.

### Where the analogy is exact

- **State machine:** PCB has process states; the Job has Job states.
- **Dispatcher:** The OS dispatcher picks a ready process for a CPU; the Server dispatcher picks a pending Job for an Agent.
- **Context switch:** The OS saves and restores the PCB on a switch; the Server updates the Job Record on each state change.
- **Termination:** The OS records exit status; the Server records `exitCode` and `error`.
- **Accounting:** The OS tracks CPU time; the Server tracks timestamps and durations.

### Where the analogy breaks

A PCB lives in kernel memory, is fast, and disappears when the process ends. A Job Record lives in a database, is persistent, and must survive restarts. A PCB describes a local process; a Job Record describes a remote execution on another machine. So the Job Record is a **durable, distributed PCB**.

### Practical implications

Because the Job Record is a PCB, it must:

1. **Be the single source of truth.** Every state change writes to the DB first, then acts.
2. **Be updated atomically.** Transitions are single SQL `UPDATE ... WHERE state = ?` statements.
3. **Include an event log.** The `job_events` table is the PCB's history.
4. **Have a well-defined lifecycle.** `PENDING → DISPATCHED → RUNNING → terminal`.
5. **Be queryable.** `GET /jobs/{id}`, `GET /jobs`, `GET /jobs/{id}/events`.

---

## Communication Design

Two channels.

### Agent ↔ Server: WebSocket

| Option | Why chosen / not chosen |
|--------|-------------------------|
| **WebSocket** | **Chosen.** Outbound-friendly, works behind NAT, bidirectional |
| gRPC bidirectional streaming | Rejected. More setup, harder for browser clients |
| Message Broker (RabbitMQ, NATS) | Rejected. Adds infrastructure; deferred to a later phase |

The Agent opens the WebSocket. The Server never dials the Agent.

### User ↔ Server: HTTP + SSE

- **HTTP** for Job submission, status, result, logs, events, and cancel.
- **SSE** for live log streaming. One-way, HTTP-native, browser-friendly.

The dispatch channel (Agent ↔ Server) and the log channel (User ↔ Server) are separate concerns and use different protocols on purpose.

### Properties

| Property | How it is handled |
|----------|-------------------|
| **Durability** | Every Job persisted before dispatch. The database is the source of truth |
| **Ordering** | Per-Agent ordering enforced by the single WebSocket connection |
| **Backpressure** | Per-subscriber log queues with a cap. Container never blocked |
| **Acknowledgement** | Every dispatch requires an `ack`; unacked Jobs requeue |
| **Reconnect** | Agent reconnects with exponential backoff. Server marks offline after 3 missed heartbeats |
| **Horizontal scaling** | Future: multiple Server instances sharing the DB |

---

## Design Decisions

| Decision | Options considered | Choice | Why |
|----------|--------------------|--------|-----|
| Agent ↔ Server communication | WebSocket, gRPC, Message Broker | WebSocket | Outbound-friendly, simple, sufficient |
| User ↔ Server live logs | WebSocket, SSE, Streaming HTTP | SSE | One-way stream, HTTP-native |
| Source of truth | In-memory, DB, Broker | Database | Must survive restarts |
| Database | SQLite, Postgres, MongoDB | SQLite | Zero setup; Postgres-ready |
| Final Log storage | DB column, file, object storage | `job_logs` table | Queryable, simple |
| Event storage | DB table, file, external | `job_events` table | Append-only, queryable |
| Ack timeout | — | 5s (configurable) | Balances latency vs. slow networks |
| Retry limit | — | 3 attempts | Bounded, prevents permanent locks |
| Heartbeat interval | — | 10s | Detects silent drops within 30s |
| Reconnect backoff | — | 1s → 30s with jitter | Standard, avoids thundering herd |
| Container discovery | — | Docker labels | Standard metadata |
| Reconciliation | — | Agent-driven | Agent owns local state |
| Idempotency scope | Per-user, global, per-agent | Global | Strongest guarantee |
| Job scheduling | FIFO, priority, MLFQ | MLFQ (Phase 3) | Prevents starvation, adapts to behavior |
| Preemption | None, cancel only, kill + requeue | Cancel + requeue | Safe with idempotency |
| Multi-Server | Single, shared DB, sharded | Single (MVP), shared DB (future) | Start simple |

---

## State Machine Details

### Initial state

A Job always begins in `PENDING`. It is created in this state the moment `POST /jobs` returns a `jobId`.

### Final states

- `SUCCEEDED` — container exited with `exitCode = 0`
- `FAILED` — container exited with non-zero `exitCode`, or the Agent reported an error, or dispatch retries were exhausted
- `TIMED_OUT` — the Job exceeded `timeoutMs`
- `CANCELLED` — the user cancelled the Job

### Allowed transitions

| From | To | Trigger |
|------|----|---------|
| `PENDING` | `DISPATCHED` | Server sends the Job to an online Agent |
| `DISPATCHED` | `RUNNING` | Agent sends `started` |
| `DISPATCHED` | `PENDING` | Ack timeout or Agent disconnect before start |
| `RUNNING` | `SUCCEEDED` | Agent reports `exitCode = 0` |
| `RUNNING` | `FAILED` | Agent reports non-zero `exitCode` or error |
| `RUNNING` | `TIMED_OUT` | Server timeout fires; Agent kills container |
| `RUNNING` | `CANCELLED` | User cancels |
| `PENDING` | `CANCELLED` | User cancels before dispatch |

Any transition not in this table is invalid and is rejected.

### Duplicate transition

Treated as an idempotent no-op. The state is unchanged and the message is logged.

### Late result for a final Job

If a `result` message arrives for a Job already in a final state, the Server records the event in `job_events` and does not change the state.

### "No result" vs "definite failure"

- **No result yet** — `PENDING`, `DISPATCHED`, or `RUNNING`. The Job is still alive.
- **Definite failure** — `FAILED`, `TIMED_OUT`, or `CANCELLED`. The Job is finished.

The distinction matters: a Job with no result may still succeed; a definitely-failed Job must not be silently retried.

### Retry policy

The Server does not silently retry failed Jobs. The only automatic retry is the `DISPATCHED → PENDING` requeue, which recovers from an unacked dispatch. Execution retries require a new Job with a new `idempotencyKey`.

---

## Failure Model

| Scenario | Expected Behavior |
|----------|-------------------|
| Agent offline before receiving Job | Job stays `PENDING`, queued |
| Network drops mid-execution | Agent reconnects; Job state preserved |
| Agent silently drops | Heartbeat watcher marks offline after 30s |
| Agent restarts mid-execution | Agent reconciles container state on startup |
| Server restarts | Reloads Jobs, re-accepts Agents, reconciles |
| Same `idempotencyKey` sent twice | Existing `jobId` returned |
| No ack from Agent | Requeue, up to 3 attempts, then `FAILED` |
| Live log connection drops | Job continues; final log persisted |
| Agent crashes before reporting result | Reconcile detects orphan container |
| Log storage unavailable | Buffered in memory, execution never blocked |
| Orphan container | Detected on Agent startup, reported or cleaned up |
| Timeout | Server cancels, Agent kills, state → `TIMED_OUT` |
| Duplicate delivery | Idempotency prevents double execution |
| Late result for a final Job | Recorded as event, state unchanged |

---

## Scheduling Policy

The scheduler adapts the **Multi-Level Feedback Queue (MLFQ)** from OS CPU scheduling to a distributed Job system.

| CPU Concept | System Equivalent |
|-------------|-------------------|
| Ready queue | `PENDING` Jobs per Agent |
| Dispatcher | Server orchestrator |
| Time slice | `timeoutMs` |
| Preemption | `cancel` message → container kill |
| Priority | Job priority level |
| Aging | Periodic boost of pending Jobs |
| Starvation | Job stuck in `PENDING` |
| Throughput | Jobs completed per unit time |

**Why MLFQ:**

- It solves priority, fairness, and starvation in one mechanism.
- It adapts to Job behavior (short Jobs stay high, long Jobs demote).
- It maps cleanly to distributed execution with expensive preemption.

**Why not plain priority:**

- Plain priority starves low-priority Jobs.
- Plain FIFO ignores interactive workloads.
- MLFQ gives both responsiveness and fairness.

---

## Tech Stack

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Language | Python 3.11+ | Readable, strong async, great Docker SDK |
| Agent ↔ Server | WebSocket | Outbound-friendly, bidirectional |
| User ↔ Server (control) | REST | Universal API, easy to test |
| User ↔ Server (live logs) | SSE | One-way stream, HTTP-native |
| Execution | Docker | Isolation, portability |
| Persistence | SQLite | Zero setup; Postgres-ready |
| API framework | FastAPI | Async, typed, auto docs |
| Validation | Pydantic | Integrated with FastAPI |
| Testing | pytest + pytest-asyncio | Standard |
| Linting | ruff | Fast, all-in-one |

---

## Quick Start

Requires Python 3.11+, Docker Desktop, and PowerShell.

```powershell
git clone https://github.com/<you>/job-system.git
cd job-system

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Three terminals in the project root, venv activated in each.

**Terminal 1 — Server:**

```powershell
python -m packages.server.main
```

**Terminal 2 — Agent:**

```powershell
$env:AGENT_ID = "agent-1"
python -m packages.agent.main
```

**Terminal 3 — Submit a Job:**

```powershell
$body = @{
  agentId = "agent-1"
  image = "alpine:latest"
  command = @("sh", "-c", "echo hello && sleep 2 && echo done")
  timeoutMs = 30000
  idempotencyKey = "quick-start-1"
} | ConvertTo-Json

$r = Invoke-RestMethod -Uri http://localhost:8000/jobs -Method Post -Body $body -ContentType "application/json"
Invoke-RestMethod -Uri "http://localhost:8000/jobs/$($r.jobId)/result" | ConvertTo-Json
```

### Configuration

`env.example` documents every value:

```
SERVER_HOST=0.0.0.0
SERVER_PORT=8080
API_PORT=8000
AGENT_ID=agent-1
SERVER_URL=ws://localhost:8080
LOG_LEVEL=INFO
DB_PATH=data/jobs.db
ACK_TIMEOUT_SECONDS=5
MAX_DISPATCH_ATTEMPTS=3
```

---

## Evidence

- [Phase 1 Evidence](docs/EVIDENCE_PHASE1.md) — MVP: end-to-end dispatch, 83 tests, 97.84% coverage, `v0.1.0`
- [Phase 2 Evidence](docs/EVIDENCE_PHASE2.md) — Reliability: persistence, timeouts, logs, ack, heartbeat, reconcile, events, 165 tests, 87.37% coverage, `v0.2.1`–`v0.2.8`, `v0.3.0`