# Stage 4 complete — feature engineering

Feature run: a133c264-6929-4ba5-8335-c15d6782fccb.
Source quality run: 08211eda-8ece-48c3-a0d7-2ece69de1010.
Version: technical-v1.0.

Built 39 numeric features for NIFTY 50 and ten equities: returns/log returns,
SMA/EMA and distances, RSI, MACD, Bollinger Bands, ATR, momentum/ROC, volatility,
252-session high/low distances and volume statistics. Precise formulas, units,
seeds and warm-up requirements are in FEATURE_DICTIONARY.md.

31,867 session rows are preserved (2,897 per instrument), including 141 explicit
gap rows with null predictors. 27,245 rows have the seven core features available.
Core-ready does not mean all 39 features exist. Latest core-ready date is September
8, 2026 for ten instruments and September 4 for HINDUNILVR, whose September 7 gap
resets its indicator history.

## Deliverables

- data/features/a133c264-6929-4ba5-8335-c15d6782fccb/: eleven Parquet datasets and
  manifest containing predictor/metadata columns, configuration and source hashes.
- data/features/latest.json: pointer to the completed build.
- reports/a133c264-6929-4ba5-8335-c15d6782fccb/: features.md, coverage.csv with
  every instrument/feature's null counts, and verification.json.
- config/features.json and src/marketpulse/features/: reusable implementation.
- Build Features.cmd: double-click launcher.

## Reliability and limits

Rolling and recursive calculations restart after invalid price sessions. High/low
are adjusted consistently with close. Volume requires eligible positive share
volume; NIFTY volume predictors are null. Division by zero returns null. Windows
are not shortened to manufacture coverage. Future-dependent target availability
flags and labels are excluded from predictors.

All 52 tests pass, covering known values, Wilder seeds, gap resets, constant prices,
adjusted OHLC consistency, volume gaps, tamper rejection, end-to-end generation,
and unchanged past features when future rows change. Actual saved files passed
checksums, counts, gap nulls, indicator bounds and prefix-invariance checks for
every instrument. Code checks pass.

Inputs remain retrospective provider-adjusted snapshots. available_at reflects
actual source observation time, not a fabricated historical close-time timestamp.
Computational causality is checked; point-in-time investability is not certified.
No additional prices were downloaded or filled, no database writes were made,
and no models or background jobs were introduced.

## Rerun

Use the existing environment; no new dependencies or credentials are needed.
Fresh setup uses requirements-data.txt and requirements-dev.txt, or the recorded
requirements-lock.txt followed by editable package installation.

```powershell
.\.venv\Scripts\python.exe -m marketpulse.features.build
.\.venv\Scripts\python.exe scripts/verify_features.py
```

Each run writes a fresh folder and publishes latest.json only after completion.
Dataset identity includes hashes of the Stage 3 manifest, feature configuration,
universe, implementation and dependency versions. Use the manifest's predictor
allowlist to keep readiness/provenance metadata out of later model inputs.

Next is Stage 5: load validated prices and versioned features into PostgreSQL.
No further user intervention is needed for Stage 4.
