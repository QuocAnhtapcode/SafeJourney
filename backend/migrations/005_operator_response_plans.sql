-- Prepared, reviewable actions. Legacy proposals remain readable and actionable.
ALTER TABLE proposals ADD COLUMN response_plan JSONB;
ALTER TABLE proposals ADD COLUMN revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0);
ALTER TABLE proposals ADD COLUMN followup_of UUID UNIQUE REFERENCES proposals(id);
ALTER TABLE proposals ADD COLUMN operator_outcome JSONB;
ALTER TABLE proposals ADD COLUMN follow_up_due_at TIMESTAMPTZ;
