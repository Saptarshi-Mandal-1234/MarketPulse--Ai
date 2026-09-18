# MarketPulse AI — local quick start

1. Run **Run Daily Update.cmd**, or wait for the optional 4:00 PM IST scheduled run.
2. Confirm success with **Check Project Health.cmd**.
3. Open **MarketPulse AI - Enhanced** with **Open Dashboard.cmd**.
4. In Power BI Desktop, choose **Home -> Refresh**.
5. Check **As of** and **Data availability** before interpreting any reading.

The daily pipeline downloads data, validates it, builds features, loads PostgreSQL,
computes analytics and risk, and atomically publishes dashboard tables. An incomplete
update leaves the last good dashboard in place.

The targets are next-session direction, next-session return, and five-session return.
Current selections are research baselines because the tested ML candidates did not win
the predefined validation criteria. Blank forecasts are deliberately skipped when their
inputs or target dates are ineligible.

Generated data lives under `data/`, reports under `reports/`, and models under
`artifacts/`; all are excluded from Git. The generated Power BI project is also local
because it embeds the clone-specific path. Rebuild it after the first successful run.

The NSE operational calendar ends after December 31, 2026 and must be extended before
processing 2027 sessions. See [STAGES_8_10.md](docs/STAGES_8_10.md) for operations and
[DEMO_GUIDE.md](docs/DEMO_GUIDE.md) for a walkthrough.
