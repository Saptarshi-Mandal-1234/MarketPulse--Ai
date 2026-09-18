# Stage 7 — prediction engine

Run `Train Models.cmd` from the project folder. Fresh installations need
`requirements-models.txt`. The seeded CPU experiment reads checksum-verified
Stage 3 and 4 artifacts, trains models, and produces `reports/stage7/<run-id>`
and `artifacts/models/<run-id>`. A latest pointer is published only on success.

## Targets and inputs

Predict next-session direction (positive return = 1, zero/negative = 0),
next-session adjusted-close return, and cumulative five-session return.
Targets are saved separately in `targets.parquet`. Unknown outcomes remain null.
Five-session labels require every intervening session price to be eligible.
No label is shifted across a missing session.

Predictors are the 39 Stage 4 numeric features plus fixed-universe instrument
indicators. The model is pooled across eleven instruments. Core-ready rows are
required; other warm-up missing values use training-only median imputation,
with missingness indicators and training-only scaling. Feature metadata,
target dates, eligibility flags and outcome columns cannot enter the input matrix.

## Evaluation design

Three initial years precede expanding three-month validation folds. All stocks
share date boundaries. Reserve the final twelve calendar months as a single
untouched holdout. Purge training rows whose five-session outcome date reaches
the next evaluation start, including when training one-session models. Validation
outcome dates must remain within their evaluation block; this also prevents
validation model selection from using final-holdout outcomes.

Compare a class-frequency/majority or zero-return baseline, Logistic Regression
for direction (Ridge for returns), Random Forest and XGBoost. Fixed small model
configurations are recorded in `config/models.json`; no parameter search uses
the holdout. Select by lowest equal-fold mean Brier score for direction and MAE
for returns, including the baseline as a candidate. Evaluate only that selection
and the baseline on the final holdout. Saved models are fitted on purged
pre-holdout data; they have not been refitted on the holdout.

Report balanced accuracy, ROC-AUC, Brier loss, log loss and probability calibration
bins for direction; MAE/RMSE for returns. Errors are return fractions, not prices.
Per-symbol scores and counts help expose differences hidden by pooled results.
The results do not claim statistical significance: symbols and overlapping
five-session labels are correlated, and repeated folds are not independent trials.

## Reproducibility and scope

`manifest.json` records configuration, feature provenance, package versions,
implementation hash and output hashes. `split_audit.csv` records boundaries and
latest training outcome dates. `holdout_predictions.csv` contains dated predictions
and observed labels. Saved joblib files contain the fitted preprocessing pipeline,
input names and source dataset identity. Load only these locally generated files;
joblib is not an untrusted-file interchange format.

Run `.venv\Scripts\python.exe scripts/verify_models.py` to verify hashes, split
purging, metrics and reproduction of predictions from the saved models.

Historical provider revisions and actual 2026 archive timestamps mean this is
retrospective research, not a point-in-time backtest. No inputs are falsely
backdated to historical prediction cutoffs. There are no live predictions,
trading signals, order execution or profitability claims. Live inference needs
new validated observations and an extended calendar; it is outside Stage 7.

Reference APIs: [scikit-learn time-series validation](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
and [XGBoost Python API](https://xgboost.readthedocs.io/en/stable/python/python_api.html).
The implementation uses explicit shared date masks, not row-number splits,
because the input is a panel of multiple instruments per session.
