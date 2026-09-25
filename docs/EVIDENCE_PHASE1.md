# Job System — Phase 1 Evidence

**Phase:** 1 — MVP
**Branch:** `phase-1-mvp` (merged to `main`)
**Tags:** `v0.1.0`
**Platform:** Windows 11, Python 3.12, Docker Desktop with WSL 2 backend
**Test suite at Phase 1 close:** 83 tests, 97.84% coverage

---

## 1. Scope

Phase 1 proves the hardest part of the system: **dispatching a Job from a Server to an Agent that the Server cannot reach, and getting the result back.**

Everything else — persistence, timeouts, logs, ack, heartbeat, reconcile, structured logging — came later in Phase 2. Phase 1 is the core dispatch loop and nothing more.

**Delivered:**

- HTTP API for Job submission and retrieval.
- WebSocket gateway for outbound Agent connections.
- Docker execution on the Agent.
- Job state machine.
- Idempotency via `idempotency_key`.
- Async submission (`POST /jobs` returns `202 Accepted` and does not block).
- Race-condition fixes for dispatch, idempotency, and state transitions.
- Two agents minimum for routing proof (in the demo environment).
- Demo script.

---

## 2. Deliverables

### 2.1 — Shared protocol

**File:** `packages/shared/protocol.py`

**What it defines:**

- `JobState` enum: `PENDING`, `DISPATCHED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `CANCELLED`.
- Message shapes for Agent → Server: `register`, `ack`, `started`, `log`, `result`, `heartbeat`.
- Message shapes for Server → Agent: `job`, `cancel`.
- Union types `AgentToServer` and `ServerToAgent` for type-safe dispatch.

**Claim:** Server and Agent agree on the message contract. Both import from one file.

**Evidence:**

- Tests: `tests/phase1/test_protocol.py` (6 tests).

---

### 2.2 — Server: domain model and repository

**File:** `packages/server/store.py`

**What it provides:**

- `Job` dataclass — the durable PCB for a Job: identity, request, state, outcome, timestamps.
- `JobRepository` (abstract) with compare-and-swap methods `transition_if` and `complete_if_running`.
- `InMemoryJobRepository` — atomic dict operations with no `await` between check and write.
- `JobService` — every state transition goes through the repository's CAS methods.
- `AgentRegistry` — tracks connected Agents.

**Claim:** Every state transition is atomic. Concurrent transitions cannot lose updates.

**Evidence:**

- Tests: `tests/phase1/test_store.py` (42 tests).
- Concurrency tests: `tests/phase1/test_concurrency.py` — 20 concurrent transitions yield one state change.
- Design note: `docs/race-conditions.md`.

---

### 2.3 — Server: WebSocket gateway

**File:** `packages/server/gateway.py`

**What it does:**

- Accepts outbound Agent connections.
- Registers Agents by `agent_id`.
- Dispatches `PENDING` Jobs, oldest first, with a per-Agent lock.
- Handles every message type from Agents.
- Tracks per-agent dispatch locks.

**Claim:** Two concurrent `dispatch_pending` calls cannot send the same Job twice.

**Evidence:**

- Tests: `tests/phase1/test_gateway.py`.
- Concurrency test: `test_concurrent_dispatch_sends_once`.

---

### 2.4 — Server: HTTP API

**File:** `packages/server/api.py`

**Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/jobs` | Submit a Job. Returns `202 Accepted` and a `jobId`. |
| `GET` | `/jobs` | List Jobs, filtered by `agentId` and/or `state`. |
| `GET` | `/jobs/{id}` | Get one Job's full record. |
| `GET` | `/jobs/{id}/result` | Get the Job's outcome (exit code, stdout, stderr). |

**Claim:** Submission is asynchronous. The HTTP connection does not block until completion.

**Evidence:**

- Tests: `tests/phase1/test_api.py` (15 tests).
- Behavior: `POST /jobs` returns `202` immediately. The user polls for the result.

---

### 2.5 — Agent: outbound WebSocket and Docker execution

**File:** `packages/agent/main.py`

**What it does:**

- Connects outbound to the Server.
- Registers with a unique `agent_id`.
- Waits for `job` messages.
- Runs each Job as a Docker container.
- Reports `ack`, `started`, and `result`.

