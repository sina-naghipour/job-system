# Job System — Phase 2 Evidence

**Phase:** 2 — Reliability
**Branch:** `phase-2-reliability` (merged to `main`)
**Tags:** `v0.2.1` through `v0.2.8`, plus `v0.3.0` on the merge
**Period:** Phase 2 delivery
**Platform:** Windows 11, Python 3.12, Docker Desktop with WSL 2 backend
**Test suite:** 165 tests, 87.37% coverage

---

## 1. Scope

Phase 2 turns the Phase 1 MVP into a system that survives failures. The eight sub-phases delivered:

| Sub-phase | Capability |
|-----------|------------|
| 2.1 | SQLite persistence for Jobs |
| 2.2 | Timeout enforcement and cancellation |
| 2.3 | Live log streaming over SSE |
| 2.4 | Durable final logs |
| 2.5 | Ack-based delivery with bounded retries |
| 2.6 | Heartbeat detection and Agent reconnect |
| 2.7 | Container reconcile on Agent restart |
| 2.8 | Structured logging, correlation IDs, and event history |

---

## 2. Deliverables

### 2.1 — Persistence

**Files:**

- `packages/server/schema.sql`
- `packages/server/sqlite_repository.py`

**What it does:**

- Replaces the in-memory store with SQLite.
- Persists every Job field, including `idempotency_key`.
- Uses WAL mode for crash safety.
- All state transitions are single SQL `UPDATE ... WHERE state = ?` statements.

**Claim:** Jobs survive Server restart.

**Evidence:**

- Test: `tests/phase2/test_sqlite_repository.py::test_jobs_survive_reopen`
- Test: `tests/phase2/test_sqlite_repository.py::test_idempotency_survives_reopen`
- Test: `tests/phase2/test_sqlite_repository.py::test_state_survives_reopen`
- Demo: `scripts/demo_phase2_4.ps1` — restart the Server, log survives.

---

### 2.2 — Timeout and cancellation

**Files:**

- `packages/server/timeouts.py`
- `packages/agent/main.py` — `start` / `wait` / `kill`
- `packages/server/api.py` — `POST /jobs/{id}/cancel`

**What it does:**

- Scans `RUNNING` Jobs every second.
- Fires `cancel` when `timeout_ms` is exceeded.
- Supports user-initiated cancellation.
- Agent kills the container on receipt.

**Claim:** Jobs cannot run forever. Users can cancel them.

**Evidence:**

- Tests: `tests/phase2/test_timeouts.py` (8 tests)
- Tests: `tests/phase2/test_api_cancel.py` (6 tests)
- Tests: `tests/phase2/test_gateway_cancel.py` (3 tests)
- Demo: `scripts/demo_phase2_2.ps1` — timeout and cancel scenarios

**Demo output (timeout):**

```
[1/3] Timeout: job sleeps 60s, timeout is 3s
    submitted: job_xxxxxxxxxxxx
    state: RUNNING
    state: TIMED_OUT
  OK: job job_xxxxxxxxxxxx is TIMED_OUT
```

**Demo output (cancel):**

```
[2/3] Cancel: job sleeps 60s, cancelled after 2s
    submitted: job_yyyyyyyyyyyy
    cancel response: state=CANCELLED
    state: CANCELLED
  OK: job job_yyyyyyyyyyyy is CANCELLED
```

---

### 2.3 — Live logs over SSE

**Files:**

- `packages/server/log_broker.py`
- `packages/server/api.py` — `GET /jobs/{id}/logs/live`
- `packages/agent/main.py` — `stream_logs`

**What it does:**

- Agent streams container output as chunks.
- LogBroker fans chunks to subscribers.
- SSE endpoint replays history, then streams live, then sends `event: end`.
- Slow subscribers drop oldest chunks; container never blocked.

**Claim:** Users watch stdout/stderr in real time.

**Evidence:**

- Tests: `tests/phase2/test_log_broker.py` (11 tests)
- Tests: `tests/phase2/test_api_logs_live.py` (3 tests)
- Demo: `scripts/demo_phase2_3.ps1`

**Demo output:**

```
[1/1] Submitting a job that prints once per second

    streaming logs (each line should appear once per second):

event: log
data: {"stream": "stdout", "sequence": 1, "chunk": "tick 1\n"}

event: log
data: {"stream": "stdout", "sequence": 2, "chunk": "tick 2\n"}

event: log
data: {"stream": "stdout", "sequence": 3, "chunk": "tick 3\n"}

event: log
data: {"stream": "stdout", "sequence": 4, "chunk": "tick 4\n"}

event: log
data: {"stream": "stdout", "sequence": 5, "chunk": "tick 5\n"}

event: end
data: {}
```

