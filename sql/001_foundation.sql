SET search_path TO marketpulse, public;
CREATE TABLE stocks (
 symbol text PRIMARY KEY, name text NOT NULL,
 kind text NOT NULL CHECK (kind IN ('index','equity')),
 sector text NOT NULL, exchange text NOT NULL DEFAULT 'NSE',
 currency char(3) NOT NULL DEFAULT 'INR', provider_symbol text NOT NULL UNIQUE
);
CREATE TABLE ingestion_runs (
 run_id uuid PRIMARY KEY, provider text NOT NULL, started_at timestamptz NOT NULL,
 finished_at timestamptz, status text NOT NULL CHECK(status IN ('running','success','failed')),
 raw_path text NOT NULL, raw_sha256 text NOT NULL CHECK(length(raw_sha256)=64),
 CHECK(finished_at IS NULL OR finished_at >= started_at)
);
CREATE TABLE trading_sessions (
 exchange text NOT NULL, session_date date NOT NULL, close_at timestamptz NOT NULL,
 source text NOT NULL, PRIMARY KEY(exchange,session_date)
);
CREATE TABLE daily_prices (
 symbol text NOT NULL REFERENCES stocks(symbol), session_date date NOT NULL,
 open numeric(20,6) NOT NULL CHECK(open>0 AND open<'Infinity'::numeric),
 high numeric(20,6) NOT NULL CHECK(high>0 AND high<'Infinity'::numeric),
 low numeric(20,6) NOT NULL CHECK(low>0 AND low<'Infinity'::numeric),
 close numeric(20,6) NOT NULL CHECK(close>0 AND close<'Infinity'::numeric),
 adj_close numeric(20,6) CHECK(adj_close>0 AND adj_close<'Infinity'::numeric),
 volume bigint CHECK(volume>=0), provider text NOT NULL,
 adjustment text NOT NULL CHECK(adjustment='raw_ohlc_with_adj_close'),
 observed_at timestamptz NOT NULL, run_id uuid NOT NULL REFERENCES ingestion_runs(run_id),
 PRIMARY KEY(symbol,session_date,provider),
 CHECK(high>=low AND high>=open AND high>=close AND low<=open AND low<=close)
);
CREATE TABLE quality_issues (
 issue_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id uuid NOT NULL REFERENCES ingestion_runs(run_id),
 symbol text REFERENCES stocks(symbol), session_date date,
 severity text NOT NULL CHECK(severity IN ('warning','error')),
 rule text NOT NULL, details jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE technical_indicators (
 symbol text NOT NULL REFERENCES stocks(symbol), session_date date NOT NULL,
 feature_version text NOT NULL, dataset_sha256 text NOT NULL,
 available_at timestamptz NOT NULL, values jsonb NOT NULL CHECK(jsonb_typeof(values)='object'),
 PRIMARY KEY(symbol,session_date,feature_version,dataset_sha256)
);
CREATE TABLE model_runs (
 model_run_id uuid PRIMARY KEY, model_name text NOT NULL, feature_version text NOT NULL,
 dataset_sha256 text NOT NULL, train_start date NOT NULL, train_end date NOT NULL,
 trained_at timestamptz NOT NULL, metrics jsonb NOT NULL, artifact_path text NOT NULL,
 CHECK(train_end>=train_start)
);
CREATE TABLE predictions (
 prediction_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 symbol text NOT NULL REFERENCES stocks(symbol), as_of_date date NOT NULL,
 target_date date NOT NULL, horizon_sessions smallint NOT NULL CHECK(horizon_sessions IN (1,5)),
 target text NOT NULL CHECK(target IN ('direction_1d','return_1d','return_5d')),
 predicted_value double precision NOT NULL
 CHECK(predicted_value > '-Infinity'::float8 AND predicted_value < 'Infinity'::float8),
 model_run_id uuid NOT NULL REFERENCES model_runs(model_run_id), created_at timestamptz NOT NULL,
 CHECK(target_date>as_of_date),
 CHECK((target='return_5d' AND horizon_sessions=5) OR
       (target IN ('direction_1d','return_1d') AND horizon_sessions=1)),
 CHECK(target<>'direction_1d' OR predicted_value BETWEEN 0 AND 1),
 UNIQUE(symbol,as_of_date,target,model_run_id)
);
CREATE TABLE signals (
 signal_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 symbol text NOT NULL REFERENCES stocks(symbol), session_date date NOT NULL,
 rule_version text NOT NULL, signal text NOT NULL, details jsonb NOT NULL,
 created_at timestamptz NOT NULL, UNIQUE(symbol,session_date,rule_version)
);
CREATE TABLE anomalies (
 anomaly_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 symbol text NOT NULL REFERENCES stocks(symbol), session_date date NOT NULL,
 detector_version text NOT NULL, score double precision NOT NULL
 CHECK(score > '-Infinity'::float8 AND score < 'Infinity'::float8),
 details jsonb NOT NULL, created_at timestamptz NOT NULL,
 UNIQUE(symbol,session_date,detector_version)
);
CREATE INDEX prices_date_idx ON daily_prices(session_date);
CREATE INDEX predictions_date_idx ON predictions(as_of_date);
CREATE INDEX quality_run_idx ON quality_issues(run_id);
