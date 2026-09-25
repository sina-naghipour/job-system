import asyncio
import logging
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class BaseWatcher(ABC):
    def __init__(self, scan_interval: float) -> None:
        self._scan_interval = scan_interval

    async def run(self) -> None:
        name = type(self).__name__
        log.info("Watcher started", extra={"watcher": name, "interval": self._scan_interval})
        while True:
            try:
                await self._scan()
            except Exception:
                log.exception("Watcher scan failed", extra={"watcher": name})
            await asyncio.sleep(self._scan_interval)

    @abstractmethod
    async def _scan(self) -> None: ...