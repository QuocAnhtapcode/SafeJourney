-- Routine contact is authorized by a bounded backend policy, never by a fake human.
ALTER TABLE mock_actions ALTER COLUMN approved_by DROP NOT NULL;
ALTER TABLE proposals ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'HUMAN'
    CHECK (execution_mode IN ('HUMAN','AUTO'));
ALTER TABLE proposals ADD COLUMN contact_attempt INTEGER NOT NULL DEFAULT 0 CHECK (contact_attempt BETWEEN 0 AND 2);
ALTER TABLE incidents ADD COLUMN automation_state TEXT NOT NULL DEFAULT 'NONE'
    CHECK (automation_state IN ('NONE','WAITING_RESPONSE','MONITORING','ESCALATED','COMPLETE'));
ALTER TABLE incidents ADD COLUMN monitor_until TIMESTAMPTZ;
CREATE TABLE contact_replies (
    request_id UUID PRIMARY KEY,
    proposal_id UUID NOT NULL UNIQUE REFERENCES proposals(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL REFERENCES users(id),
    outcome TEXT NOT NULL CHECK (outcome IN ('safe','needs_help')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX proposal_auto_deadline_idx ON proposals(follow_up_due_at,incident_id)
    WHERE execution_mode='AUTO' AND status='EXECUTED';
CREATE INDEX incident_monitor_deadline_idx ON incidents(monitor_until) WHERE status='OPEN' AND automation_state='MONITORING';