Each chunk arrives one second apart. Live streaming works.

---

### 2.4 — Durable final logs

**Files:**

- `packages/server/schema.sql` — `job_logs` table
- `packages/server/log_repository.py`
- `packages/server/api.py` — `GET /jobs/{id}/logs`

**What it does:**

- Persists every chunk as it arrives.
- Returns full log as `text/plain`.
- Survives Server restart, Agent restart, and client disconnect.

**Claim:** Final logs are durable artifacts.

**Evidence:**

- Tests: `tests/phase2/test_log_repository.py` (6 tests)
- Tests: `tests/phase2/test_api_logs.py` (5 tests)
- Demo: `scripts/demo_phase2_4.ps1` — full log before and after Server restart

**Demo output:**

```
[2/3] Fetch persisted log
    --- log content (before restart) ---
    line 1
    line 2
    line 3
    line 4
    line 5
    ---

[3/3] Durability check
    Restart the Server (Ctrl+C in Terminal 1, then start it again).
    Then press ENTER to fetch the log again.

    --- log content (after restart) ---
    line 1
    line 2
    line 3
    line 4
    line 5
    ---

  OK: log survived Server restart
```

---

### 2.5 — Ack-based delivery

**Files:**

- `packages/server/ack_watcher.py`
- `packages/server/store.py` — `mark_dispatched_with_attempt`, `fail_stale_dispatch`
- `packages/server/gateway.py` — increments attempts
- `packages/server/schema.sql` — `dispatch_attempts` column

**What it does:**

- Requires an `ack` from the Agent before the Job advances.
- Requeues Jobs that never ack within `ACK_TIMEOUT_SECONDS` (default 5).
- Fails after `MAX_DISPATCH_ATTEMPTS` (default 3).

**Claim:** Jobs that are never acked do not get stuck. They retry and then fail cleanly.

**Evidence:**

- Tests: `tests/phase2/test_ack_watcher.py` (4 tests)
- Demo: `scripts/demo_phase2_5.ps1` — broken Agent that never acks

**Demo output:**

```
[1/1] Submit a job to an agent that never acks
    submitted: job_xxxxxxxxxxxx
    target:    agent-noack

    watching job state (ack timeout is 5s, max attempts is 3):

  state=DISPATCHED  dispatchAttempts=1
  state=DISPATCHED  dispatchAttempts=2
  state=DISPATCHED  dispatchAttempts=3
  state=FAILED  dispatchAttempts=3

  final state: FAILED
  attempts:    3
  error:       No ack after 3 dispatch attempts

  OK: job requeued, retried, and finally failed after max attempts
```

---

### 2.6 — Heartbeat and reconnect

**Files:**

- `packages/server/heartbeat_watcher.py`
- `packages/server/store.py` — `AgentConnection.last_heartbeat_at`, `AgentRegistry.touch`
- `packages/agent/main.py` — `_heartbeat`, reconnect loop

**What it does:**

- Agent sends heartbeats every 10 seconds.
- Server marks an Agent offline after 3 missed beats.
- Agent reconnects with exponential backoff (1s to 30s) and jitter.
- Queued Jobs dispatch on reconnect.

**Claim:** Silent Agent failures are detected. Agents recover automatically.

**Evidence:**

- Tests: `tests/phase2/test_heartbeat_watcher.py` (4 tests)
- Demo: `scripts/demo_phase2_6.ps1`

**Demo output:**

```
[2/4] Kill the agent
    Waiting 35 seconds for the server to detect missed heartbeats...

[3/4] Submit a job while the agent is offline
    submitted: job_yyyyyyyyyyyy
    current state: PENDING attempts=0
  OK: job is queued, waiting for an online agent

[4/4] Restart the agent
    Waiting for the queued job to complete...
    state: SUCCEEDED attempts=1

  OK: queued job ran after the agent came back
```

**Server log line:**

```
[server] WARNING Agent agent-1 missed 3 heartbeats; marking offline
```

---

### 2.7 — Reconcile

**Files:**

- `packages/agent/main.py` — `_reconcile`, `_reattach`, container labels
- `packages/server/gateway.py` — `_on_reconcile`
- `packages/shared/protocol.py` — `ReconcileMessage`

**What it does:**

- Labels every container with `job_id` and `managed_by=job-system`.
- On startup, Agent scans Docker for managed containers.
- Running containers are reattached; results reported when they exit.
- Exited containers are inspected and reported immediately.

**Claim:** Agent restarts do not lose Jobs or rerun them.