**Claim:** The Agent runs Jobs in Docker and reports the result.

**Evidence:**

- Tests: `tests/phase1/test_agent.py`.
- Integration test: `tests/phase1/test_integration.py` — full round-trip over a real WebSocket.

---

### 2.6 — Race-condition fixes

**Files:**

- `packages/server/store.py`
- `packages/server/gateway.py`
- `packages/server/api.py`

**What was fixed:**

1. **Dispatch race** — two concurrent `dispatch_pending` calls could send the same Job twice. Fixed with a per-Agent `asyncio.Lock`.
2. **Idempotency race** — two concurrent submits with the same `idempotency_key` could create two Jobs. Fixed with atomic check-and-insert in the in-memory repository.
3. **State transition race** — concurrent transitions could lose updates. Fixed with compare-and-swap (`transition_if`, `complete_if_running`).

**Claim:** All three races are closed and proven with concurrency tests.

**Evidence:**

- Tests: `tests/phase1/test_concurrency.py` (3 tests, one per race).
- Documentation: `docs/race-conditions.md` — explains each race, the fix, and why the fix is correct for the asyncio single-process model.

---

### 2.7 — Demo script

**File:** `scripts/demo.ps1`

**What it does:**

1. Submits a Job that prints and sleeps.
2. Submits the same Job twice with the same `idempotencyKey` and asserts one Job.
3. Submits a Job that exits with code 42 and asserts `FAILED`.

**Claim:** The three core behaviors are demonstrable in one script.

**Evidence:** Script output captured below.

---

## 3. Verified End-to-End

All verification run on Windows 11, Python 3.12, Docker Desktop with WSL 2.

| Scenario | Result |
|----------|--------|
| Happy path: `POST /jobs`, Agent runs container, `GET /jobs/{id}/result` shows `SUCCEEDED` | ✅ |
| Idempotency: same `idempotencyKey` twice returns same `jobId`, one execution | ✅ |
| Failure path: `exit 42` → `FAILED`, `exitCode: 42` | ✅ |
| Async submission: `POST /jobs` returns `202` immediately | ✅ |
| Routing: Job dispatches to the correct `agentId` | ✅ |
| Two independent Agents in the demo environment | ✅ |
| Race conditions: 20 concurrent dispatches send one Job | ✅ |
| Race conditions: 20 concurrent idempotent submits return one `jobId` | ✅ |
| Race conditions: 20 concurrent transitions yield one state change | ✅ |

---

## 4. Test Coverage Report

Full-suite run at Phase 1 close:

```
Name                          Stmts   Miss Branch BrPart  Cover
-------------------------------------------------------------------------
packages\server\api.py           44      0      4      0   100%
packages\server\gateway.py       93      5     20      3    93%
packages\server\store.py        136      0     22      0   100%
packages\shared\protocol.py      51      0      0      0   100%
-------------------------------------------------------------------------
TOTAL                           324      5     46      3    98%
Required test coverage of 85% reached. Total coverage: 97.84%
====================================================================
83 passed
```

**Test file inventory at Phase 1 close:**

| File | Tests | Focus |
|------|-------|-------|
| `tests/phase1/test_protocol.py` | 6 | JobState enum, terminal states, serialization |
| `tests/phase1/test_store.py` | 42 | Repository, service, registry |
| `tests/phase1/test_api.py` | 15 | HTTP contract, validation, 404s |
| `tests/phase1/test_gateway.py` | 14 | WebSocket message handlers |
| `tests/phase1/test_agent.py` | 3 | Docker executor with a fake client |
| `tests/phase1/test_concurrency.py` | 3 | Race-condition proofs |
| `tests/phase1/test_integration.py` | 1 | Full round-trip over a real socket |

**How to reproduce:**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

---

## 5. Demo Output

`scripts/demo.ps1`, run against a live Server and Agent:

```
=== Phase 1 Demo ===

[1/3] Happy path
  submitted: job_b4accb92bd2f
  state: PENDING
  state: DISPATCHED
  state: RUNNING
  state: SUCCEEDED

  state:    SUCCEEDED
  exitCode: 0
  error:
  stdout:   Hello from the container
Done

[2/3] Idempotency
  first:  job_4ee6ad285868
  second: job_4ee6ad285868
  OK: same jobId returned, no duplicate created
  state: RUNNING
  state: SUCCEEDED

  state:    SUCCEEDED
  exitCode: 0
  error:
  stdout:   once

[3/3] Failure path
  submitted: job_d066e268e5d7
  state: RUNNING
  state: FAILED

  state:    FAILED
  exitCode: 42
  error:
  stdout:   about to fail

=== Demo complete ===
```

