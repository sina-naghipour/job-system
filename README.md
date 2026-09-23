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

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                          USER                               │
│              (CLI, curl, or any HTTP client)                │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST + WebSocket (live logs)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    CONTROL PLANE (Server)                   │
│                                                             │
│   REST API   │   Live Log Streamer   │   Agent Gateway      │
│                                                             │
│   ─────────────────────────────────────────────────────    │
│                                                             │
│              Job Orchestrator / State Machine               │
│   Routing │ Idempotency │ Timeout │ Retry │ Reconcile       │
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
| **Phase 2** | Reliability — survive failures | ☐ |
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
| Timeout | Jobs exceeding `timeoutMs` are marked `TIMED_OUT` |
| Live logs | Agent streams `stdout`/`stderr` to the Server in real time |
| Result retrieval | User fetches `exitCode` and `error` after completion |
| Async submission | `POST /jobs` returns immediately with `jobId`; HTTP does not block |

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

### Explicitly Out of Scope

- Persistence across Server restarts
- Reconnect and heartbeat
- Reconciliation of orphan containers
- Multi-Agent routing
- Priority scheduling
- Observability beyond basic logs

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

### Demo

1. Start the Server.
2. Start one Agent.
3. `POST /jobs` with a simple command.
4. `GET /jobs/{id}` shows the Job moving through states.
5. `GET /jobs/{id}/result` returns the `exitCode`.

### Deliverable

A running system that proves the core dispatch loop works end-to-end.

### Commit

```
feat: MVP — end-to-end job dispatch with Docker execution
```

---

## Phase 2 — Reliability

### Objective

Make the system survive failures. Jobs must never be lost, never duplicated, and never stuck — even when the network drops, an Agent crashes, or the Server restarts.

### What It Delivers

A system where every Job is durably tracked, every state transition is enforced, every log is preserved, and every Agent recovers cleanly after a crash or disconnect.

### Capabilities

| Capability | Description |
|------------|-------------|
| Persistence | Jobs, Agents, Logs, Events stored in SQLite (Postgres-ready) |
| Formal state machine | All transitions enforced through a single function |
| Durable final logs | Final log persisted as an artifact, independent of live stream |
| Live stream independence | User disconnect never interrupts Job execution |
| Agent reconnect | Exponential backoff, automatic reconnection |
| Heartbeat | Agent liveness tracked; offline detection after missed beats |
| Ack-based delivery | Agent acknowledges each Job before state advances |
| Agent reconcile | On restart, Agent scans local containers and reports results |
| Server reconcile | On restart, Server reloads Jobs and re-dispatches pending work |
| Structured logging | `jobId`, `agentId`, `correlationId` on every log line |
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
| Agent restarts | Agent scans Docker, reports results for known Jobs |
| Server restarts | Reloads Jobs from DB, re-accepts Agents, reconciles in-flight |
| Duplicate `idempotencyKey` | Returns the existing `jobId`, no new Job |
| Live log client disconnects | Job continues; final log still persisted |
| Log storage temporarily down | Buffered in memory with a cap; never blocks execution |
| Orphan container | Detected on Agent startup, reported as `FAILED` or resumed |
| Timeout reached | Server sends `cancel`; Agent kills container; state → `TIMED_OUT` |

### Demo

1. Submit a long Job, then kill the Agent mid-run.
2. Restart the Agent — it reconciles and the Job completes.
3. Kill the Server, restart it — state is preserved.
4. Submit the same `idempotencyKey` twice — one Job, one execution.
5. Drop the live log connection — the Job keeps running.

### Deliverable

A system that a reviewer can break on purpose and watch recover.

### Commit

```
feat: production-grade reliability — persistence, reconnect, reconcile
```

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

### Demo

1. Start two Agents.
2. Submit a batch Job and an interactive Job — the interactive one runs first.
3. Submit Jobs to `agent-1` and `agent-2` — each runs on the correct Agent.
4. Submit a Job, let it time out, observe demotion and longer timeout on retry.
5. Leave a Job pending for a long time — aging promotes it.

