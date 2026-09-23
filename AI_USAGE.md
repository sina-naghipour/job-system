# AI Usage

## Tools Used

- **DeepSeek** — used as a design and implementation assistant throughout the project.
- No other AI tools were used.

## How AI Was Used

The AI was used as a **thinking partner**, not as a code generator that replaced my own work. Concretely:

- **Architecture discussion.** I asked DeepSeek to compare WebSocket, gRPC bidirectional streaming, and Message Brokers for the Agent ↔ Server channel, and to explain the trade-offs. The final decision to use WebSocket was mine, based on that comparison.
- **Project scoping.** I asked DeepSeek to help me break the task into phases. The four-phase structure (MVP, Reliability, Scale, Delivery) came out of that conversation and I refined it.
- **Concept clarification.** I asked DeepSeek to explain how this system relates to OS CPU scheduling, and how a Job record is analogous to a Process Control Block (PCB). This informed the design of the Job record and the state machine.
- **Concrete implementation examples.** For Phase 1, I asked DeepSeek for a minimal WebSocket + Docker example to confirm the correct usage of the Python Docker SDK, particularly `containers.run(..., detach=True)` and `container.wait()`.
- **Code review.** I asked DeepSeek to review the repository layout and the protocol design and to point out gaps or inconsistencies.

## What I Wrote Myself

The following decisions and code are my own:

- The protocol message shapes (`register`, `ack`, `started`, `log`, `result`, `job`, `cancel`) and the reason for each message.
- The decision to push blocking Docker SDK calls off the event loop using `asyncio.to_thread`.
- The repository layout under `packages/shared`, `packages/server`, and `packages/agent`.
- The in-memory `JobStore` design, including idempotency handling via a separate `idempotency_key -> job_id` map.
- The decision to make `POST /jobs` return `202 Accepted` with a `jobId`, and never block until the Job finishes.
- The structure and content of the README, including the roadmap, the design decisions table, and the state machine details.

## What I Verified / Changed

- Confirmed that `container.wait()` in the Python Docker SDK returns a **dict** with a `StatusCode` key, not an integer. The type hints were adjusted accordingly.
- Verified that `docker.from_env()` works on Windows when Docker Desktop is running with the WSL 2 backend.
- Verified that `async for raw in ws` on the `websockets` library works the same on both the server and the client side.
- Changed the AI's initial suggestion of storing logs in memory to a decision that final logs must be persisted (recorded for Phase 2).
- Rejected the AI's suggestion of adding a Message Broker in Phase 1, because the task explicitly allows choosing one communication method and justifying it. WebSocket is sufficient and easier to defend.

## Note

The main architecture — the outbound-only WebSocket, the Job state machine, the durable Job record, the four-phase delivery plan, and the failure model — was designed and understood by me. DeepSeek was used to accelerate research, clarify concepts, and sanity-check implementation details. I can explain and defend every design decision in this repository.
