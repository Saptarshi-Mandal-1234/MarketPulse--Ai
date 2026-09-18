# Technical feature contract: technical-v1.0

All predictors are float values or null; no infinities. Each instrument has one row
per NSE session in the Stage 3 calendar. All windows include the current session
and use only current/past rows of the same uninterrupted valid-price segment.
The periods and core subset live in config/features.json. This version fixes the
10-session momentum, 20-session volume and 252-session range names/definitions;
changing these definitions requires a new feature version and code names.

Let C be source adjusted close; H/L are source high/low multiplied by
adjusted_close / source_close. This consistently adjusts every OHLC-dependent
indicator. No raw/adjusted mixing is allowed. Values are retrospective Yahoo
adjustments, not original as-traded prices or point-in-time adjustment vintages.

| Predictor | Definition and first availability within segment |
|---|---|
| return_1d, return_5d, return_20d | C(t)/C(t-n)-1; first available at n+1 observations. Fractions, not percentages. |
| log_return_1d | ln(C(t)/C(t-1)); second observation. |
| sma_5/10/20/50/200 | Arithmetic mean of n closes; n observations required. |
| distance_sma_5/10/20/50/200 | C/SMA-1; fractional distance. |
| ema_12/26/50 | Recursive EMA, alpha=2/(n+1); first close seeds recurrence, output hidden until n observations. |
| rsi_14 | 100-100/(1+average_gain/average_loss); Wilder averages seeded by the first 14 changes, then alpha=1/14. Available after 15 closes. Zero loss with positive gain gives 100; both zero gives 50; positive loss with zero gain gives 0. |
| macd | EMA12-EMA26; 26 closes. |
| macd_signal | Recursive 9-observation EMA of available MACD; 34 closes. |
| macd_histogram | MACD-signal; 34 closes. |
| bollinger_middle/upper/lower | 20-close SMA and SMA +/- 2 population standard deviations (ddof=0); 20 closes. |
| bollinger_width | (upper-lower)/middle. |
| bollinger_percent_b | (C-lower)/(upper-lower); null when bands coincide; not clipped to [0,1]. |
| atr_14 | Wilder average of max(H-L, abs(H-previous C), abs(L-previous C)); first segment TR=H-L; 14-observation arithmetic seed. |
| atr_fraction | ATR14/C. |
| momentum_10 | C(t)-C(t-10), in adjusted price/index units; 11 closes. |
| roc_10 | C(t)/C(t-10)-1; 11 closes. |
| volatility_20/60 | Sample standard deviation (ddof=1) of n log returns times sqrt(252); n+1 closes. Annualized fraction. |
| high_252, low_252 | Maximum adjusted H/minimum adjusted L across 252 sessions; 252 uninterrupted observations. A 52-week proxy, not exactly 365 calendar days. |
| distance_high_252, distance_low_252 | C/rolling extreme-1. |
| volume_change_1d | V(t)/V(t-1)-1; both positive/eligible. |
| volume_sma_20 | Mean of 20 positive, eligible share-volume observations in 20 consecutive sessions. |
| relative_volume_20 | V(t) divided by mean of preceding 20 sessions, excluding current session; 21 eligible observations. |

Volume is in provider-reported shares and is not adjusted using a dividend price
factor. Volume across corporate actions can contain genuine discontinuities; it is
not certified split-normalized. Zero/missing/invalid volume masks affected volume
windows. Index volume predictors are always null. Price features can remain valid
when volume predictors are unavailable. No warm-up or missing value is filled.

Metadata is separate from the manifest's explicit predictor_columns allowlist:
symbol, session_date, segment_age, input_valid, core_ready, available_at,
feature_version, dataset_sha256. Target eligibility flags are future-dependent and
are deliberately excluded. Stage 7 must join target masks separately by session.

core_ready requires return_1d, sma_20, ema_26, rsi_14, macd_signal, atr_14 and
volatility_20. It does not require 200/252-session or volume features and is not a
model-readiness claim. Later training must select features, apply warm-up masks,
and fit any imputer/scaler only on its training folds.

available_at conservatively uses the cumulative maximum of actual source observation
timestamps. Historical values collected today are not falsely timestamped as known
years earlier. Prefix-invariance tests establish computational causality within a
fixed snapshot; they cannot establish point-in-time availability of revised data.

Implementation references checked during build:
- https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.ewm.html
- Formula conventions above are the project's explicit contract; charting packages
  may differ in EMA/Wilder seeds, warm-up or standard-deviation conventions.
