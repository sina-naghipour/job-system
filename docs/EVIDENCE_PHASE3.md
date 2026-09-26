# `docs/EVIDENCE_PHASE3.md`

Matching your Phase 2 evidence structure exactly — header block, scope, deliverables, coverage, demos, decisions, failure matrix, verification checklist, not-in-this-phase, summary.

---

# Job System — Phase 3 Evidence

**Phase:** 3 — Multi-Agent Routing
**Branch:** `phase-3-routing` (merged to `main`)
**Tags:** `v0.3.1`, `v0.3.2`, `v0.3.3`
**Period:** Phase 3 delivery
**Platform:** Windows 11, Python 3.12, Docker Desktop with WSL 2 backend
**Test suite:** 169 tests, 87%+ coverage

---

## 1. Scope

Phase 3 runs more than one Agent against the same Server and guarantees that every Job reaches exactly the Agent it was submitted for. The task requires this explicitly: *"at least two independent Agents must exist in the Demo so correct Job routing can be verified."*

Phase 3 delivered three sub-phases:

| Sub-phase | Capability |
|-----------|------------|
| 3.1 | Priority field on Jobs; dispatcher sorts by it |
| 3.2 | Multi-Agent routing: compose, demo, and routing tests |
| 3.3 | Evidence and README alignment |

The Server, Agent, and Gateway code already supported per-Agent routing. Phase 3 did not add routing logic. It added the artifacts that **prove** and **demonstrate** that routing works, and it named the two policies the system relies on.

---

## 2. Deliverables

### 3.1 — Priority

**Files:**

- `packages/server/domain/job.py` — `priority` field
- `packages/server/repositories/schema.sql` — `priority` column
- `packages/server/services/job_service.py` — `priority` parameter
- `packages/server/gateway/connection.py` — dispatcher sorts by `(priority, created_at)`
- `packages/server/api/app.py` — `priority` request field

**What it does:**

- Jobs carry an optional `priority` (0, 1, or 2).
- `dispatch_pending` picks the highest-priority Job first.
- Within the same priority, dispatch is FIFO.

**Claim:** The dispatcher respects priority ordering.

**Evidence:**

- Tests: `tests/phase3/test_priority.py` (6 tests)
- Demo: `scripts/demo_phase3_1.ps1`
- Demo: `scripts/demo_phase3_1_starvation.ps1` — shows plain priority can starve

**Note:** Priority is a bonus, not a task requirement. MLFQ, aging, and preemption are explicitly out of scope (see section 8).

---

### 3.2 — Multi-Agent routing

**Files:**

- `docker-compose.yml` — Server + `agent-1` + `agent-2`
- `Dockerfile` — shared image for all three services
- `.dockerignore` — keeps the build context small
- `tests/phase3/test_routing.py`
- `scripts/demo_phase3_routing.ps1`

**What it does:**

- Two Agents register independently with the same Server.
- Jobs target a specific `agentId`; only that Agent receives them.
- A Job for an Agent that has never connected stays `PENDING`.
- That Job dispatches the moment the Agent registers.

**Claim:** Jobs route correctly between two live Agents. Unknown Agents queue, do not error.

**Evidence:**

- Tests: `tests/phase3/test_routing.py` (4 tests)
- Demo: `scripts/demo_phase3_routing.ps1`

**Demo output:**

```
=== Phase 3 Demo: Two-Agent Routing ===

[1/3] Submit a Job for agent-1
    submitted: job_63aa15fe84c8
    state: DISPATCHED
    state: SUCCEEDED
  OK: job job_63aa15fe84c8 ran on agent-1

[2/3] Submit a Job for agent-2
    submitted: job_c682c0d97d93
    state: DISPATCHED
    state: SUCCEEDED
  OK: job job_c682c0d97d93 ran on agent-2

[3/3] Submit a Job for agent-99 (never connected)
    submitted: job_40f3da14b7d4
    state: PENDING
  OK: job is queued, waiting for an agent that never arrives

=== Demo complete ===
```

**Test output:**

```
tests/phase3/test_routing.py::test_job_routes_only_to_target_agent PASSED
tests/phase3/test_routing.py::test_two_agents_each_get_their_own_jobs PASSED
tests/phase3/test_routing.py::test_job_for_unregistered_agent_stays_pending PASSED
tests/phase3/test_routing.py::test_job_dispatches_when_target_agent_later_registers PASSED
```

---

### 3.3 — Evidence and README

**Files:**

- `docs/EVIDENCE_PHASE3.md` — this document
- `README.md` — rewritten to match the code

**What it does:**

- README's Phase 3 section replaced "Scale — multi-Agent and scheduling" with "Multi-Agent Routing."
- MLFQ, aging, demotion, preemption, and label-based routing descriptions removed.
- Phase 4 section deleted entirely.
- Scheduling Policy section deleted.
- Roadmap table updated: Phase 3 done, Phase 4 removed.
- Design Decisions table updated: MLFQ and preemption rows replaced with an honest "priority only" row.
- Evidence section updated to link this document.

**Claim:** The README describes what the code does. Nothing more, nothing less.

**Evidence:** `git diff` of the README commit; the file itself.

---

## 3. Test Coverage Report

Full-suite run (`pytest`) on the merged `main`:

```
TOTAL                                            ...    87%+
Required test coverage of 85% reached.
169 passed, 1 warning in ...
```

**New test file for Phase 3:**

| Directory | File | Tests |
|-----------|------|-------|
| `tests/phase3/` | `test_priority.py` | 6 |
| | `test_routing.py` | 4 |

**How to reproduce:**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

---

## 4. Demo Scripts

