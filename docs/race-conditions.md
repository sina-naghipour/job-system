# Race Conditions in Phase 1

Phase 1 uses `asyncio` — a single thread with cooperative scheduling. That
does not mean the code is race-free. Every `await` is a yield point, and
any read-then-write sequence that yields in between can interleave with
another coroutine.

Three races existed in the original Phase 1 code. Each was found by
reasoning about the `await` points, fixed, and covered by a concurrency
test.

---

## Race 1 — Dispatch

### Where

`AgentGateway.dispatch_pending`

### What could go wrong

Two concurrent calls could both run:

```python
pending = self._job_service.list(agent_id=agent_id, state=JobState.PENDING)
for job in pending:
    await conn.ws.send(json.dumps(message))   # <-- await
    self._job_service.mark_dispatched(job.job_id)
```

If both calls listed the same PENDING job before either sent it, both
would send the same job to the Agent. The Agent would run the container
twice, with different results for the same `jobId`.

The most likely trigger: an HTTP submit and an Agent registration
arriving at the same moment. Both call `dispatch_pending`.

### Why it matters

Duplicate execution. Idempotency at the submission level does not help,
because the duplicate happens at dispatch.

### The fix

A per-agent `asyncio.Lock` wraps the entire dispatch sequence:

```python
async def dispatch_pending(self, agent_id: str) -> None:
    async with self._lock_for(agent_id):
        ...
```

The lock is per-agent, not global. Agent A's dispatch never blocks Agent
B's. Two dispatches for the same agent run one after the other. The
second sees the job already `DISPATCHED` and skips it.

### The test

`tests/phase1/test_concurrency.py::test_concurrent_dispatch_sends_once`

Fires 20 concurrent dispatches for the same agent and asserts the job
was sent exactly once.

---

## Race 2 — Idempotency

### Where

`InMemoryJobRepository.add`

### What could go wrong

The original code did:

```python
existing = self.get_by_idempotency_key(job.idempotency_key)
if existing:
    return existing
self._jobs[job.job_id] = job
self._idempotency[job.idempotency_key] = job.job_id
```

If two submits with the same `idempotency_key` interleaved at an `await`
between the check and the write, both would find nothing, both would
write, and the caller would get two different `jobId`s for one logical
request.

### Why it matters

Violates exactly-once submission. The container would run twice.

### The fix

Atomic check-and-insert with no `await` in between:

```python
def add(self, job: Job) -> Job:
    if job.idempotency_key is not None:
        existing_id = self._idempotency.get(job.idempotency_key)
        if existing_id is not None:
            return self._jobs[existing_id]
        self._idempotency[job.idempotency_key] = job.job_id
    self._jobs[job.job_id] = job
    return job
```

CPython guarantees dict operations are atomic within a single thread.
Since `add` never yields, the entire sequence is atomic under asyncio.

In Phase 2, this becomes a `UNIQUE` constraint on `idempotency_key` in
SQLite, so the guarantee survives process restarts and multiple writers.

### The test

`tests/phase1/test_concurrency.py::test_concurrent_idempotent_submit`

Fires 20 concurrent submits with the same key and asserts all return the
same `jobId`.

---

## Race 3 — State Transitions

### Where

`JobService.mark_dispatched`, `mark_running`, `mark_succeeded`,
`mark_failed`, `mark_timed_out`, `mark_cancelled`

### What could go wrong

The original pattern was:

```python
job = self._repository.get(job_id)
if job.state.is_terminal:
    return job
job.state = new_state
self._repository.save(job)
```

If two transitions ran concurrently — say a `mark_timed_out` and a
`mark_succeeded` — both could read `RUNNING`, both pass the terminal
check, both write. Last writer wins. One transition is silently lost.

This is the classic "lost update" problem.

### Why it matters

A late result could overwrite a `TIMED_OUT` state, or a cancel could
overwrite a completed job. The state machine becomes unreliable.

### The fix

Compare-and-swap. The repository exposes two atomic operations:

```python
def transition_if(self, job_id, expected, new_state) -> Optional[Job]:
    job = self._jobs.get(job_id)
    if job is None:
        return None
    if job.state != expected:
        return job
    job.state = new_state
    ...
```

```python
def complete_if_running(self, job_id, new_state, ...) -> Optional[Job]:
    job = self._jobs.get(job_id)
    if job is None:
        return None
    if job.state != JobState.RUNNING:
        return job
    ...
```

A transition is applied only if the current state matches the expected
state. If a concurrent transition already changed it, the second one is
a clean no-op. No lost updates.

`JobService` no longer decides whether a transition is legal — it passes
the expected state to the repository, and the repository decides
atomically.

### The test

`tests/phase1/test_concurrency.py::test_concurrent_transitions_only_one_wins`

Fires 20 concurrent `mark_dispatched` calls and asserts the final state
is `DISPATCHED` — one transition succeeded, nineteen were rejected.
