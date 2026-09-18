# Stage 3 complete — 2026-09-10

Status: **complete with documented exclusions**. The output is ready for Stage 4
feature engineering using the supplied session and eligibility masks.

Final quality run: `08211eda-8ece-48c3-a0d7-2ece69de1010`.
Refreshed download: `bf71a312-568b-4f87-b485-0e25df6a79c4`.
Narrow gap rechecks: `100e3748-e386-4b67-8ca4-30a8d8139eff`.

## Results

- 31,800 source rows: 31,726 retained and 74 quarantined.
- 141 instrument-session gaps: 111 absent source rows and 30 unusable session rows.
  These counts differ from quarantine totals because 44 quarantined rows are on
  non-trading dates and are not expected-session gaps.
- All 141 gaps were rechecked with narrow Yahoo history requests: 112 were absent
  and 29 still had invalid prices. A narrow request omitted one row that the full
  request represented as invalid; neither response supplied a usable replacement.
- Latest usable close across all eleven instruments is September 8, 2026.
- 31,586 one-session and 31,030 five-session price windows pass the gap masks,
  before feature warm-up, train/test splits and later modelling requirements.

The provider gaps were resolved operationally by exclusion, not by inventing or
recovering prices. Raw archives remain immutable and no canonical database prices
were loaded. Stage 5 will handle validated database loading.

## Calendar reconciliation

config/nse_sessions_reference.json now contains checked annual NSE Capital Market
holiday dates for 2015–2026, all annual Muhurat dates, and researched amendments:
election closures, the June 2023 holiday revision, and special sessions including
February 1, 2020/2025/2026 and the three 2024 Saturday sessions. It replaces the
holidays-library baseline, which omitted or misclassified some dates. Ordinary
weekends are closed; mock trading sessions are not included as real sessions.

The reference is deliberately bounded to January 1, 2015–September 9, 2026.
Requests outside that range fail until its coverage is reviewed. Calendar source
URLs and accessed mirror copies are recorded per year/amendment; direct PDF
downloads timed out, so local binary originals are not claimed. The 2016 and 2020
notices were inspected via publicly available copies of the NSE circulars.
This is a daily-session calendar, not an intraday close-time schedule.

## Validation and dispositions

The repeatable validator checks source checksums, row counts, schema, numeric
types, nulls, duplicate dates, sorting, invalid/infinite/nonpositive prices, OHLC
ordering, integer/nonnegative volume, zero/missing volume, adjusted close,
corporate-action values, unusually large observed returns and volume spikes,
calendar membership, missing sessions and latest-bar freshness.

Error rows are quarantined; every finding has a disposition in issues.csv. Valid
but unusual observations are retained without automatic repair. Source corporate
actions are preserved as events; independently certifying every historical event
and point-in-time adjustment vintage is outside this cleaning stage.

## Files and safe use

- `data/processed/08211eda-8ece-48c3-a0d7-2ece69de1010/aligned/`: preferred Stage 4 input, one row for every
  expected session for each instrument. Missing prices remain null.
- `data/processed/08211eda-8ece-48c3-a0d7-2ece69de1010/`: retained bars and lineage manifest.
- `data/quarantine/08211eda-8ece-48c3-a0d7-2ece69de1010/`: rejected rows with source positions and reasons.
- `reports/08211eda-8ece-48c3-a0d7-2ece69de1010/`: quality.md, issues.csv, calendar.csv, per-symbol gap lists,
  STAGE_3_COMPLETE.md and completion.json.
- `data/processed/latest.json`: pointer published only after a completed validation.

Use feature_eligible and volume_feature_eligible. Restart rolling calculations
when segment_id changes. Honor target_1d_eligible and target_5d_eligible; they
require every session in the horizon to be present. Missing endpoint/future bars
are ineligible. Plain retained files omit gaps and must not be used with an
unqualified shift/rolling operation. These masks prevent hidden gap jumps; they
do not replace chronological model validation or prevent all forms of leakage.

## Run and verify

Double-click **Validate Data.cmd** to validate the latest successful full-universe
download. A subset investigation cannot replace the full-universe input.
Fresh setup: install requirements-quality.txt and requirements-dev.txt.

```powershell
.\.venv\Scripts\python.exe -m marketpulse.quality.validate
.\.venv\Scripts\python.exe scripts/verify_quality.py data/processed/08211eda-8ece-48c3-a0d7-2ece69de1010/manifest.json
.\.venv\Scripts\python.exe scripts/close_stage3.py 08211eda-8ece-48c3-a0d7-2ece69de1010 100e3748-e386-4b67-8ca4-30a8d8139eff
```

Each run emits a dated report; no unattended schedule is enabled. The separate
closeout command proves that all excluded sessions match the reviewed source
snapshot and recheck evidence. For a new source snapshot, recheck its gaps before
claiming the same closeout. See scripts/recheck_gaps.py.

**Verification:** 41 tests pass, including special calendars, leakage across gaps,
quarantine, schema failures, retries, lineage and end-to-end output generation.
Code/dependency checks pass. Actual output hashes, sorted unique dates, positive
finite retained prices, row conservation and horizon masks pass verification.
All 141 recheck response hashes and the original gap inventory match the audit.

Stage 3 has no remaining user setup step. Next is Stage 4 feature engineering.
Model-ready remains false because features, targets and walk-forward evaluation
are later stages, not because any Stage 3 finding lacks a disposition.
This document supersedes the earlier provisional Stage 3 reports, retained for audit.
