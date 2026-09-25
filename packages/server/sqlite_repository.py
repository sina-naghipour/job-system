import json
import sqlite3
from pathlib import Path
from typing import Optional

from packages.server.store import Job, JobRepository, now
from packages.shared.protocol import JobState

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class SQLiteJobRepository(JobRepository):
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

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            job_id=row["job_id"],
            agent_id=row["agent_id"],
            image=row["image"],
            command=json.loads(row["command_json"]),
            timeout_ms=row["timeout_ms"],
            idempotency_key=row["idempotency_key"],
            metadata=json.loads(row["metadata_json"]),
            state=JobState(row["state"]),
            exit_code=row["exit_code"],
            error=row["error"],
            stdout=row["stdout"],
            stderr=row["stderr"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            correlation_id=row["correlation_id"],
            dispatch_attempts=row["dispatch_attempts"],
        )

    def _fetch(self, job_id: str) -> Optional[Job]:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return self._row_to_job(row) if row else None

    def add(self, job: Job) -> Job:
        try:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    job_id, agent_id, image, command_json, timeout_ms,
                    idempotency_key, metadata_json, state, exit_code, error,
                    stdout, stderr, created_at, updated_at, started_at,
                    finished_at, correlation_id, dispatch_attempts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.agent_id,
                    job.image,
                    json.dumps(job.command),
                    job.timeout_ms,
                    job.idempotency_key,
                    json.dumps(job.metadata),
                    job.state.value,
                    job.exit_code,
                    job.error,
                    job.stdout,
                    job.stderr,
                    job.created_at,
                    job.updated_at,
                    job.started_at,
                    job.finished_at,
                    job.correlation_id,
                    job.dispatch_attempts,
                ),
            )
            return job
        except sqlite3.IntegrityError:
            if job.idempotency_key is None:
                raise
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?",
                (job.idempotency_key,),
            ).fetchone()
            if row is None:
                raise
            return self._row_to_job(row)

    def get(self, job_id: str) -> Optional[Job]:
        return self._fetch(job_id)

    def get_by_idempotency_key(self, key: str) -> Optional[Job]:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return self._row_to_job(row) if row else None

    def list(
        self,
        agent_id: Optional[str] = None,
        state: Optional[JobState] = None,
    ) -> list[Job]:
        clauses = []
        params: list[str] = []
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if state:
            clauses.append("state = ?")
            params.append(state.value)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM jobs {where} ORDER BY created_at DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_job(r) for r in rows]

    def save(self, job: Job) -> Job:
        job.updated_at = now()
        self._conn.execute(
            """
            UPDATE jobs SET
                agent_id = ?, image = ?, command_json = ?, timeout_ms = ?,
                idempotency_key = ?, metadata_json = ?, state = ?,
                exit_code = ?, error = ?, stdout = ?, stderr = ?,
                created_at = ?, updated_at = ?, started_at = ?,
                finished_at = ?, correlation_id = ?, dispatch_attempts = ?
            WHERE job_id = ?
            """,
            (
                job.agent_id,
                job.image,
                json.dumps(job.command),
                job.timeout_ms,
                job.idempotency_key,
                json.dumps(job.metadata),
                job.state.value,
                job.exit_code,
                job.error,
                job.stdout,
                job.stderr,
                job.created_at,
                job.updated_at,
                job.started_at,
                job.finished_at,
                job.correlation_id,
                job.dispatch_attempts,
                job.job_id,
            ),
        )
        return job

    def transition_if(
        self,
        job_id: str,
        expected: JobState,
        new_state: JobState,
    ) -> Optional[Job]:
        timestamp = now()
        self._conn.execute(
            """
            UPDATE jobs
            SET state = ?,
                updated_at = ?,
                started_at = COALESCE(started_at, ?),
                finished_at = CASE WHEN ? THEN ? ELSE finished_at END
            WHERE job_id = ? AND state = ?
            """,
            (
                new_state.value,
                timestamp,
                timestamp if new_state == JobState.RUNNING else None,
                new_state.is_terminal,
                timestamp,
                job_id,
                expected.value,
            ),
        )
        return self._fetch(job_id)

    def complete_if_running(
        self,
        job_id: str,
        new_state: JobState,
        exit_code: int,
        stdout: str,
        stderr: str,
        error: Optional[str],
    ) -> Optional[Job]:
        timestamp = now()
        self._conn.execute(
            """
            UPDATE jobs
            SET state = ?, exit_code = ?, stdout = ?, stderr = ?, error = ?,
                updated_at = ?, finished_at = ?
            WHERE job_id = ? AND state = ?
            """,
            (
                new_state.value,
                exit_code,
                stdout,
                stderr,
                error,
                timestamp,
                timestamp,
                job_id,
                JobState.RUNNING.value,
            ),
        )
        return self._fetch(job_id)