# Stage 2 completed — 2026-09-10

Historical downloader installed and run successfully for NIFTY 50 and ten equities.
Run ID: df90317f-90c9-40ff-87ee-bdfa1be2fd3a.
Requested 2015-01-01 inclusive through 2026-09-10 exclusive.
All eleven instruments succeeded on their first attempt: 31,800 rows total.
Equities: 2,891 rows each, 2015-01-01 through 2026-09-09.
NIFTY50: 2,890 rows, 2015-01-02 through 2026-09-09.

Artifacts:
- data/raw/yahoo_research/{run_id}/: Parquet snapshots, original request, individual
  receipts, and final manifest with SHA256 hashes, parameters and library versions.
- reports/{run_id}/download.md: human-readable coverage summary.
- Download History.cmd: double-click launcher.
- scripts/verify_archive.py: offline checksum and row-count verification.

The archive preserves yfinance-returned DataFrames, including dividends/splits,
missing values, and separate Close/Adj Close. It is not a byte-for-byte capture of
Yahoo HTTP responses. auto_adjust, back_adjust and repair are disabled; keepna and
actions are enabled. Yahoo may itself revise or split-adjust historical values:
do not assume original as-traded nominal OHLC solely from auto_adjust=False.
No imputation, deduplication or OHLC repair is performed. Each download gets a new
UUID directory; prior runs remain intact. Interrupted runs retain request and
completed instrument receipts, but have no final manifest and are not complete.

Default end is today's date in India, exclusive, so current-day partial bars are
excluded. Start/end and required columns are checked; these are ingestion checks,
not exchange-calendar completeness certification. NIFTY has 13 null Close/Adj Close
values and 12 null Open/High/Low values in this snapshot. Stage 3 must investigate
those and the differing first session, plus calendar gaps, corporate actions,
invalid prices, volumes and freshness, before any model training.

Eight tests cover the foundation, archive fidelity, separate rerun directories,
checksums, retry exhaustion/recovery, date bounds, required columns and unknown
symbols. Ruff and dependency checks pass. A live PostgreSQL connection check passed
against 18.6. Stage 2 does not write unvalidated prices to the database; loading
validated canonical prices remains the database-layer stage.

Source parameters verified against the provider's documentation:
https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html
Data remains for personal research under the provider's stated use limitations.

Next: Stage 3 data cleaning and validation. No user credential intervention is
currently needed.
