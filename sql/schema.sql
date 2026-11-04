-- Wafer fab simulator schema. Portable across PostgreSQL and SQLite.
-- All *_time columns are simulation hours since t = 0.

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    scenario        TEXT NOT NULL,
    dispatch_rule   TEXT NOT NULL,
    release_policy  TEXT NOT NULL,
    seed            INTEGER NOT NULL,
    sim_hours       DOUBLE PRECISION NOT NULL,
    warmup_hours    DOUBLE PRECISION NOT NULL,
    created_at      TEXT NOT NULL,
    config_json     TEXT,
    summary_json    TEXT
);

CREATE TABLE IF NOT EXISTS lots (
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    lot_id          INTEGER NOT NULL,
    release_time    DOUBLE PRECISION NOT NULL,
    due_time        DOUBLE PRECISION NOT NULL,
    complete_time   DOUBLE PRECISION,             -- NULL = still WIP at end of run
    wafers_start    INTEGER NOT NULL,
    wafers_out      INTEGER NOT NULL,
    PRIMARY KEY (run_id, lot_id)
);

-- One row per lot per route step (the "wafer move" history).
CREATE TABLE IF NOT EXISTS lot_moves (
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    lot_id          INTEGER NOT NULL,
    step_idx        INTEGER NOT NULL,
    recipe          TEXT NOT NULL,
    tool_group      TEXT NOT NULL,
    tool_id         TEXT NOT NULL,
    arrive_time     DOUBLE PRECISION NOT NULL,    -- joined the queue
    start_time      DOUBLE PRECISION NOT NULL,    -- processing started
    end_time        DOUBLE PRECISION NOT NULL,    -- processing finished (incl. repair pauses)
    batch_id        INTEGER NOT NULL,
    batch_size      INTEGER NOT NULL,
    wafers_in       INTEGER NOT NULL,
    wafers_out      INTEGER NOT NULL,
    PRIMARY KEY (run_id, lot_id, step_idx)
);

-- Tool state intervals. Idle time = everything not covered by PROD or DOWN.
CREATE TABLE IF NOT EXISTS tool_states (
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    tool_id         TEXT NOT NULL,
    tool_group      TEXT NOT NULL,
    state           TEXT NOT NULL CHECK (state IN ('PROD', 'DOWN')),
    start_time      DOUBLE PRECISION NOT NULL,
    end_time        DOUBLE PRECISION NOT NULL,
    batch_id        INTEGER
);

CREATE TABLE IF NOT EXISTS wip_snapshots (
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    t               DOUBLE PRECISION NOT NULL,
    tool_group      TEXT NOT NULL,
    queued          INTEGER NOT NULL,
    in_process      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_moves_group ON lot_moves (run_id, tool_group);
CREATE INDEX IF NOT EXISTS ix_states_tool ON tool_states (run_id, tool_id);
CREATE INDEX IF NOT EXISTS ix_wip_t ON wip_snapshots (run_id, t);
