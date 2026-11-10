-- Additive upgrade from the original demo. Do not edit after applying.
ALTER TABLE trips ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 0;
ALTER TABLE telemetry_inbox ADD COLUMN IF NOT EXISTS processing_result TEXT;
CREATE INDEX IF NOT EXISTS inbox_unprocessed_received_idx ON telemetry_inbox(received_at,event_id) WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS outbox_dispatch_idx ON telemetry_outbox(dispatched_at,event_id);
CREATE INDEX IF NOT EXISTS trips_driver_idx ON trips(driver_id,id);
CREATE INDEX IF NOT EXISTS trips_passenger_idx ON trips(passenger_id,id);
CREATE INDEX IF NOT EXISTS trips_active_received_idx ON trips((COALESCE(last_received_at,created_at))) WHERE status='ACTIVE';
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS login_attempt_lookup_idx ON login_attempts(username,ip,created_at);
CREATE INDEX IF NOT EXISTS login_attempt_expiry_idx ON login_attempts(created_at);
CREATE INDEX IF NOT EXISTS incidents_planning_idx ON incidents(severity DESC,created_at) WHERE needs_plan AND status='OPEN';
CREATE INDEX IF NOT EXISTS incidents_list_idx ON incidents(status,severity DESC,created_at DESC);
CREATE INDEX IF NOT EXISTS events_incident_idx ON incident_events(incident_id,id);
CREATE INDEX IF NOT EXISTS events_kind_idx ON incident_events(incident_id,kind);
CREATE INDEX IF NOT EXISTS proposals_latest_idx ON proposals(incident_id,created_at DESC);
CREATE INDEX IF NOT EXISTS proposals_expiry_idx ON proposals(expires_at) WHERE status='PENDING';
CREATE INDEX IF NOT EXISTS graph_work_idx ON graph_jobs(status,created_at) WHERE status IN ('NEW','WAITING');
CREATE INDEX IF NOT EXISTS sos_actor_idx ON sos_events(actor_id,incident_id);