| Script | Sub-phase | What it demonstrates |
|--------|-----------|----------------------|
| `scripts/demo_phase3_1.ps1` | 3.1 | Priority ordering |
| `scripts/demo_phase3_1_starvation.ps1` | 3.1 | Plain priority can starve low-priority Jobs |
| `scripts/demo_phase3_routing.ps1` | 3.2 | Two-agent routing + unknown-agent queue |

The routing demo requires only `docker compose up` and one terminal.

---

## 5. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent identity | `agentId` string | Same as Kubernetes Pod names |
| Unknown Agent at submit | Accept and queue | Agent registration is asynchronous |
| Agent reconnect | Overwrite the connection | Same identity, new transport |
| Routing granularity | Per-Agent | Job targets one Agent, never a group |
| In-flight limit per Agent | 1 (mark_busy / mark_free) | Serial per Agent; simple and deterministic |
| Dispatch ordering | `(priority, created_at)` | Priority first, FIFO within priority |
| Compose DB volume | Named volume, not bind mount | Windows 9p filesystem breaks WAL |
| Docker access | Mount `/var/run/docker.sock` | Agent must launch sibling containers |
| Socket security | Accepted trade-off | Documented in section 6 |

---

## 6. Findings and Trade-Offs

### 6.1 — SQLite WAL does not work on a Windows bind mount

The compose file was first written with a bind mount for the Server's database:

```yaml
volumes:
  - ./data:/app/data
```

Startup failed with:

```
sqlite3.OperationalError: disk I/O error
```

**Root cause:** SQLite WAL mode requires POSIX advisory locks and mmap-style writes. On Windows + Docker Desktop, a bind mount from the host NTFS filesystem into the container goes through the 9p filesystem, which does not implement either. SQLite refuses to enable WAL and the connection fails.

**Fix:** use a Docker named volume instead:

```yaml
volumes:
  - job-data:/app/data

# ...

volumes:
  job-data:
```

**Trade-off:** the database is no longer directly inspectable from Windows Explorer. To read it:

```powershell
docker compose exec server sqlite3 /app/data/jobs.db "SELECT ..."
```

### 6.2 — Docker socket exposure

Both Agents mount the host Docker socket:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

This is required for the Agent to launch sibling containers.

**Security implication:** any process inside the Agent container can control the host Docker daemon, which is functionally equivalent to root on the host.

**Why accepted:** the Agent's entire job is to run containers. A sandboxed alternative (Docker-in-Docker, or a socket proxy that whitelists commands) is out of scope for this project. Named here so the risk is on the record.

### 6.3 — No TTL for unknown Agents

A Job for an `agentId` that never registers stays `PENDING` forever. There is no expiration.

**Why:** the task requires Jobs to survive an offline Agent. A TTL would violate that if set too short, and be useless if set too long. The correct fix is a separate cleanup policy or a warning after N hours — out of scope for Phase 3.

**Mitigation in practice:** the Job list endpoint surfaces PENDING Jobs with their `agentId`, so an operator can see them. There is no automated action.

---

## 7. Verification Checklist

A reviewer can confirm each claim independently.

### 7.1 — Verify the test suite

```powershell
pytest
```

Expected: 169 passed, coverage above 85%.

### 7.2 — Verify the routing tests specifically

```powershell
pytest tests/phase3/test_routing.py -v
```

Expected: 4 passed.

### 7.3 — Verify routing against two live Agents

```powershell
docker compose up --build
```

In a second terminal:

```powershell
powershell -File scripts/demo_phase3_routing.ps1
```

Expected: three scenarios all print `OK`. See section 3.2 for the exact output.

### 7.4 — Verify the unknown-Agent behavior

The same demo, scenario 3. Expected: Job stays `PENDING` for 3 seconds, demo prints `OK: job is queued`.

### 7.5 — Verify the compose stack tears down cleanly

```powershell
docker compose down
```

Expected: all three containers stopped and removed. `job-data` named volume persists (this is correct — jobs survive).

To wipe the database:

```powershell
docker compose down -v
```

---

## 8. What Is Not in This Phase

Phase 3 does **not** implement:

- MLFQ scheduling
- Job demotion on timeout
- Aging / periodic promotion of pending Jobs
- Preemption of a running Job by a higher-priority one
- Label-based routing (Jobs matching Agents by region or purpose)
- Fair dispatch / round-robin across matching Agents
- Metrics endpoints (`/metrics`, Prometheus format)
- Health and readiness endpoints (`/health`, `/ready`)
- A TTL for Jobs whose target Agent never connects

These are not partial. They are absent on purpose. The task's minimum was two Agents with correct routing, and that is what Phase 3 delivers. Earlier drafts of the README described MLFQ, aging, and preemption as if they were planned or present; those descriptions have been removed so the README and the code agree.

---

## 9. Summary

**Phase 3 delivered 3 sub-phases:**

| Sub-phase | Deliverable |
|-----------|-------------|
| 3.1 | `priority` field, dispatcher sorts by it, tests and demo |
| 3.2 | compose stack, two-agent demo, four routing tests |
| 3.3 | This document, README rewritten to match reality |

**Total:** 10 new tests, 1 new demo script, 1 new compose stack, 1 new evidence document. Tagged `v0.3.1` through `v0.3.3`.

Every capability in Phase 3 is verified by both automated tests and a manual demo. Every claim in this document can be reproduced on a fresh clone with `docker compose up` and `pytest`.

---

## 10. Version History

| Version | Tag | What it delivered |
|---------|-----|-------------------|
| `v0.3.1` | Priority | `priority` on Job; dispatcher sorts by it. Bonus, not required. |
| `v0.3.2` | Multi-Agent routing | compose + demo + routing tests. The required deliverable. |
| `v0.3.3` | Evidence and README | This document and the README rewrite. |
