# Contributing

Create a branch, keep changes focused, and run these checks before a pull request:

```powershell
python -m ruff check .
python -m pytest -q
python -m pip check
```

Do not commit credentials, `.env`, downloaded data, generated reports, trained models,
backups, or generated Power BI files. Indicator, target, calendar, and evaluation-rule
changes should include a contract update and leakage-focused test.

This is research software. Describe limitations honestly and do not present forecasts as
investment advice.