### Deliverable

A system that demonstrates correct routing and a defensible scheduling policy.

### Commit

```
feat: multi-agent routing and MLFQ-style scheduler
```

---

## Phase 4 — Delivery

### Objective

Make the system understandable, debuggable, and reproducible by anyone who clones the repository.

### What It Delivers

A professional repository that a reviewer can clone, run, and understand in minutes. Full observability, complete documentation, and a one-command demo.

### Capabilities

| Capability | Description |
|------------|-------------|
| Structured JSON logging | Machine-readable logs with consistent fields |
| Correlation ID | Generated at submission, propagated to Agent and logs |
| Job event history | Append-only audit trail per Job |
| Health endpoints | `/health` and `/ready` |
| Metrics endpoint | `/metrics` in Prometheus format |
| README | Architecture, roadmap, decisions, trade-offs |
| AI_USAGE.md | Honest record of AI assistance and human decisions |
| Documentation | Per-phase notes in `docs/` |
| docker-compose | One command to run Server and two Agents |
| Demo scripts | `scripts/demo.sh` and `scripts/demo.ps1` |
| Failure scenarios | Reproducible scripts for each failure mode |
| `env.example` | Documented environment configuration |

### Demo

1. `docker compose up` — Server and two Agents start.
2. `./scripts/demo.sh` — submits Jobs, shows live logs, kills an Agent, restarts it, and shows reconciliation.
3. `GET /metrics` — exposes scheduler and Job metrics.
4. README — a reviewer reads it and understands the whole system.

### Deliverable

A repository that a reviewer can run, break, and understand without reading the source.

### Commit

```
docs: observability, README, AI_USAGE, and end-to-end demo
```

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
| Logs | Output / context |
| `priority` (Phase 3) | Scheduling priority |
| `attempts` (Phase 3) | Retry count |

So the Job Record is the **PCB of a Job** — the single, durable structure that holds everything the Server needs to know about a Job's identity, state, context, and lifecycle.

### Where the analogy is exact

- **State machine:** PCB has process states; the Job has Job states. Same idea.
- **Dispatcher:** The OS dispatcher picks a ready process for a CPU; the Server dispatcher picks a pending Job for an Agent.
- **Context switch:** The OS saves and restores the PCB on a switch; the Server updates the Job Record on each state change.
- **Termination:** The OS records exit status; the Server records `exitCode` and `error`.
- **Accounting:** The OS tracks CPU time; the Server tracks timestamps and durations.

### Where the analogy breaks (and why it matters)

A PCB lives in **kernel memory**, is **fast**, and is **ephemeral** — it disappears when the process ends. A Job Record lives in a **database**, is **persistent**, and must **survive restarts**. This is a deliberate difference:

- A PCB does not survive a reboot.
- A Job Record **must** survive a Server restart, because the Job may still be running on a remote Agent.

A PCB also describes a **local** process. A Job Record describes a **remote** execution — the actual container lives on another machine. So the Job Record is more like a **durable, distributed PCB**: it tracks a process that runs somewhere else and must be recoverable after a crash.

### Practical implications

Because the Job Record is a PCB, it must:

1. **Be the single source of truth.** No state lives only in memory. Every state change writes to the DB first, then acts.
2. **Be updated atomically.** Transitions should be transactional (`UPDATE ... WHERE state = 'expected'`) to prevent races.
3. **Include an event log.** A `job_events` table is the PCB's history — every transition, every ack, every log boundary. It is your audit trail and your debugging tool.
4. **Have a well-defined lifecycle.** `PENDING → DISPATCHED → RUNNING → terminal`. Same as a process.
5. **Be queryable.** `GET /jobs/{id}` reads the PCB. `GET /jobs` lists PCBs. `GET /jobs/{id}/events` reads the history.

---

## Communication Design

The task requires a deliberate decision on how Server and Agent communicate, and an explicit discussion of the following properties. This section documents the choice and the reasoning.

### Chosen method: WebSocket

