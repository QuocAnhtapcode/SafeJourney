-- Acknowledgement is historical; active ownership is a separate renewable lease.
-- Existing incidents intentionally start unassigned; old acknowledgements remain.
ALTER TABLE incidents ADD COLUMN assigned_operator_id TEXT REFERENCES users(id);
ALTER TABLE incidents ADD COLUMN assigned_at TIMESTAMPTZ;
ALTER TABLE incidents ADD COLUMN assignment_expires_at TIMESTAMPTZ;
ALTER TABLE incidents ADD COLUMN assignment_version BIGINT NOT NULL DEFAULT 0 CHECK (assignment_version >= 0);
ALTER TABLE incidents ADD COLUMN unassigned_since TIMESTAMPTZ;
ALTER TABLE incidents ADD CONSTRAINT incident_assignment_complete CHECK (
    (assigned_operator_id IS NULL AND assigned_at IS NULL AND assignment_expires_at IS NULL)
    OR (assigned_operator_id IS NOT NULL AND assigned_at IS NOT NULL AND assignment_expires_at IS NOT NULL)
);
CREATE INDEX incident_assignee_open_idx ON incidents(assigned_operator_id,assignment_expires_at)
    WHERE status='OPEN';
CREATE INDEX incident_assignment_expiry_idx ON incidents(assignment_expires_at)
    WHERE status='OPEN' AND assigned_operator_id IS NOT NULL;