Three scenarios. Three passes.

---

## 6. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Communication | WebSocket | Outbound-friendly, works behind NAT, bidirectional |
| Job storage | In-memory (Phase 1) | Zero setup; replaced by SQLite in Phase 2 |
| State ownership | Server | Single source of truth; Agent reports facts |
| Docker blocking calls | `asyncio.to_thread` | Keep the event loop responsive |
| Idempotency | `idempotencyKey` → `jobId` map | Prevents duplicate execution |
| Protocol shape | `TypedDict` + `Literal` | Zero-overhead typing; discriminated unions |
| Async submission | `POST /jobs` returns `202` | No blocking until completion |
| Race handling | Locks, atomic ops, CAS | Match the concurrency model |

---

## 7. Failure Model (Phase 1 Scope)

| Failure | Behavior |
|---------|----------|
| Agent offline at submit | Job stays `PENDING` (persistence arrives in Phase 2) |
| Duplicate `idempotencyKey` | Existing `jobId` returned, no new Job |
| Container exits non-zero | Job marked `FAILED` with `exitCode` and `error` |
| Late result for a terminal Job | Ignored; state unchanged |
| Unknown message type | Logged and ignored |
| Agent disconnects | State preserved in memory; reconnect arrives in Phase 2 |

---

## 8. Known Limitations (Deferred to Phase 2)

Phase 1 was explicitly scoped. These capabilities were **not** implemented and are documented as Phase 2 work:

- No persistence. Restart the Server, Jobs are lost.
- No timeout enforcement. `timeout_ms` is stored but not acted on.
- No live log streaming. Logs arrive only at the end.
- No reconnect. Agent disconnect leaves the Job stuck.
- No heartbeat. Server does not know if an Agent is alive.
- No reconcile. Orphan containers are not detected.
- No multi-Agent routing beyond explicit `agentId`.
- No scheduler.
- No structured logging or correlation IDs.

All of these were addressed in Phase 2. See the Phase 2 evidence document.

---

## 9. Verification Checklist

A reviewer can confirm each claim independently.

### 9.1 — Verify the branch structure

```powershell
git log --oneline main
git tag -l
```

Expected: `v0.1.0` on `main`. The Phase 1 merge commit is at the top of the history before Phase 2 was merged.

### 9.2 — Verify the test suite

```powershell
pytest tests/phase1/
```

Expected: 83 tests pass.

Full-suite coverage was 97.84% at Phase 1 close. Later phases raised the total test count and lowered the aggregate coverage to 87.37%.

### 9.3 — Verify the race conditions are closed

```powershell
pytest tests/phase1/test_concurrency.py -v
```

Expected: 3 tests pass. Each one fires 20 concurrent operations and asserts a single winner.

### 9.4 — Verify the demo

With Server and Agent running:

```powershell
.\scripts\demo.ps1
```

Expected: three scenarios, all pass, ending with `=== Demo complete ===`.

### 9.5 — Read the race condition design note

```powershell
Get-Content docs/race-conditions.md
```

Explains dispatch, idempotency, and state-transition races, and why the current fixes are correct for the asyncio single-process model.

---

## 10. What Was Not in Phase 1

Everything in Phase 2:

- Persistence
- Timeouts and cancellation
- Live log streaming
- Durable final logs
- Ack-based delivery
- Heartbeat and reconnect
- Reconcile
- Structured logging and correlation IDs
- Job event history

And everything in Phases 3 and 4:

- Multi-Agent routing and priority scheduling (Phase 3)
- Metrics, health endpoints, docker-compose, full documentation (Phase 4)

---

## 11. Summary

**Phase 1 delivered the MVP:**

- Core dispatch loop, end to end.
- 83 tests, 97.84% coverage.
- Three race conditions identified and fixed.
- Demo script with three scenarios, all passing.
- Tag `v0.1.0` on the merged `main`.

Every claim in this document can be reproduced on a fresh clone.