**Evidence:**

- Integration test: `tests/phase1/test_integration.py`
- Demo: `scripts/demo_phase2_7.ps1`

**Demo output:**

```
[1/5] Submit a long-running job (sleeps 30 seconds)
    state: RUNNING

[2/5] Kill the agent

[3/5] Verify the job is still RUNNING on the server
    state: RUNNING
  OK: job is stuck in RUNNING; container is still alive in Docker

[4/5] Restart the agent
    Watch Terminal 2 for:
      'Reconcile: found 1 managed container(s)'

[5/5] Wait for the container to exit and the result to arrive
    state: SUCCEEDED exitCode=0

  OK: job completed after agent restart via reconcile
```

**Agent log lines (after restart):**

```
[agent] Reconcile: found 1 managed container(s)
[agent] Reconcile: job job_xxxxxxxxxxxx already exited; reporting
[agent] Job job_xxxxxxxxxxxx finished with exit_code=0
```

---

### 2.8 — Structured logging and events

**Files:**

- `packages/shared/logging_config.py` — `JsonFormatter`
- `packages/server/schema.sql` — `job_events` table
- `packages/server/event_repository.py`
- `packages/server/api.py` — `GET /jobs/{id}/events`
- `packages/shared/protocol.py` — `correlation_id` on `JobMessage`

**What it does:**

- Every log line is JSON with `timestamp`, `level`, `component`, `message`, and optional `job_id`, `agent_id`, `correlation_id`.
- `correlation_id` generated at submission, propagated to Agent.
- Every state transition recorded in `job_events`.
- Full event history retrievable via API.

**Claim:** Any Job can be traced end to end across Server and Agent.

**Evidence:**

- Tests: `tests/phase2/test_event_repository.py` (6 tests)
- Tests: `tests/phase1/test_gateway.py` — event recording tests
- Demo: `scripts/demo_phase2_8.ps1`

**Demo output:**

```
[2/4] Event history (GET /jobs/{id}/events)

  2026-09-25T12:42:22.194808+00:00  submitted  {"agent_id":"agent-1","image":"alpine:latest"}
  2026-09-25T12:42:22.195914+00:00  dispatched  {"attempt":1}
  2026-09-25T12:42:22.196934+00:00  ack  {}
  2026-09-25T12:42:22.488521+00:00  started  {"state":"RUNNING"}
  2026-09-25T12:42:22.586066+00:00  result  {"state":"SUCCEEDED","exit_code":0}
```

**Correlation trace:**

Every line about the Job, on both Server and Agent, carries `"correlation_id": "0132e727301947288d6320a9c62158a8"`.

Sample Server log line:

```json
{"timestamp":"2026-09-25T12:42:22.195Z","level":"INFO","component":"server","message":"Job dispatched","job_id":"job_2badf810bc11","correlation_id":"0132e727301947288d6320a9c62158a8","agent_id":"agent-1"}
```

Sample Agent log line:

```json
{"timestamp":"2026-09-25T12:42:22.197Z","level":"INFO","component":"agent","message":"Received job","job_id":"job_2badf810bc11","correlation_id":"0132e727301947288d6320a9c62158a8","agent_id":"agent-1","image":"alpine:latest"}
```

---

## 3. Test Coverage Report

Full-suite run (`pytest`) on the merged `main`:

```
TOTAL                                            830     95    136     15    87%
Required test coverage of 85% reached. Total coverage: 87.37%
====================================================================
165 passed, 1 warning in 2.66s
```

**Test file inventory:**

| Directory | File | Tests |
|-----------|------|-------|
| `tests/phase1/` | `test_protocol.py` | 6 |
| | `test_store.py` | 42 |
| | `test_api.py` | 15 |
| | `test_gateway.py` | 17 |
| | `test_concurrency.py` | 3 |
| | `test_integration.py` | 1 |
| `tests/phase2/` | `test_agent.py` | 7 |
| | `test_sqlite_repository.py` | 17 |
| | `test_log_repository.py` | 6 |
| | `test_log_broker.py` | 11 |
| | `test_event_repository.py` | 6 |
| | `test_timeouts.py` | 8 |
| | `test_ack_watcher.py` | 4 |
| | `test_heartbeat_watcher.py` | 4 |
| | `test_api_cancel.py` | 6 |
| | `test_api_logs.py` | 5 |
| | `test_api_logs_live.py` | 3 |
| | `test_gateway_cancel.py` | 3 |

**How to reproduce:**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

---

## 4. Demo Scripts

Every sub-phase has a runnable demo. Each is interactive and prints explicit `OK` / `FAIL` lines.

