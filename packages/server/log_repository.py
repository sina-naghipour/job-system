import sqlite3
from pathlib import Path
from typing import Optional

from packages.server.store import now

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class SQLiteLogRepository:
    def __init__(self, db_path: str = "data/jobs.db") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def close(self) -> None:
        self._conn.close()

    def append(self, job_id: str, stream: str, sequence: int, chunk: str) -> None:
        self._conn.execute(
            """
            INSERT INTO job_logs (job_id, stream, sequence, chunk, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, stream, sequence, chunk, now()),
        )

    def list_for_job(
        self,
        job_id: str,
        stream: Optional[str] = None,
    ) -> list[dict]:
        if stream is not None:
            rows = self._conn.execute(
                """
                SELECT stream, sequence, chunk FROM job_logs
                WHERE job_id = ? AND stream = ?
                ORDER BY id ASC
                """,
                (job_id, stream),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT stream, sequence, chunk FROM job_logs
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (job_id,),
            ).fetchall()
        return [dict(r) for r in rows]