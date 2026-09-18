# Stage 6 — descriptive analytics: complete

Double-click `Build Analytics.cmd`. It reads a consistent, read-only PostgreSQL
snapshot and creates a new report folder under `reports/stage6`. `latest.json`
identifies the latest run. No network download or new credentials are required.
For a fresh environment install `requirements-analytics.txt` first.

The delivered analysis covers eleven instruments with common endpoints of
2015-01-02 and 2026-09-08. Outputs include price growth, daily returns, drawdowns,
annual volatility, CAGR, Sharpe, Sortino, beta against NIFTY, correlation and pair
counts, 60-session rolling volatility/beta, and selected-stock sector summaries.
The Markdown report includes four charts. CSV tables preserve numerical results;
the manifest identifies the source dataset, configuration, implementation checksum
and output checksums.

## Calculation contract

- Use eligible adjusted closes on the full ordered exchange-session grid.
- Simple return is P[t]/P[t-1]-1 only when both adjacent prices exist. Never fill
  prices or bridge a missing session. Risk statistics use remaining valid returns.
- Normalize all series to 100 on their first common available date. Endpoint return
  is final/initial-1. CAGR uses elapsed calendar days divided by 365.25.
- Annualized volatility is sample daily-return standard deviation times sqrt(252).
- Risk-free assumption is explicitly 0% annually in `config/analytics.json`.
  Convert any configured annual rate to daily using (1+rate)^(1/252)-1.
- Sharpe is mean daily excess return / sample standard deviation times sqrt(252).
- Sortino uses sqrt(mean(min(daily excess return,0)^2)) across ALL valid return
  observations as denominator, then the same mean and annualization as Sharpe.
- Beta uses sample covariance with NIFTY divided by NIFTY sample variance on
  same-session valid pairs. Correlation uses Pearson paired returns. Pair counts
  are exported. At least 30 observations are required for full-period risk ratios.
- Zero denominators produce nulls. Rolling metrics require all 60 return
  observations in the window; gaps interrupt them.
- Drawdown is price / running observed peak - 1. Missing observations may hide
  worse drawdowns. Endpoint return minus NIFTY return is a percentage-point
  difference, not risk-adjusted alpha.
- Sector summaries are unweighted constituent metric means for this selected
  basket, not sector-index returns or rebalanced portfolio performance.

Adjusted equity prices and the NIFTY price index are not like-for-like total-return
benchmarks. This surviving large-cap basket, provider revisions and excluded gaps
limit interpretation. These are descriptive results, not a trading backtest.

Stages 1–6 are complete. Stage 7 will create prediction targets and models with
time-ordered validation; no model training or future-return labels are included here.
