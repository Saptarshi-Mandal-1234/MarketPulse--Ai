# MarketPulse AI

MarketPulse AI is a reproducible research pipeline for Indian equities. It downloads
daily OHLCV data, validates exchange sessions, computes 39 technical features, loads
versioned data into PostgreSQL, evaluates forecasting models, detects risk and anomaly
conditions, and publishes a seven-page Power BI report.

The initial universe is NIFTY 50 plus ten liquid large-cap stocks: RELIANCE, HDFCBANK,
ICICIBANK, INFY, TCS, BHARTIARTL, ITC, LT, SBIN, and HINDUNILVR.

> **Research only.** The tested machine-learning candidates did not outperform the
> selected simple baselines under the predefined validation criteria. The project does
> not claim a trading edge and does not place orders.

## What is included

- Immutable Yahoo Finance research snapshots with retries and checksums.
- NSE-session-aware validation with explicit gaps and no invented prices.
- Returns, moving averages, RSI, MACD, Bollinger Bands, ATR, momentum, volatility,
  volume, and 52-week features.
- PostgreSQL migrations and provenance-linked analytical tables.
- Performance, drawdown, beta, Sharpe, Sortino, and correlation analytics.
- Purged chronological evaluation for next-session direction, next-session return,
  and five-session return.
- Risk bands, statistical checks, and prior-only Isolation Forest anomaly detection.
- Atomic daily publication, last-good-report preservation, health checks, backups,
  and a Windows Task Scheduler helper.
- A generated Power BI Project with seven analytical pages.

## Architecture

```text
Market data -> immutable archive -> validation -> features -> PostgreSQL
                                                   |            |
                                                   v            v
                                              model tests    analytics/risk
                                                   \            /
                                                    dashboard export
                                                           |
                                                     Power BI report
```

See [ARCHITECTURE.md](docs/ARCHITECTURE.md),
[DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md), and
[FEATURE_DICTIONARY.md](docs/FEATURE_DICTIONARY.md) for detailed contracts.

## Requirements

- Windows 10/11 for the supplied launchers and scheduler registration.
- Python 3.11-3.14.
- PostgreSQL 16 or newer.
- Power BI Desktop for the dashboard.
- Internet access for fresh market-data downloads.

## Setup

```powershell
git clone <your-repository-url>
cd marketpulse-ai
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item .env.example .env
```

Create a dedicated PostgreSQL database and fill `.env` locally. Never commit that file.
The interactive Windows bootstrap can create the role, database, and private application
password:

```powershell
.\.venv\Scripts\python.exe scripts\setup_database.py
```

Or configure an existing database, then initialize it:

```powershell
.\.venv\Scripts\python.exe -m marketpulse.cli db-check
.\.venv\Scripts\python.exe -m marketpulse.cli db-init
```

## Run the pipeline

```powershell
.\.venv\Scripts\python.exe -m marketpulse.pipeline --daily
```

Register the optional local 4:00 PM IST Windows schedule:

```powershell
.\scripts\register_schedule.ps1
```

The laptop must be on, online, and logged in. Provider data can be delayed after the
close; validation preserves the previous report instead of publishing incomplete data.

## Build and open Power BI

Runtime data and the generated semantic model contain local paths, so they are excluded
from Git. After a successful pipeline run, generate the report:

```powershell
.\.venv\Scripts\python.exe scripts\build_powerbi.py
.\.venv\Scripts\python.exe scripts\verify_powerbi.py --output dashboards\MarketPulsePolished
```

Open `dashboards\MarketPulsePolished\MarketPulse AI - Enhanced.pbip` and choose
**Home -> Refresh**. On the configured machine, `Open Dashboard.cmd` opens it.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pip check
```

The current local release passes 68 tests plus independent archive, feature, database,
analytics, model, dashboard, and Power BI checks. Generated evidence is written under
`reports/` and excluded from Git.

## Repository policy

The following remain local and ignored: `.env`, virtual environments, downloaded market
data, trained model artifacts, reports, database backups, Power BI caches, and the
generated Power BI project. Empty directory markers preserve the expected layout.

Historical stage notes under `docs/` describe how the implementation was built. Current
operating instructions are in [START_HERE.md](START_HERE.md).

## Known limits

- Yahoo Finance is a research source, not an exchange-grade market feed.
- Historical adjusted data is not certified as point-in-time data.
- Correlated instruments and overlapping horizons reduce effective sample size.
- The operational NSE calendar ends on December 31, 2026 and must be extended before
  processing 2027 sessions.
- Power BI Desktop refresh is manual; Power BI Service publishing and gateway setup
  are outside this local repository.
