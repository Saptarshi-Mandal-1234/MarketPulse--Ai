SET search_path TO marketpulse, public;
CREATE TABLE risk_runs (
 risk_run_id text PRIMARY KEY, dataset_id text NOT NULL REFERENCES dataset_loads(dataset_id),
 created_at timestamptz NOT NULL, config jsonb NOT NULL, manifest jsonb NOT NULL
);
CREATE TABLE risk_observations (
 risk_run_id text NOT NULL REFERENCES risk_runs(risk_run_id),
 symbol text NOT NULL REFERENCES stocks(symbol), session_date date NOT NULL,
 details jsonb NOT NULL, PRIMARY KEY(risk_run_id,symbol)
);
CREATE TABLE pipeline_runs (
 run_id uuid PRIMARY KEY, started_at timestamptz NOT NULL, finished_at timestamptz,
 mode text NOT NULL, status text NOT NULL, details jsonb NOT NULL
);
CREATE TABLE research_forecasts (
 run_id uuid NOT NULL, symbol text NOT NULL REFERENCES stocks(symbol),
 as_of_date date NOT NULL, target text NOT NULL, target_date date,
 model_run_id uuid NOT NULL, value double precision,
 status text NOT NULL, details jsonb NOT NULL,
 PRIMARY KEY(run_id,symbol,target)
);
CREATE TABLE dashboard_snapshots (
 snapshot_id uuid PRIMARY KEY, dataset_id text NOT NULL REFERENCES dataset_loads(dataset_id),
 created_at timestamptz NOT NULL, manifest jsonb NOT NULL
);