| Option | Description | Why chosen / not chosen |
|--------|-------------|-------------------------|
| **WebSocket** | Bidirectional, message-based, runs over HTTP/1.1 upgrade | **Chosen.** Simple, outbound-friendly, works behind NAT, well-supported in Python |
| gRPC bidirectional streaming | HTTP/2-based, Protobuf-typed, built-in deadlines | Rejected for MVP. More setup, harder for browser clients, overkill for JSON messages |
| Message Broker (RabbitMQ, NATS JetStream) | Decoupled publish/subscribe | Rejected for MVP. Adds infrastructure; useful later for horizontal scaling |

The Agent opens the WebSocket. The Server never dials the Agent. This is what makes the system work across NAT and firewalls.

### Properties discussed

| Property | How it is handled |
|----------|-------------------|
| **Durability** | Every Job is persisted before dispatch. Messages are not the source of truth; the database is. If a message is lost, the Job is still recoverable from the DB |
| **Ordering** | Per-Agent ordering is enforced by the single WebSocket connection and a monotonic sequence number on each message. Out-of-order messages are rejected or buffered |
| **Backpressure** | The Server tracks the Agent's in-flight Job count. If the Agent is saturated, new Jobs stay `PENDING`. The Agent tracks its own Docker capacity and refuses Jobs it cannot run |
| **Acknowledgement** | Every Job dispatch requires an `ack` from the Agent before the state advances from `DISPATCHED` to `RUNNING`. Unacknowledged Jobs are re-dispatched after a timeout |
| **Reconnect** | The Agent reconnects with exponential backoff (1s, 2s, 4s, up to 30s). The Server marks the Agent offline after 3 missed heartbeats and queues Jobs for it |
| **Horizontal scaling** | Multiple Server instances can share the database. Each Agent connects to exactly one Server instance at a time. A future version can use a Message Broker to decouple this |

### Why not a Message Broker (yet)

A Message Broker like RabbitMQ or NATS JetStream would solve durability, ordering, and backpressure at the infrastructure level. It was rejected for the MVP because:

- It adds operational complexity (another service to run, monitor, and secure).
- The core problem — reliable dispatch to an Agent behind NAT — is solved by the WebSocket plus persistence, not by the Broker.
- The task explicitly says not all options need to be implemented; one well-justified choice is enough.

The Broker becomes attractive in Phase 3 or later, when horizontal scaling of the Server is needed. It is listed as a future extension, not a requirement.

---

## Design Decisions

This section records the research and decisions the task requires.

| Decision | Options considered | Choice | Why |
|----------|--------------------|--------|-----|
| Communication method | WebSocket, gRPC, Message Broker | WebSocket | Outbound-friendly, simple, sufficient |
| Source of truth | In-memory, DB, Broker | Database | Must survive restarts; Jobs are durable |
| Database | SQLite, Postgres, MongoDB | SQLite (Postgres-ready) | Zero setup for MVP, easy migration later |
| Live Log transport | WebSocket, SSE, Streaming HTTP | WebSocket | Same protocol as dispatch; bidirectional |
| Final Log storage | DB column, file, object storage | DB for small, file for large | Trade-off between query and size |
| Recovery after restart | None, replay from DB, reconcile | Reconcile | Robust against partial failures |
| Idempotency scope | Per-user, global, per-agent | Global | Simplest, strongest guarantee |
| Job scheduling | FIFO, priority, MLFQ | MLFQ (Phase 3) | Prevents starvation, adapts to behavior |
| Preemption | None, cancel only, kill + requeue | Cancel + requeue | Cheap enough, safe with idempotency |
| Multi-Server | Single, shared DB, sharded | Single (MVP), shared DB (future) | Start simple, scale when needed |

Each decision is revisited in the phase where it becomes relevant.

---

## State Machine Details

The task requires precise definitions for the following behaviors. These are the rules the Server enforces.

### Initial state

A Job always begins in `PENDING`. It is created in this state the moment `POST /jobs` returns a `jobId`.

### Final states

A Job is in a final state when it can no longer transition. The final states are:

