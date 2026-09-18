# Stages 8–10: risk, reporting and daily operations

## Stage 8 — analytical signals

`marketpulse.signals.risk` computes an explainable technical vote from EMA12 versus
EMA26, MACD versus its signal, and 20-session return. Mean votes at least +0.5
are Bullish, at most -0.5 Bearish, otherwise Neutral. These are observations,
not order instructions or model forecasts. Thresholds are in `config/risk.json`.

Annualized 20-session log-return volatility below 15% is Low; at least 35% is
High Risk; the middle range is Moderate. Relative volume at least twice the prior
20-session mean flags Abnormal Volume. Index volume remains unavailable.

Isolation Forest uses at most 252 earlier core-ready observations (minimum 120),
with training-only median imputation and 5% configured contamination. A negative
decision-function value flags an anomaly; it is not a probability. The current
observation never enters detector fitting. A separate absolute z-score of at least
3 flags return surprises, using up to 60 previous returns within the current valid
segment, minimum 40. Neither anomaly flag deletes a price.

Output rows include the observation date, training end, availability and freshness.
An old core-ready observation can be shown for context but is explicitly marked
stale. No inference is made by filling missing sessions. Runs and results are
reconciled into versioned `risk_runs` and `risk_observations` PostgreSQL tables.

## Stage 9 — Power BI and daily insights

Open `Open Dashboard.cmd` or `dashboards/MarketPulseRelease/MarketPulseRelease.pbip`.
Seven report pages cover Market Overview, Stock Explorer, Technical Analysis,
Prediction Center, Risk Analytics, Anomalies, and Daily Insights.

The import-mode semantic model contains eight tables and instrument relationships.
It reads local CSV exports through `data/dashboard/current.json`, so Power BI
does not need the PostgreSQL password. Click **Home → Refresh** after a completed
pipeline update; import-mode Power BI Desktop does not automatically refresh an
already-open report when files change. Avoid refreshing while a pipeline is
publishing a new snapshot. Cloud scheduled refresh requires a Power BI workspace,
gateway and account, none of which is needed for this local edition.

The generated `Insights` table and `reports/daily/<snapshot>/DAILY_REPORT.md` use
deterministic statements from measured data; no language-model/API key is needed.
The Prediction Center shows Stage 7 validation results and forecast eligibility.
Only the validated selected models are used; all currently selected models are
baselines. Stale inputs, unavailable cutoffs or elapsed/unknown target dates create
skipped forecasts with null values. Every forecast is research-only, records its
original model run, and makes no claim of improved prediction or tradable return.

Use `scripts/build_powerbi.py` to regenerate report source before opening Desktop.
Do not regenerate it over manual report edits. `scripts/verify_powerbi.py` validates
the public Microsoft schemas and field references. Power BI can upgrade schema
versions on save. Keep `.pbi` caches and local settings out of Git.

## Stage 10 — local daily deployment

The Windows task **MarketPulse AI Daily** runs at **16:00 IST**.
The laptop must be powered on, connected and logged into this Windows account.
The task is limited to the current user and stores no Windows password. A missed
trigger can run when the laptop becomes available. Two-hour execution bounds and
an exclusive PostgreSQL advisory lock prevent overlapping pipeline runs.

`Run Daily Update.cmd` runs it manually. The workflow:

1. Determine the latest eligible exchange session (normal cutoff 16:00, special
   sessions 21:30), using the sourced operational calendar.
2. Archive a fresh full adjusted-price snapshot for all eleven instruments. Full
   history intentionally captures provider corporate-action revisions consistently.
3. Validate/quarantine and require a usable expected-session price for every symbol.
4. Build features, load/reconcile PostgreSQL, generate analytics and risk results.
5. Apply the selected historical models only where eligible; record skips explicitly.
6. Write complete dashboard tables and insights, then atomically switch the snapshot pointer.
7. Record stage logs and final status locally and in PostgreSQL.

Two provider attempts after the first failure have bounded backoff. A failed stage
stops later work. The published dashboard remains the last good snapshot until a
complete export succeeds; intermediates and database staging may already have
advanced, and are rebuilt on the next run. There is no claim of a single distributed
transaction across the provider, filesystem and database.

Inspect `reports/pipeline/latest.json`, per-run stage logs and `schedule.json`.
Failures are local logs, not unsolicited email/Slack messages. The second daily
trigger checks delayed observations. Already-current, fully feature-ready snapshots
are skipped; incomplete feature history can be rechecked at the second trigger.
`Replay Pipeline.cmd` exercises processing from the current immutable raw archive
without downloading. Replay is explicitly labelled and can retain stale history.

The operational calendar is bounded through **2026-12-31**. Exchange amendments
must be reviewed when announced, and the 2027 calendar must be supplied before
January runs. Out-of-range dates fail closed. The original historical reference
is preserved separately so old manifests remain auditable.

## Backup and recovery

`scripts/backup_database.py` makes a custom-format PostgreSQL backup and verifies
its archive inventory. It passes credentials through the environment, not command
arguments. A backup was created locally; restore testing into a separate database
is still needed before treating this as a disaster-recovery guarantee.

Preserve the entire project, including ignored data, model artifacts, reports,
backups and the private `.env`, on your own protected backup storage. Git alone
does not contain those files. Never publish `.env` or the private Power BI cache.

To restore, create a separate empty database, point private connection settings at
it, and use PostgreSQL `pg_restore --no-owner --no-privileges` with the chosen dump.
Never restore over the active database without a separately verified backup.
Raw archives plus the replay command can reconstruct the analytical layers.

Docker/Airflow migration and Power BI Service publishing are optional subsequent
deployments; this delivered runtime is the agreed Windows laptop edition.


Schedule updated: one daily trigger at 16:00 IST, 30 minutes after the regular NSE equity close. The former 18:15 and 21:30 triggers are removed. Special evening sessions require a manual run after their existing 21:30 eligibility cutoff; the 16:00 trigger cannot collect an evening session. If the provider has not supplied the completed daily bars, validation preserves the previous report and records the failed run. Power BI Desktop still requires Refresh to display a newly published snapshot.