| Script | Sub-phase | What it demonstrates |
|--------|-----------|----------------------|
| `scripts/demo.ps1` | 1 | Phase 1 end-to-end dispatch |
| `scripts/demo_phase2_2.ps1` | 2.2 | Timeout and user cancel |
| `scripts/demo_phase2_3.ps1` | 2.3 | SSE live log streaming |
| `scripts/demo_phase2_4.ps1` | 2.4 | Durable log across restart |
| `scripts/demo_phase2_5.ps1` | 2.5 | Broken Agent never acks |
| `scripts/demo_phase2_6.ps1` | 2.6 | Heartbeat and offline detection |
| `scripts/demo_phase2_7.ps1` | 2.7 | Reconcile on Agent restart |
| `scripts/demo_phase2_8.ps1` | 2.8 | Event history and correlation |
| `scripts/fake_agent_no_ack_phase2_5.py` | 2.5 | Deliberately broken Agent |

---

## 5. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Storage | SQLite, three repositories on one file | Zero setup, Postgres-ready |
| CAS semantics | Single SQL `UPDATE ... WHERE state = ?` | Atomic at the DB level |
| Live log transport | SSE | One-way, HTTP-native |
| Ack timeout | 5s, configurable | Balances latency vs. slow networks |
| Retry limit | 3 attempts | Bounded, prevents permanent locks |
| Heartbeat interval | 10s | Detects silent drops within 30s |
| Reconnect backoff | 1s → 30s with jitter | Standard, avoids thundering herd |
| Container discovery | Labels | Standard Docker metadata |
| Reconciliation | Agent-driven | Agent owns its local state |
| Event storage | No foreign key to `jobs` | Events are a stream |
| Logging format | JSON only | One format, machine-parseable |

---

## 6. Failure Handling Matrix

| Failure | Behavior |
|---------|----------|
| Agent offline at submit | Job stays `PENDING`, dispatched on reconnect |
| Agent disconnects mid-run | Container keeps running; on reconnect, Agent reports |
| Agent silently drops (network) | Heartbeat watcher marks offline after 30s |
| Server restarts | Reloads Jobs, re-accepts Agents, reconciles |
| No ack from Agent | Requeue, up to 3 attempts, then `FAILED` |
| Timeout reached | Server sends `cancel`, Agent kills container |
| User cancels | Same cancel path, state → `CANCELLED` |
| Live log client disconnects | Job continues, final log still persists |
| Orphan container on Agent startup | Reconcile detects, reattaches, or reports |
| Log storage temporarily down | Buffered in memory, execution never blocked |

---

## 7. Verification Checklist

A reviewer can confirm each claim independently.

### 7.1 — Verify the branch structure

```powershell
git branch -a
git tag -l
```

Expected: `main` current, `phase-2-reliability` deleted after merge. Tags `v0.1.0`, `v0.2.1`–`v0.2.8`, `v0.3.0`.

### 7.2 — Verify the test suite

```powershell
pytest
```

Expected: 165 passed, coverage above 85%.

### 7.3 — Verify the event history

```powershell
# With Server and Agent running
.\scripts\demo_phase2_8.ps1
```

Expected: event history shows `submitted → dispatched → ack → started → result`, all with `correlation_id`.

### 7.4 — Verify persistence

```powershell
# With Server and Agent running
.\scripts\demo_phase2_4.ps1
```

Restart the Server when prompted. Expected: log content identical before and after restart.

### 7.5 — Verify reconcile

```powershell
.\scripts\demo_phase2_7.ps1
```

Kill the Agent when prompted, restart it. Expected: Job completes with the original container's result.

### 7.6 — Verify heartbeat

```powershell
.\scripts\demo_phase2_6.ps1
```

Kill the Agent when prompted. Expected: after 30 seconds, Server logs `Agent agent-1 missed 3 heartbeats; marking offline`.

---

## 8. What Is Not in This Phase

- **Phase 3:** multi-Agent routing, label-based selection, priority levels, MLFQ scheduling, aging, escalating timeouts, preemption, fair dispatch.
- **Phase 4:** metrics endpoint, health endpoints, docker-compose, full documentation, end-to-end demo script.

Those are scoped in the project README and will be delivered in their own branches and phases.

---

## 9. Summary

**Phase 2 delivered 8 sub-phases, each with:**

- Source code
- Unit and integration tests
- A runnable demo script
- A git tag

**Total:** 165 tests, 87.37% coverage, 9 tags, 8 demo scripts, 1 merge to `main`.

Every capability is verified by both automated tests and a manual demo. Every claim in this document can be reproduced on a fresh clone.
