# AI Usage

## Tools Used

- **DeepSeek** — used as a design and implementation assistant throughout the project.
- No other AI tools were used.

## How AI Was Used

The AI was used as a **thinking partner**, not as a code generator that replaced my own work. Concretely:

### Phase 1 — MVP

- **Architecture discussion.** Compared WebSocket, gRPC bidirectional streaming, and Message Brokers for the Agent ↔ Server channel, with trade-offs. The final decision to use WebSocket was mine.
- **Project scoping.** Helped break the task into four phases. The structure came out of that conversation and I refined it.
- **Concept clarification.** Explained how the system relates to OS CPU scheduling, and how a Job record is analogous to a Process Control Block (PCB). This informed the design of the Job record and the state machine.
- **Concrete implementation examples.** For Phase 1, asked for a minimal WebSocket + Docker example to confirm correct Python Docker SDK usage, particularly `containers.run(..., detach=True)` and `container.wait()`.
- **Code review.** Reviewed the repository layout and the protocol design and pointed out gaps.

### Phase 2 — Reliability

- **Race-condition analysis.** Asked the AI to explain how Python handles races under asyncio, threads, and multiprocessing, and to identify the specific race surfaces in the dispatch, idempotency, and state-transition paths. I chose the fixes (per-agent lock, atomic dict insert, compare-and-swap).
- **Design review of the ack flow.** Discussed whether the ack timeout should be a per-job task or a scan loop. I chose the scan loop.
- **Design review of the heartbeat flow.** Discussed clean disconnect vs. silent drop. The observation that a clean disconnect unregisters instantly (and only silent drops need the heartbeat watcher) came out of that discussion, and I confirmed it against the running system.
- **Reconcile design.** Discussed whether the Agent or the Server should drive reconcile. I chose Agent-driven.
- **Concept clarification.** Explained how structured logging and correlation IDs should be threaded through the codebase.
- **Concrete implementation examples.** For each sub-phase, generated initial code skeletons for the new modules (`log_broker.py`, `log_repository.py`, `event_repository.py`, `ack_watcher.py`, `heartbeat_watcher.py`, `timeouts.py`) and the tests. I reviewed each one, corrected the logic where it was wrong, and integrated it.
- **Bug diagnosis.** When the dispatch event recorded `attempt: 0` against SQLite but `attempt: 1` against the in-memory repository, the AI identified that the local Job object was stale — the SQLite repository returns a different instance from `get()`. I applied the fix.

## What I Wrote Myself

The following decisions and code are my own:

- The protocol message shapes (`register`, `ack`, `started`, `log`, `result`, `heartbeat`, `job`, `cancel`, `reconcile`) and the reason for each message.
- The decision to push blocking Docker SDK calls off the event loop using `asyncio.to_thread`.
- The repository layout under `packages/shared`, `packages/server`, and `packages/agent`.
- The decision to make `POST /jobs` return `202 Accepted` with a `jobId`, and never block until the Job finishes.
- All three race-condition fixes: per-agent `asyncio.Lock`, atomic dict check-and-insert, and compare-and-swap state transitions.
- The choice to use SSE for live logs instead of WebSocket — a deliberate split of the Agent ↔ Server channel and the User ↔ Server log channel.
- The three-repository split (`SQLiteJobRepository`, `SQLiteLogRepository`, `SQLiteEventRepository`) with separate connections to the same file.
- The decision to remove the foreign key from `job_logs` and `job_events` — logs and events are streams, not relational children.
- The choice to keep the AckWatcher as a scan loop rather than a task per dispatch.
- The choice to make reconcile Agent-driven.
- The `dispatch_attempts` column and its semantics.
- The state machine table and the rules for duplicate transitions and late results.
- The structure and content of the README and both evidence documents.

## What I Verified / Changed

- Confirmed that `container.wait()` in the Python Docker SDK returns a **dict** with a `StatusCode` key, not an integer.
- Verified that `docker.from_env()` works on Windows when Docker Desktop is running with the WSL 2 backend.
- Verified that `async for raw in ws` on the `websockets` library behaves the same on both the server and the client side.
- Changed the AI's initial suggestion of storing logs in memory to persisting them in `job_logs`.
- Rejected the AI's suggestion of adding a Message Broker in Phase 1.
- Rejected the AI's suggestion of a per-dispatch `asyncio.Task` for the ack timeout; chose the scanner loop instead.
- Diagnosed and fixed the `attempt: 0` bug: the AI produced the initial code with `job.dispatch_attempts + 1`, which double-counted. The correct version uses the value returned from the service method.
- Verified that a clean Agent disconnect (Ctrl+C) unregisters instantly and does not trigger the heartbeat watcher — the watcher is for silent drops only.
- Verified that Demo 2.4 (durable logs) really survives a Server restart by running it.
- Verified that Demo 2.7 (reconcile) really completes a Job after the Agent restarts by running it.

## Note

The main architecture — the outbound-only WebSocket, the Job state machine, the durable Job record as a PCB, the four-phase delivery plan, the SSE split for live logs, the ack/heartbeat/reconcile triad — was designed and understood by me. DeepSeek was used to accelerate research, clarify concepts, sanity-check implementation details, and generate initial code skeletons that I then reviewed and corrected. I can explain and defend every design decision in this repository.

Every sub-phase in Phase 2 was run end to end against a live Server and Agent before being tagged. The evidence documents in `docs/` record what was verified and how.