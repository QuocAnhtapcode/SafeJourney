-- A renewal is requested once per expired proposal; it never grants approval.
ALTER TABLE proposals ADD COLUMN replan_requested_at TIMESTAMPTZ;
ALTER TABLE proposals ADD COLUMN replan_requested_by TEXT REFERENCES users(id);
