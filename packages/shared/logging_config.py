import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line.

    Standard fields: timestamp, level, component, message.
    Optional fields (present if the caller passed them via extra=):
      job_id, agent_id, correlation_id.
    """

    def __init__(self, component: str) -> None:
        super().__init__()
        self._component = component

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self._format_time(record.created),
            "level": record.levelname,
            "component": self._component,
            "message": record.getMessage(),
        }

        for field in ("job_id", "agent_id", "correlation_id"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _format_time(created: float) -> str:
        dt = datetime.fromtimestamp(created, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def configure_logging(component: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(component=component))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))

    # Quiet the noisy uvicorn access log; we log what we need ourselves.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)