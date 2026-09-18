# Stage 5 — PostgreSQL loading: complete

Run `Load Database.cmd` from the project folder. PostgreSQL is installed and the
private local `.env` is configured. No new credentials are required.

The loader checks source and feature hashes, uses an atomic transaction, retains
versioned session snapshots, and verifies every session and feature payload.
Repeating the current load does not duplicate rows. Reactivating an older dataset
is rejected because the current price cache would need rebuilding first.

Verified current dataset:

- 31,726 canonical daily prices and 31,726 technical indicator rows.
- 31,867 aligned sessions, including explicit unusable sessions.
- 4,270 calendar dates and 614 quality findings/dispositions.
- 39 predictors; warm-up values remain null.

`dataset_loads`, `validated_sessions`, `session_calendars`, and
`dataset_quality_issues` preserve dataset provenance. `active_dataset` identifies
the snapshot used by analytics; `current_validated_sessions` exposes that snapshot.
`daily_prices` is the current provider/window cache. Existing date-only calendars
do not populate `trading_sessions.close_at`: special-session close times are not
invented.

Canonical SQL prices use six decimal places. JSON payloads use pandas JSON
serialization (15 decimal precision, millisecond timestamps); source Parquet
archives retain their original precision. Verification respects these contracts.

`reports/stage5/database_load.json` records repeat-load verification.
`reports/stage5/verification.json` records price, calendar and issue reconciliation
and successful rejection of negative prices/volume using rolled-back probes.
Run `.venv\Scripts\python.exe scripts/verify_database.py` to repeat those checks.