- `SUCCEEDED` — container exited with `exitCode = 0`
- `FAILED` — container exited with non-zero `exitCode`, or the Agent reported an error
- `TIMED_OUT` — the Job exceeded `timeoutMs`
- `CANCELLED` — the user cancelled the Job

### Allowed transitions

| From | To | Trigger |
|------|----|---------|
| `PENDING` | `DISPATCHED` | Server sends the Job to an online Agent |
| `DISPATCHED` | `RUNNING` | Agent acknowledges and starts the container |
| `DISPATCHED` | `PENDING` | Agent disconnects before ack; Job is requeued |
| `RUNNING` | `SUCCEEDED` | Agent reports `exitCode = 0` |
| `RUNNING` | `FAILED` | Agent reports non-zero `exitCode` or error |
| `RUNNING` | `TIMED_OUT` | Server timeout fires; Agent kills container |
| `RUNNING` | `CANCELLED` | User cancels |
| `PENDING` | `CANCELLED` | User cancels before dispatch |

Any transition not in this table is invalid and is rejected.

### Duplicate transition

If the Server receives a message that would trigger a transition that has already happened, it is treated as an **idempotent no-op**. The state remains unchanged, and the message is logged.

Example: if the Agent sends `result` twice for the same `jobId`, the second is ignored. The Job stays in its final state.

### Late result for an already-final Job

If a `result` message arrives for a Job that is already in a final state, the Server:

1. Records the late result in the `job_events` table.
2. Does **not** change the Job's state.
3. Logs a warning with the `jobId`, `correlationId`, and the current state.

This protects against races where the Server times out a Job at the same moment the Agent reports success.

### "No result" vs "definite failure"

These are two distinct situations and must be handled differently:

- **No result yet** — the Job is still in `PENDING`, `DISPATCHED`, or `RUNNING`. The Agent has not reported anything. The Job is still considered alive. The Server may eventually time it out, but until then, it is not failed.
- **Definite failure** — the Job is in `FAILED`, `TIMED_OUT`, or `CANCELLED`. The Agent reported an error, the timeout fired, or the user cancelled. The Job is finished and will not run again.

The distinction matters because:

- A Job with no result may still succeed. It must not be marked `FAILED` prematurely.
- A Job with a definite failure must not be retried silently. If retry is desired, it must be explicit (new Job with the same `idempotencyKey` would return the old one, so a new key is required).

### Retry policy

The Server does not silently retry failed Jobs. If a Job is `FAILED` or `TIMED_OUT`, the user must submit a new Job (with a new `idempotencyKey`). This keeps the model simple and avoids surprising duplicate side effects.

The one exception is the `DISPATCHED → PENDING` requeue, which is a recovery from a transient network failure, not a retry of execution.

---

## Failure Model

| Scenario | Expected Behavior |
|----------|-------------------|
| Agent offline before receiving Job | Job stays `PENDING`, queued |
| Network drops mid-execution | Agent reconnects; Job state preserved |
| Agent restarts mid-execution | Agent reconciles container state on startup |
| Server restarts | Reloads Jobs, re-accepts Agents, reconciles |
| Same `idempotencyKey` sent twice | Existing `jobId` returned |
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
| Agent ↔ Server | WebSocket | Outbound-friendly, bidirectional, simple |
| User ↔ Server | REST + WebSocket | Universal API, streaming for live logs |
| Execution | Docker | Isolation, portability, standard |
| Persistence | SQLite (Postgres-ready) | Zero setup for MVP, scalable later |
| API framework | FastAPI | Async, typed, auto docs |
| Validation | Pydantic | Integrated with FastAPI |
| Testing | pytest + pytest-asyncio | Standard |
| Linting | ruff | Fast, all-in-one |

---

## Quick Start

> Filled in as phases are completed. Placeholder below.

```bash
git clone https://github.com/<you>/job-system.git
cd job-system

python -m venv .venv
.venv\Scripts\Activate.ps1     # Windows
# source .venv/bin/activate    # Linux / macOS

pip install -e .

# Terminal 1
python -m packages.server.main

# Terminal 2
python -m packages.agent.main
```

