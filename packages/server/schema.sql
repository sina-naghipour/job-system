CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL,
    image               TEXT NOT NULL,
    command_json        TEXT NOT NULL,
    timeout_ms          INTEGER NOT NULL,
    idempotency_key     TEXT,
    metadata_json       TEXT NOT NULL,
    state               TEXT NOT NULL,
    exit_code           INTEGER,
    error               TEXT,
    stdout              TEXT NOT NULL DEFAULT '',
    stderr              TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    started_at          TEXT,
    finished_at         TEXT,
    correlation_id      TEXT NOT NULL,
    dispatch_attempts   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_agent_state
    ON jobs (agent_id, state);

CREATE INDEX IF NOT EXISTS idx_jobs_state
    ON jobs (state);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency
    ON jobs (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS job_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL,
    stream     TEXT NOT NULL,
    sequence   INTEGER NOT NULL,
    chunk      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_logs_job
    ON job_logs (job_id, sequence);

CREATE TABLE IF NOT EXISTS job_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_events_job
    ON job_events (job_id, id);