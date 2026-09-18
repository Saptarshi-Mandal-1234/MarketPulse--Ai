# MarketPulse AI | Presentation guide

An Indian equity research project covering NIFTY 50 and ten large-cap stocks.
It turns archived market data into validated analytics, evaluated forecasts and a daily Power BI report.

## A five-minute demonstration

1. **Market Overview:** start with the input dates and data availability. Explain the current technical readings and why an older reading is labelled.
2. **Stock Explorer:** choose one instrument. Follow adjusted price and volume through time; clear the selection to compare instruments.
3. **Technical Analysis:** keep one instrument selected to inspect moving averages and MACD. With several instruments selected, these charts show averages, not a portfolio return.
4. **Risk Analytics:** compare volatility, drawdown and beta. Read the date next to the latest available risk readings.
5. **Prediction Center:** explain the three targets: next-session direction, next-session return and five-session return. Validation selected simple baselines; the project does not claim a profitable ML strategy. Direction values are probabilities; regression values are returns. Blank values are deliberately skipped forecasts.
6. **Anomalies:** read the flags first, then inspect the supporting scores. A flag is an unusual observation, not a confirmed data error or trade instruction.
7. **Daily Insights:** finish with the evidence and limitations, then explain automatic report generation at 4 PM IST on this laptop.

## What makes the project credible

- Preserved source snapshots and data-quality checks.
- No invented prices across gaps; indicator availability is explicit.
- Chronological model evaluation and baseline comparisons.
- A database-backed pipeline that preserves the last published report on failure.
- Reproducible exports, readable daily insights and a local operational check.

## Before presenting

Run **Check Project Health.cmd**, then open **Open Dashboard.cmd** and use **Home > Refresh**. Check the source dates; do not call an older snapshot live data. Keep the laptop online and logged in for the scheduled run. Special evening sessions need a later manual update.

## Reading key metrics

| Metric | Meaning |
|---|---|
| Daily return | Change from the previous valid session |
| Annualized volatility | Historical variability scaled to a year |
| Max drawdown | Largest observed peak-to-trough decline |
| Beta vs NIFTY | Historical sensitivity to benchmark returns |
| RSI (14) | Momentum indicator over 14 observations |
| ROC AUC | Ranking quality for the direction classifier |
| Brier score | Probability error; lower is better |
| MAE / RMSE | Return prediction errors; lower is better |

The report describes research results. It is not an execution or order-placement system.
