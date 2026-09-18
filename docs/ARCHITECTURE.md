# Architecture and decisions

Stage 1 delivers scaffolding only. Data download, feature computations, training,
dashboard and scheduling are later stages; package folders reserve their boundaries.

Provider adapter -> immutable raw files -> validation/quarantine -> canonical
PostgreSQL daily_prices -> versioned features -> analytics / walk-forward models
-> predictions / signals / anomalies -> reporting (future).

Use a local Python package with a src layout and configuration outside code.
PostgreSQL 16+ is the intended shared store; SQL migrations are checksum-tracked,
serialized with an advisory transaction lock and applied atomically. Never edit an
applied migration: append a numbered migration. No database or role is created by
the app; connect as the owner of a dedicated empty database. Use a separate limited
runtime role when deploying. Raw files remain outside Git. No credentials in code.

The initial dependency set deliberately contains only configuration and PostgreSQL
support plus development checks. requirements-data.txt prepares later ingestion;
ML and dashboard dependencies will be chosen and tested at their stages. This
machine uses Python 3.14; pyproject accepts 3.11–3.14. The local lock captures this
Windows/Python installation and is not a cross-platform guarantee.

Provider decision: prototype with yfinance's no-key research interface, preserving
an adapter boundary for licensed data. No API key is required at this stage.
Availability, adjustment semantics and symbol coverage must be verified in Stage 2.
Yahoo access is unofficial and described by the project as personal/research use;
commercial distribution requires a suitable data agreement. No scraping bypass.

Reference checks, 2026-09-10:
- NIFTY benchmark definition: https://www.niftyindices.com/indices/equity/broad-based-indices/nifty--50
- Provider and use limitations: https://github.com/ranaroussi/yfinance
- PostgreSQL constraints: https://www.postgresql.org/docs/current/ddl-constraints.html
- Psycopg Python support: https://www.psycopg.org/install/

Stage gates: 2 fetch and archive data; 3 validate/calendar checks; 4 features;
5 ingestion into the schema; 6 analytics; 7 models; 8 risk/signals; 9 reporting;
10 scheduling/operations. Later gates should produce a reviewable working result.
