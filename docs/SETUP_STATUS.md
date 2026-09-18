# Setup status

The repository contains the complete ten-stage local implementation. Machine-specific
state is excluded from version control: credentials, downloaded data, trained artifacts,
verification reports, backups, and generated Power BI files.

On a fresh clone, follow the root README to create the Python environment and PostgreSQL
database. Run the daily pipeline once before generating the Power BI project. Use
`Check Project Health.cmd` or `scripts/check_health.py` after the first successful run.

The maintained verification baseline is 68 tests, Ruff, dependency consistency, and
the stage-specific archive, feature, database, analytics, model, release, and Power BI
checks. Live database and report checks require locally generated data and credentials.
