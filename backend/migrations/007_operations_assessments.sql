-- Advisory calculations have their own memory and never authorize incident actions.
CREATE TABLE operations_runs (
    id UUID PRIMARY KEY,
    trip_id TEXT NOT NULL REFERENCES trips(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    scenario_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    snapshot JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING','COMPLETED','PARTIAL','BLOCKED','FAILED')),
    report JSONB,
    execution_token UUID NOT NULL,
    lease_until TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX operations_trip_history_idx ON operations_runs(trip_id,created_at DESC,id DESC);
CREATE INDEX operations_actor_running_idx ON operations_runs(actor_id,lease_until) WHERE status='RUNNING';
CREATE INDEX operations_actor_created_idx ON operations_runs(actor_id,created_at DESC);
