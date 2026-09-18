CREATE TABLE marketpulse.dataset_loads (
 dataset_id text PRIMARY KEY CHECK(length(dataset_id)=64),
 quality_id text NOT NULL, feature_run_id text NOT NULL,
 manifests jsonb NOT NULL, loaded_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE marketpulse.validated_sessions (
 dataset_id text NOT NULL REFERENCES marketpulse.dataset_loads(dataset_id),
 symbol text NOT NULL REFERENCES marketpulse.stocks(symbol), session_date date NOT NULL,
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
 PRIMARY KEY(dataset_id,symbol,session_date)
);
CREATE TABLE marketpulse.session_calendars (
 dataset_id text NOT NULL REFERENCES marketpulse.dataset_loads(dataset_id),
 session_date date NOT NULL, expected_open boolean NOT NULL,
 session_kind text NOT NULL, source text NOT NULL,
 PRIMARY KEY(dataset_id,session_date)
);
CREATE TABLE marketpulse.dataset_quality_issues (
 dataset_id text NOT NULL REFERENCES marketpulse.dataset_loads(dataset_id),
 issue_number integer NOT NULL, details jsonb NOT NULL,
 PRIMARY KEY(dataset_id,issue_number)
);
CREATE TABLE marketpulse.active_dataset (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 dataset_id text NOT NULL REFERENCES marketpulse.dataset_loads(dataset_id)
);
CREATE VIEW marketpulse.current_validated_sessions AS
 SELECT s.* FROM marketpulse.validated_sessions s
 JOIN marketpulse.active_dataset a USING(dataset_id);
CREATE INDEX validated_dates_idx ON marketpulse.validated_sessions(dataset_id,session_date);
-- The original close_at table is not populated from a date-only calendar:
-- special-session closing times must never be invented.
