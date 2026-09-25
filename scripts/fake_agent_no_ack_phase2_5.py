"""
scripts/fake_agent_no_ack.py

A deliberately broken Agent for the Phase 2.5 demo.
It connects, registers, receives `job` messages, and never acks.
Used to demonstrate the AckWatcher requeueing stale dispatches.
"""

import asyncio
import json
import logging
import os

import websockets
from websockets.asyncio.client import ClientConnection

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [fake-agent] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

AGENT_ID = os.getenv("AGENT_ID", "agent-noack")
SERVER_URL = os.getenv("SERVER_URL", "ws://localhost:8080")


async def run() -> None:
    async with websockets.connect(SERVER_URL) as ws:
        await ws.send(json.dumps({"type": "register", "agent_id": AGENT_ID}))
        log.info("Registered as %s (will NOT ack)", AGENT_ID)

        async for raw in ws:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if message.get("type") == "job":
                log.warning(
                    "Received job %s but will not ack (simulating broken agent)",
                    message["job_id"],
                )


if __name__ == "__main__":
    asyncio.run(run())