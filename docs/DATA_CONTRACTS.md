# Data contracts v1.0

Universe: NIFTY50 benchmark plus ten equities in config/universe.json. This is a
fixed research basket, not a reconstruction of historical index membership or a
claim these are today's ten most liquid stocks. Validate provider symbols and
traded-value coverage during Stage 2; maintain symbol/corporate-action history.
Stock prices are INR; NIFTY50 values are index points. Never interpret the index
as a directly tradable stock. Price-index returns are not total-return-index returns.

Daily input: symbol:string, session_date:ISO date in Asia/Kolkata,
open/high/low/close:positive finite decimal, adj_close:nullable positive decimal,
volume:nullable nonnegative integer, provider:string, adjustment:string,
observed_at:UTC timestamp, run_id:UUID. OHLC retains the provider basis with auto_adjust=False. Yahoo may already
split-adjust historical OHLC; do not assume original nominal as-traded prices. Keep source adjusted close separately. Missing equity
volume is flagged; index volume may be null. Zero volume is a warning, not a deletion.
Index adj_close may use close only with an explicit documented index-only mapping.
Never replace missing equity adjusted close with raw close for labels.

Raw responses are immutable under data/raw/{provider}/{run_id}/ with request
parameters, fetch timestamp, SHA256 and provider version. Nulls, duplicate keys,
nonfinite/negative prices, impossible OHLC and missing expected sessions are
reported; invalid rows go to quarantine. Do not forward-fill missing price bars.
Use an authoritative NSE session calendar including exceptional sessions; weekdays
alone are insufficient. Do not shift labels over missing exchange sessions.
Canonical key is (symbol,session_date,provider). Revisions create new raw snapshots;
the canonical table may be updated transactionally with new run provenance.
Dataset manifests identify exact raw checksums for reproducible training.

Features: (symbol,session_date,feature_version,dataset_sha256), available_at UTC,
values object of finite numeric values or null. Warm-up nulls remain null.
Version feature names, periods and adjustments. Never mix adjusted close with raw
high/low in an indicator without applying the same adjustment factor.

Targets use A(t)=adjusted close and exchange sessions, not calendar days:
- return_1d = A(t+1)/A(t)-1.
- return_5d = A(t+5)/A(t)-1 (cumulative simple return).
- direction_1d = 1 if return_1d > 0, else 0; ties are class 0.
Missing future prices produce null labels, never zero. Labels are separate from
features. Predictions store return fractions (0.01 means 1%) or P(direction=1).
Threshold 0.5 converts probability into a class for evaluation.

Prediction cutoff is 18:00 Asia/Kolkata on an exchange session, conditional on a
complete validated bar being available then; otherwise skip or record a later
actual cutoff. Every input must have available_at <= prediction cutoff.
Close-to-close targets describe research outcomes; the same close is not assumed
to be an executable entry after the cutoff. Later backtests need next-open entries,
costs and slippage. Store target_date, as_of_date, model version and creation time.

Time splits: use expanding walk-forward folds, fit transformations only on training
data, and purge every training label whose target_date reaches the validation start
(at least five sessions for the longest horizon). Reserve a final chronological
holdout. Start with a 3-year training window, 3-month validation folds, and final
12-month holdout if data coverage permits. Compare majority/zero-return baselines,
Logistic Regression, Random Forest, then XGBoost in Stage 7. Report balanced accuracy,
ROC-AUC and calibration for direction, MAE/RMSE for returns. No random splits.
Current-basket selection creates survivorship bias; retrospective adjusted data
can incorporate later revisions. Do not claim point-in-time investable performance
without vintage data and corporate-action availability checks.


Stage 3 handoff: use the bounded reviewed NSE daily-session reference in
config/nse_sessions_reference.json and data/processed/latest.json. Aligned outputs
include explicit absent-session nulls, segment_id boundaries and feature/volume/
one-session/five-session eligibility flags. Rows excluded as gaps are never filled.
OHLC data quality does not imply feature or trained-model readiness. The finite
calendar coverage must be extended explicitly before processing later dates.
