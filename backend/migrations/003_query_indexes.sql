-- Match the incident listing's actual sort, replacing the unused status sort.
DROP INDEX IF EXISTS incidents_list_idx;
CREATE INDEX incidents_priority_list_idx ON incidents
    ((status='OPEN') DESC,severity DESC,created_at DESC,id);
-- Scoped telemetry audit and load-run snapshots should not scan all history.
CREATE INDEX telemetry_trip_received_idx ON telemetry_inbox
    (trip_id text_pattern_ops,received_at);
CREATE INDEX incidents_escalation_due_idx ON incidents(created_at,id)
    WHERE status='OPEN' AND severity=3 AND acknowledged_at IS NULL;
