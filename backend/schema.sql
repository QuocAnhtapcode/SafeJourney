CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK (role IN ('operator','driver','passenger'))
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS trips (
 id TEXT PRIMARY KEY, label TEXT NOT NULL, driver_id TEXT NOT NULL REFERENCES users(id),
 passenger_id TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL DEFAULT 'ACTIVE',
 route_geom geometry(LineString,4326) NOT NULL, last_lat DOUBLE PRECISION,
 last_lon DOUBLE PRECISION, last_seen TIMESTAMPTZ, last_received_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), detector_state JSONB NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS telemetry_inbox (
 event_id UUID PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(id),
 actor_id TEXT NOT NULL REFERENCES users(id), payload JSONB NOT NULL,
 received_at TIMESTAMPTZ NOT NULL DEFAULT now(), processed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS telemetry_outbox (
 event_id UUID PRIMARY KEY REFERENCES telemetry_inbox(event_id), dispatched_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS telemetry_pending_idx ON telemetry_outbox(event_id) WHERE dispatched_at IS NULL;
CREATE TABLE IF NOT EXISTS incidents (
 id UUID PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(id), kind TEXT NOT NULL,
 severity INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 3), status TEXT NOT NULL DEFAULT 'OPEN',
 summary TEXT NOT NULL, evidence JSONB NOT NULL DEFAULT '{}', needs_plan BOOLEAN NOT NULL DEFAULT true,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 acknowledged_at TIMESTAMPTZ, acknowledged_by TEXT REFERENCES users(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS incident_open_idx ON incidents(trip_id,kind) WHERE status='OPEN';
CREATE TABLE IF NOT EXISTS incident_events (
 id BIGSERIAL PRIMARY KEY, incident_id UUID NOT NULL REFERENCES incidents(id),
 kind TEXT NOT NULL, body TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sos_events (
 event_id UUID PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(id),
 actor_id TEXT NOT NULL REFERENCES users(id), incident_id UUID NOT NULL REFERENCES incidents(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS proposals (
 id UUID PRIMARY KEY, incident_id UUID NOT NULL REFERENCES incidents(id),
 action_type TEXT NOT NULL CHECK (action_type IN ('MOCK_CHECK_IN','MOCK_EMERGENCY')),
 recipient_ref TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING'
 CHECK (status IN ('PENDING','EXECUTED','REJECTED','EXPIRED','CANCELLED')),
 expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 approved_by TEXT REFERENCES users(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS proposal_pending_idx ON proposals(incident_id) WHERE status='PENDING';
CREATE TABLE IF NOT EXISTS mock_actions (
 id UUID PRIMARY KEY, proposal_id UUID UNIQUE NOT NULL REFERENCES proposals(id),
 approved_by TEXT NOT NULL REFERENCES users(id), payload JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS system_state (id INTEGER PRIMARY KEY CHECK(id=1), version BIGINT NOT NULL DEFAULT 0);
INSERT INTO system_state(id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS graph_jobs (
 id UUID PRIMARY KEY, incident_id UUID NOT NULL REFERENCES incidents(id),
 status TEXT NOT NULL DEFAULT 'NEW', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS graph_active_idx ON graph_jobs(incident_id)
 WHERE status IN ('NEW','WAITING');
CREATE TABLE IF NOT EXISTS login_attempts (
 username TEXT NOT NULL, ip TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
