-- Initial schema (section 13). PostgreSQL.
--
-- The POC bootstraps with SQLAlchemy's create_all; this file is the reviewable
-- version of the same schema and the starting point for a real migration tool.

BEGIN;

CREATE TABLE IF NOT EXISTS tasks (
    id                  VARCHAR(64) PRIMARY KEY,
    repository_url      TEXT        NOT NULL,
    repository_path     TEXT,
    issue               TEXT        NOT NULL,
    status              VARCHAR(48) NOT NULL,
    risk_level          VARCHAR(16),
    current_node        VARCHAR(64),
    iteration           INTEGER     NOT NULL DEFAULT 0,
    ci_iteration        INTEGER     NOT NULL DEFAULT 0,
    workspace_path      TEXT,
    branch              VARCHAR(255),
    commit_sha          VARCHAR(64),
    pull_request_url    TEXT,
    approval_required   BOOLEAN     NOT NULL DEFAULT FALSE,
    created_by          VARCHAR(255),
    idempotency_key     VARCHAR(255),
    state               TEXT        NOT NULL DEFAULT '{}',
    summary             TEXT,
    error               TEXT,
    locked_by           VARCHAR(128),
    lease_expires_at    TIMESTAMPTZ,
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS ix_tasks_idempotency_key ON tasks (idempotency_key);
-- Supports the worker's recovery sweep (section 55).
CREATE INDEX IF NOT EXISTS ix_tasks_lease ON tasks (locked_by, lease_expires_at);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key                  VARCHAR(255) PRIMARY KEY,
    task_id              VARCHAR(64)  NOT NULL,
    request_fingerprint  VARCHAR(64)  NOT NULL,
    created_at           TIMESTAMPTZ  NOT NULL,
    updated_at           TIMESTAMPTZ  NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id               VARCHAR(64) PRIMARY KEY,
    task_id          VARCHAR(64) NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    workflow_run_id  VARCHAR(64) NOT NULL,
    node             VARCHAR(64) NOT NULL,
    agent            VARCHAR(64) NOT NULL,
    iteration        INTEGER     NOT NULL DEFAULT 0,
    status           VARCHAR(32) NOT NULL DEFAULT 'RUNNING',
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    duration_ms      INTEGER,
    input_tokens     INTEGER     NOT NULL DEFAULT 0,
    output_tokens    INTEGER     NOT NULL DEFAULT 0,
    cost_usd         DOUBLE PRECISION NOT NULL DEFAULT 0,
    error            TEXT,
    created_at       TIMESTAMPTZ NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_agent_runs_task_id ON agent_runs (task_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_workflow_run_id ON agent_runs (workflow_run_id);

CREATE TABLE IF NOT EXISTS tool_calls (
    id              VARCHAR(64) PRIMARY KEY,
    task_id         VARCHAR(64) NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    agent_run_id    VARCHAR(64),
    tool            VARCHAR(64) NOT NULL,
    arguments       TEXT        NOT NULL DEFAULT '{}',
    ok              BOOLEAN     NOT NULL DEFAULT TRUE,
    result_preview  TEXT,
    error           TEXT,
    exit_code       INTEGER,
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_tool_calls_task_id ON tool_calls (task_id);
CREATE INDEX IF NOT EXISTS ix_tool_calls_agent_run_id ON tool_calls (agent_run_id);

CREATE TABLE IF NOT EXISTS task_events (
    id          VARCHAR(64) PRIMARY KEY,
    task_id     VARCHAR(64) NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    sequence    INTEGER     NOT NULL DEFAULT 0,
    type        VARCHAR(48) NOT NULL,
    payload     TEXT        NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_task_events_task_seq ON task_events (task_id, sequence);

CREATE TABLE IF NOT EXISTS file_changes (
    id             VARCHAR(64) PRIMARY KEY,
    task_id        VARCHAR(64) NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    path           TEXT        NOT NULL,
    change_type    VARCHAR(16) NOT NULL DEFAULT 'MODIFIED',
    iteration      INTEGER     NOT NULL DEFAULT 0,
    lines_added    INTEGER     NOT NULL DEFAULT 0,
    lines_removed  INTEGER     NOT NULL DEFAULT 0,
    diff           TEXT,
    created_at     TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_file_changes_task_id ON file_changes (task_id);

CREATE TABLE IF NOT EXISTS approvals (
    id                VARCHAR(64) PRIMARY KEY,
    task_id           VARCHAR(64) NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    status            VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    reason            TEXT,
    requested_reason  TEXT,
    decided_by        VARCHAR(255),
    decided_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_approvals_task_id ON approvals (task_id);

CREATE TABLE IF NOT EXISTS ci_runs (
    id           VARCHAR(64) PRIMARY KEY,
    task_id      VARCHAR(64) NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    provider     VARCHAR(32) NOT NULL,
    external_id  VARCHAR(128),
    branch       VARCHAR(255),
    status       VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    conclusion   VARCHAR(32),
    url          TEXT,
    logs         TEXT,
    iteration    INTEGER     NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_ci_runs_task_id ON ci_runs (task_id);

CREATE TABLE IF NOT EXISTS evaluation_results (
    id          VARCHAR(64)  PRIMARY KEY,
    fixture     VARCHAR(128) NOT NULL,
    task_id     VARCHAR(64),
    passed      BOOLEAN      NOT NULL DEFAULT FALSE,
    metrics     TEXT         NOT NULL DEFAULT '{}',
    details     TEXT         NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL,
    updated_at  TIMESTAMPTZ  NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_evaluation_results_fixture ON evaluation_results (fixture);

CREATE TABLE IF NOT EXISTS repositories (
    id              VARCHAR(64)  PRIMARY KEY,
    url             TEXT         NOT NULL,
    path            TEXT         NOT NULL,
    default_branch  VARCHAR(128) NOT NULL DEFAULT 'main',
    languages       TEXT         NOT NULL DEFAULT '[]',
    indexed_at      TIMESTAMPTZ,
    chunk_count     INTEGER      NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ  NOT NULL,
    updated_at      TIMESTAMPTZ  NOT NULL,
    CONSTRAINT uq_repositories_url UNIQUE (url)
);

CREATE TABLE IF NOT EXISTS code_chunks (
    id             VARCHAR(64)  PRIMARY KEY,
    repository_id  VARCHAR(64)  NOT NULL REFERENCES repositories (id) ON DELETE CASCADE,
    file_path      TEXT         NOT NULL,
    symbol_name    VARCHAR(255),
    symbol_kind    VARCHAR(32),
    language       VARCHAR(32),
    start_line     INTEGER      NOT NULL DEFAULT 0,
    end_line       INTEGER      NOT NULL DEFAULT 0,
    content        TEXT         NOT NULL,
    embedding      TEXT,
    meta           TEXT         NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ  NOT NULL,
    updated_at     TIMESTAMPTZ  NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_code_chunks_repository_id ON code_chunks (repository_id);
CREATE INDEX IF NOT EXISTS ix_code_chunks_file_path ON code_chunks (file_path);
CREATE INDEX IF NOT EXISTS ix_code_chunks_symbol_name ON code_chunks (symbol_name);

COMMIT;
